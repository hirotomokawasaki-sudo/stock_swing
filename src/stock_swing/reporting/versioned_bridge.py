"""Explicit versioned adjustment publication; no live defaults or broker I/O.

The existing schema-1 builder/history fingerprint remain authoritative. This
envelope adds the exact cooperating ledger epoch and typed income/capital.
Publication is immutable and never updates the legacy active artifact/pointer.
"""
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile

from stock_swing.tracking.compatibility import read_analysis_snapshot
from stock_swing.tracking.ledger_transaction import ledger_transaction, LedgerConflict, FILES
from stock_swing.reporting.equity_bridge_reconciliation import compute_tracker_history_fingerprint

VERSION = 'revision-bound-adjustment-v1-20261110'


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _time(value):
    if not isinstance(value, str):raise ValueError('aware timestamp required')
    t = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if t.utcoffset() is None:raise ValueError('aware timestamp required')
    return t


def _money(value):
    if isinstance(value, bool) or value is None:raise ValueError('finite money required')
    try:d = Decimal(str(value))
    except Exception as exc:raise ValueError('finite money required') from exc
    if not d.is_finite():raise ValueError('finite money required')
    return d


def typed_cash_components(activities, *, baseline_date):
    """Do not label dividends as deposits, or unknown activity types as zero."""
    from datetime import date
    baseline = date.fromisoformat(baseline_date)
    if not isinstance(activities, list):raise ValueError('complete activity list required')
    result = dict(fees=Decimal(0), income=Decimal(0), external_capital=Decimal(0))
    seen = set()
    for row in activities:
        if not isinstance(row, dict):raise ValueError('invalid activity')
        stamp = str(row.get('transaction_time') or row.get('date') or '')
        if date.fromisoformat(stamp[:10]) < baseline:continue
        identity = row.get('id')
        if not isinstance(identity, str) or not identity or identity in seen:raise ValueError('missing/duplicate activity identity')
        seen.add(identity)
        kind = row.get('activity_type')
        if kind in {'FILL','SPLIT'}:continue
        if kind not in {'FEE','DIV','CSD','CSW'}:raise ValueError('unclassified cash activity')
        if row.get('currency') != 'USD' or row.get('status') != 'executed':raise ValueError('unqualified cash activity')
        amount = _money(row.get('net_amount'))
        if kind == 'FEE':
            if amount > 0:raise ValueError('fee refund needs an explicit contract')
            result['fees'] -= amount
        elif kind == 'DIV':
            if amount < 0:raise ValueError('negative dividend needs an explicit contract')
            result['income'] += amount
        else:
            if (kind == 'CSD' and amount < 0) or (kind == 'CSW' and amount > 0):raise ValueError('capital sign mismatch')
            result['external_capital'] += amount
    return {key:str(value) for key,value in result.items()}


def capture_epoch(root):
    """Current four-file hashes under the existing lock, without recovery."""
    root = Path(root).resolve()
    with ledger_transaction(root, recover=False, blocking=False) as tx:
        state, provenance = read_analysis_snapshot(root/'data/tracking/pnl_state.json')
        hashes = {}
        for name in FILES:
            raw = tx.read(root/'data/tracking'/name)
            if raw is None:raise LedgerConflict('missing financial input: '+name)
            hashes[name] = sha256(raw).hexdigest()
        return dict(ledger_revision=provenance['ledger_revision'], four_file_sha256=hashes,
                    account_id=state.get('broker_account_id'), baseline_equity=state.get('baseline_equity'),
                    cooperating_lock_only=True), state


def _validate_snapshot(snapshot, state, components):
    if (not isinstance(snapshot, dict) or type(snapshot.get('schema_version')) is not int
            or snapshot['schema_version'] != 1):raise ValueError('existing snapshot schema required')
    if snapshot.get('broker_account_id') != state.get('broker_account_id'):raise ValueError('account mismatch')
    if snapshot.get('baseline_date') != state.get('baseline_date'):raise ValueError('baseline date mismatch')
    if _money(snapshot.get('baseline_equity')) != _money(state.get('baseline_equity')):raise ValueError('baseline mismatch')
    count, fingerprint = compute_tracker_history_fingerprint(state['trades'], cutoff=snapshot.get('last_filled_at'))
    if count != snapshot.get('tracker_closed_count_at_reconciliation') or fingerprint != snapshot.get('tracker_history_fingerprint'):
        raise ValueError('history fingerprint mismatch')
    if set(components) != {'fees','income','external_capital'}:raise ValueError('typed cash schema')
    values = {k:_money(v) for k,v in components.items()}
    if values['fees'] < 0 or values['income'] < 0:raise ValueError('negative fee/income')
    if abs(_money(snapshot.get('fees'))-values['fees']) > Decimal('.005'):raise ValueError('fee decomposition mismatch')
    if abs(_money(snapshot.get('external_cash_adjustment'))-values['income']-values['external_capital']) > Decimal('.005'):
        raise ValueError('cash decomposition mismatch')
    for name in ['realized_pnl_adjustment','quarantined_pnl_adjustment','account_check_expected_equity','broker_equity_at_reconciliation']:_money(snapshot.get(name))
    if abs(_money(snapshot.get('account_check_diff'))) > Decimal('.02'):raise ValueError('cash check outside reviewed bound')
    expected=(_money(snapshot['baseline_equity'])+_money(snapshot['external_cash_adjustment'])
              +_money(snapshot['broker_order_cash_realized'])+_money(snapshot['broker_unrealized_at_reconciliation'])
              -_money(snapshot['fees']))
    if abs(_money(snapshot['account_check_expected_equity'])-expected) > Decimal('.02'):
        raise ValueError('expected equity mismatch')
    if abs(_money(snapshot['broker_order_cash_realized'])-_money(snapshot.get('tracker_realized_at_reconciliation'))
           -_money(snapshot['realized_pnl_adjustment'])) > Decimal('.02'):
        raise ValueError('realized adjustment mismatch')
    if (_money(snapshot['quarantined_pnl_adjustment']) != 0
            or snapshot.get('quarantine_policy') != 'unverified_reconstruction_pnl_is_observability_only'):
        raise ValueError('quarantine is observability only')
    if abs(_money(snapshot['broker_equity_at_reconciliation'])-expected-_money(snapshot['account_check_diff'])) > Decimal('.02'):
        raise ValueError('cash identity mismatch')
    _time(snapshot.get('generated_at'));_time(snapshot.get('last_filled_at'))


def build_versioned_snapshot(*, snapshot, state, epoch, components, acquisition):
    _validate_snapshot(snapshot, state, components)
    if not isinstance(acquisition, dict) or set(acquisition) != {'cutoff','received_at','raw_sha256','currency','atomic_all_writer_snapshot'}:
        raise ValueError('acquisition schema')
    if (acquisition['currency'] != 'USD' or acquisition['atomic_all_writer_snapshot'] is not False
            or _time(acquisition['received_at']) < _time(acquisition['cutoff'])
            or _time(snapshot['last_filled_at']) > _time(acquisition['cutoff'])):raise ValueError('acquisition cutoff/coverage')
    raw_hash = acquisition['raw_sha256']
    if not isinstance(raw_hash,str) or len(raw_hash)!=64 or any(c not in '0123456789abcdef' for c in raw_hash):raise ValueError('raw response hash')
    if epoch.get('account_id') != state.get('broker_account_id') or epoch.get('baseline_equity') != state.get('baseline_equity'):
        raise ValueError('epoch identity mismatch')
    payload=dict(version=VERSION, ledger_epoch=epoch, snapshot=snapshot,
                 cash_components=components, acquisition=acquisition,
                 performance_qualified=False, settled_cash_qualified=False,
                 promotion_authorized=False)
    # JSON normalization removes caller references and rejects nonfinite values.
    payload=json.loads(_encode(payload))
    return dict(payload=payload, sha256=sha256(_encode(payload)).hexdigest())


def _validate_envelope(envelope, *, state, expected_revision):
    if not isinstance(envelope,dict) or set(envelope)!={'payload','sha256'}:raise ValueError('versioned envelope')
    p=envelope['payload']
    if sha256(_encode(p)).hexdigest()!=envelope['sha256'] or p.get('version')!=VERSION:raise ValueError('versioned checksum/schema')
    if p['ledger_epoch']['ledger_revision']!=expected_revision:raise ValueError('ledger revision mismatch')
    if p.get('performance_qualified') is not False or p.get('settled_cash_qualified') is not False or p.get('promotion_authorized') is not False:
        raise ValueError('unearned qualification')
    rebuilt=build_versioned_snapshot(snapshot=p['snapshot'],state=state,epoch=p['ledger_epoch'],components=p['cash_components'],acquisition=p['acquisition'])
    if rebuilt!=envelope:raise ValueError('noncanonical envelope')
    return p


def publish_versioned_snapshot(root, envelope):
    """Immutable CAS publication to a revision directory; no active switch."""
    root=Path(root).resolve()
    with ledger_transaction(root,recover=False,blocking=False):
        epoch,state=capture_epoch(root)
        p=_validate_envelope(envelope,state=state,expected_revision=epoch['ledger_revision'])
        if epoch!=p['ledger_epoch']:raise LedgerConflict('financial preimage changed')
        revision=epoch['ledger_revision']
        if not isinstance(revision,str) or not revision or any(c not in '0123456789abcdef' for c in revision):
            raise ValueError('explicit corrected ledger revision required')
        folder=root/'data/audits/equity_bridge_versions'/revision
        # Do not follow an alternate destination to an active or external file.
        if any(parent.is_symlink() for parent in [root/'data',root/'data/audits',folder.parent,folder]):raise ValueError('symlinked publication path')
        folder.mkdir(parents=True,exist_ok=True)
        destination=folder/(envelope['sha256']+'.json');encoded=_encode(envelope)+b'\n'
        if destination.exists():
            if destination.is_symlink() or destination.read_bytes()!=encoded:raise LedgerConflict('immutable artifact conflict')
            return destination
        fd,temporary=tempfile.mkstemp(prefix='.prepared-',dir=folder)
        try:
            with os.fdopen(fd,'wb') as h:h.write(encoded);h.flush();os.fsync(h.fileno())
            for name,wanted in epoch['four_file_sha256'].items():
                if sha256((root/'data/tracking'/name).read_bytes()).hexdigest()!=wanted:raise LedgerConflict('noncooperating financial change')
            try:os.link(temporary,destination)
            except FileExistsError:
                if destination.is_symlink() or destination.read_bytes()!=encoded:raise LedgerConflict('immutable artifact conflict')
            directory=os.open(folder,os.O_RDONLY)
            try:os.fsync(directory)
            finally:os.close(directory)
        finally:
            if os.path.exists(temporary):os.unlink(temporary)
        return destination


def load_versioned_snapshot(path, *, root, expected_revision):
    """Normal reader validates lineage and cutoff history, not old raw hashes.

    Legitimate subsequent snapshots/fills do not reset this revision-bound
    historical reconciliation. It does not imply current broker freshness.
    """
    try:
        path=Path(path).absolute()
        if any(p.is_symlink() for p in [path,*path.parents]):raise ValueError('symlinked artifact path')
        envelope=json.loads(path.read_text())
        epoch,state=capture_epoch(root)
        if epoch['ledger_revision']!=expected_revision:raise ValueError('current ledger revision mismatch')
        p=_validate_envelope(envelope,state=state,expected_revision=expected_revision)
        return dict(snapshot=p['snapshot'], cash_components=p['cash_components'],
                    ledger_revision=expected_revision, observed_cutoff=p['acquisition']['cutoff'],
                    performance_qualified=False, settled_cash_qualified=False)
    except (OSError,ValueError,KeyError,TypeError,LedgerConflict):
        return None


def load_selected_reconciliation(root, *, expected_account_id, currency,
                                 current_trades=None, environment=None):
    """Read one explicitly selected immutable artifact, never the old active.

    The receipt is historical accounting evidence, not current account/cash
    freshness. The nonblocking cooperating lock also rejects prepared journals.
    Unknown selectors, identities or a caller's stale trade cache are unavailable.
    """
    import re
    env = os.environ if environment is None else environment
    revision = env.get('EQUITY_BRIDGE_LEDGER_REVISION', '')
    artifact = env.get('EQUITY_BRIDGE_ARTIFACT_SHA256', '')
    try:
        if (not isinstance(revision, str) or not re.fullmatch('[0-9a-f]{64}', revision)
                or not isinstance(artifact, str) or not re.fullmatch('[0-9a-f]{64}', artifact)
                or currency != 'USD' or not expected_account_id):
            return None
        root = Path(root).absolute()
        path = root/'data/audits/equity_bridge_versions'/revision/(artifact+'.json')
        with ledger_transaction(root, recover=False, blocking=False):
            epoch, state = capture_epoch(root)
            if (epoch['ledger_revision'] != revision
                    or state.get('broker_account_id') != expected_account_id
                    or (current_trades is not None and _encode(current_trades) != _encode(state['trades']))):
                return None
            # Filename is part of the explicit selector, not merely a path hint.
            envelope = json.loads(path.read_text())
            if envelope.get('sha256') != artifact:
                return None
            got = load_versioned_snapshot(path, root=root, expected_revision=revision)
            if got is None:
                return None
            return dict(got['snapshot'], income_cash=float(got['cash_components']['income']),
                external_capital_cash=float(got['cash_components']['external_capital']),
                ledger_revision=revision, reconciliation_artifact_sha256=artifact,
                acquisition_cutoff=got['observed_cutoff'],
                method='explicit_immutable_revision_bound_cash_reconciliation',
                current_account_freshness_qualified=False, settled_cash_qualified=False)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, LedgerConflict):
        return None
