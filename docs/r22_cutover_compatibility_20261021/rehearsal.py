"""Offline COPY-ONLY cutover/rollback rehearsal; not a deployment command.

Uses the existing transaction protocol, not a second journal implementation.
Original bytes stay in memory/private input storage; report contains only hashes
and invariants. Does not pause schedulers or prove operational quiescence.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import tempfile

from stock_swing.tracking.compatibility import legacy_maintenance, read_tracking_state
from stock_swing.tracking.history_migration import apply_migration, parse_events, validate_history_pair
from stock_swing.tracking.ledger_transaction import FILES, LedgerConflict, digest, ledger_transaction
from stock_swing.tracking.pnl_tracker import PnLTracker


def snapshot(root):
    with ledger_transaction(root, recover=False) as tx:
        data = {name: tx.read(root/'data/tracking'/name) for name in sorted(FILES)}
        if any(value is None for value in data.values()):
            raise LedgerConflict('incomplete four-file backup')
        validate_history_pair(json.loads(data['pnl_state.json']), parse_events(data['trade_events.jsonl']))
        return {'bytes': data, 'sha256': {n:digest(b) for n,b in data.items()}}


def restore_copy(root, backup, expected_current):
    # Only roots created by this rehearsal. Not an operator restore API.
    if not (root/'.r22-rehearsal-copy').is_file():
        raise LedgerConflict('copy-only restore')
    if set(backup['bytes']) != FILES or set(backup['sha256']) != FILES or set(expected_current) != FILES:
        raise LedgerConflict('incomplete backup manifest')
    if any(digest(b) != backup['sha256'][n] for n,b in backup['bytes'].items()):
        raise LedgerConflict('backup hash mismatch')
    validate_history_pair(json.loads(backup['bytes']['pnl_state.json']),parse_events(backup['bytes']['trade_events.jsonl']))
    with ledger_transaction(root, recover=False) as tx:
        current = {n:digest(tx.read(root/'data/tracking'/n)) for n in FILES}
        if current != expected_current:
            raise LedgerConflict('new or conflicting writes; old backup restore forbidden')
        for name, data in backup['bytes'].items():
            tx.stage(root/'data/tracking'/name, data)


def run_rehearsal(inputs, plan):
    with tempfile.TemporaryDirectory(prefix='r22-cutover-copy-') as temp:
        root=Path(temp);folder=root/'data/tracking';folder.mkdir(parents=True)
        (root/'.r22-rehearsal-copy').write_text('copy only')
        for n,b in inputs.items():(folder/n).write_bytes(b)
        before=snapshot(root)
        assert apply_migration(root,plan)['status']=='applied'
        after=snapshot(root)
        state=read_tracking_state(folder/'pnl_state.json')
        assert state['measurement_lineage']['promotion_ready'] is False
        try:
            with legacy_maintenance(root):raise AssertionError('old writer entered')
        except LedgerConflict:pass
        restore_copy(root,before,after['sha256'])
        assert snapshot(root)['bytes']==before['bytes']
        assert apply_migration(root,plan)['status']=='applied'
        tracker=PnLTracker(root)
        tracker.state.last_updated='2026-10-21T07:00:00Z'
        tracker._save_state()
        forward=snapshot(root)
        assert forward['sha256']!=after['sha256']
        try:
            restore_copy(root,before,after['sha256'])
            raise AssertionError('new observation discarded')
        except LedgerConflict:pass
        assert snapshot(root)==forward
        damaged=deepcopy(before);damaged['bytes']['pnl_state.json']+=b' '
        try:
            restore_copy(root,damaged,forward['sha256'])
            raise AssertionError('damaged backup accepted')
        except LedgerConflict:pass
        assert snapshot(root)==forward
        return {'cutover':'passed','exact_four_file_restore':'passed','legacy_writer':'blocked',
                'late_write_rollback':'refused_preserved','damaged_backup':'refused_preserved',
                'old_snapshots':'preserved_as_observed','promotion_ready':False,
                'before_sha256':before['sha256'],'after_sha256':after['sha256'],
                'closed_after':sum(r.get('status')=='closed' for r in state['trades']),
                'quarantine_after':len(state['quarantined_trades']),
                'pnl_after':round(sum(r.get('pnl',0) or 0 for r in state['trades'] if r.get('status')=='closed'),2),
                'scope':'copy-only; scheduler drain, code rollout, production restore NOT executed'}
