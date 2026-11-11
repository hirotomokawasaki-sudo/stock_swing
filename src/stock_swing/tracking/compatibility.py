"""Coherent consumers and fail-closed boundaries for pre-history maintenance.

Readers acquire the cooperating writer lock but never recover/modify a ledger.
Pending recovery is unavailable, not an empty or cached successful result.
These guards do not protect against unknown programs or an old code checkout.
"""
from contextlib import contextmanager
from functools import wraps
import json
from pathlib import Path

from .history_migration import parse_events, validate_history_pair
from .ledger_transaction import LedgerConflict, ledger_transaction, digest


def tracking_root(state_path):
    path = Path(state_path).absolute()
    if path.name != 'pnl_state.json' or path.parent.name != 'tracking' or path.parent.parent.name != 'data':
        raise LedgerConflict('unsupported legacy state path; use canonical data/tracking/pnl_state.json')
    return path.parents[2]


def read_tracking_state(state_path):
    """Fresh independent state, validated against events in the same lock epoch."""
    return read_tracking_evidence(state_path)[0]


def read_tracking_evidence(state_path):
    """Return state and exact input fingerprints from one cooperating lock epoch.

    Fingerprints identify an observation, not an economic qualification. No
    automatic journal recovery; callers must not launder an error as empty data.
    """
    root = tracking_root(state_path)
    if not (root / 'data/tracking').exists():
        raise FileNotFoundError(state_path)
    with ledger_transaction(root, recover=False) as tx:
        folder = root/'data/tracking'
        raw = tx.read(folder/'pnl_state.json')
        state = json.loads(raw) if raw is not None else {}
        if not isinstance(state, dict):
            raise LedgerConflict('tracking state must be an object')
        if state.get('history_migrations') and not isinstance(state.get('measurement_lineage'), dict):
            raise LedgerConflict('missing measurement lineage')
        event_bytes = tx.read(folder/'trade_events.jsonl')
        events = parse_events(event_bytes)
        validate_history_pair(state, events)
        if raw is None:
            raise FileNotFoundError(state_path)
        return state, {
            'state_sha256': digest(raw),
            'events_sha256': digest(event_bytes) if event_bytes is not None else None,
            'measurement_lineage': state.get('measurement_lineage'),
            'scope': 'current_active_ledger_not_performance_qualification',
        }


def read_analysis_snapshot(state_path):
    """Coherent descriptive input and provenance, never performance approval.

    The hashes identify the exact state/events pair used in this observation.
    A ledger revision identifies a historical correction boundary, not a new
    strategy, qualified session series, or authorization to promote capital.
    """
    state, evidence = read_tracking_evidence(state_path)
    if 'trades' not in state:
        raise LedgerConflict('missing tracking collection: trades')
    for key in ('trades', 'quarantined_trades'):
        rows = state.get(key, [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise LedgerConflict('invalid tracking collection: ' + key)
    # reconciled_removed is retained by legacy PnLTracker summaries as well as
    # the current open/closed/quarantined states. Typos cannot disappear into
    # status filters and overwrite an existing report with an empty success.
    if any(row.get('status') not in ('open', 'closed', 'quarantined', 'reconciled_removed')
           for row in state['trades']):
        raise LedgerConflict('invalid trade status')
    lineage = state.get('measurement_lineage')
    if lineage is not None and (not isinstance(lineage, dict)
            or not isinstance(lineage.get('ledger_revision'), str)
            or not lineage.get('ledger_revision')
            or not isinstance(lineage.get('measurement_status'), str)):
        raise LedgerConflict('invalid measurement lineage')
    return state, {
        'schema_version': 1,
        'ledger_revision': lineage['ledger_revision'] if lineage else 'legacy',
        'state_sha256': evidence['state_sha256'],
        'events_sha256': evidence['events_sha256'],
        'measurement_status': lineage['measurement_status'] if lineage else 'legacy_unqualified',
        'scope': 'descriptive_active_ledger_not_performance_qualification',
        'promotion_ready': False,
    }


def legacy_analytical_state(state_path):
    """Stop unversioned analyses before derived files, recommendations or I/O.

    Only the canonical state/events pair is supported. A standalone JSON export
    cannot establish that supersession markers or a prepared journal are absent.
    This is intentionally not an override switch for corrected history.
    """
    state, _ = read_analysis_snapshot(state_path)
    if state.get('history_migrations') or state.get('measurement_lineage'):
        raise LedgerConflict('analysis unavailable: corrected history is unqualified; use a lineage-aware analysis')
    return state


@contextmanager
def legacy_maintenance(project_root):
    """Serialize the whole legacy operation; forbid use after historical change."""
    root = Path(project_root).resolve()
    with ledger_transaction(root, recover=False) as tx:
        folder = root/'data/tracking'
        raw = tx.read(folder/'pnl_state.json')
        state = json.loads(raw) if raw is not None else {}
        events = parse_events(tx.read(folder/'trade_events.jsonl'))
        validate_history_pair(state, events)
        if state.get('history_migrations') or state.get('measurement_lineage'):
            raise LedgerConflict('legacy maintenance blocked: historical migration requires lineage-aware repair')
        yield


def legacy_entrypoint(root_getter):
    """Also usable on low-level save functions to prevent import/API bypass."""
    def decorate(function):
        @wraps(function)
        def call(*args, **kwargs):
            with legacy_maintenance(root_getter(*args, **kwargs)):
                return function(*args, **kwargs)
        return call
    return decorate
