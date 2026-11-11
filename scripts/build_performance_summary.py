#!/usr/bin/env python3
"""Versioned descriptive export; never an economic or promotion qualification.

No tracker construction, recovery, snapshot recording or unknown-to-zero fallback.
Only a coherent state/events pair may replace the last exported observation.
"""
from __future__ import annotations
import json
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / 'src'))
from stock_swing.tracking.compatibility import read_analysis_snapshot
from stock_swing.tracking.ledger_transaction import ledger_transaction
from stock_swing.sources.broker_client import BrokerClient


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError('missing numeric input')
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('nonfinite input')
    return number


def export(root, broker):
    root = Path(root)
    state_path = root/'data/tracking/pnl_state.json'
    state, provenance = read_analysis_snapshot(state_path)
    closed = [t for t in state['trades'] if t['status'] == 'closed']
    pnl = [_finite(t.get('pnl')) for t in closed]
    realized = math.fsum(pnl)
    if abs(realized - _finite(state.get('cumulative_realized_pnl'))) > 1:
        raise ValueError('closed PnL/state cumulative mismatch')
    # Missing external values remain null. A verified empty positions list is 0.
    errors = []
    equity = unrealized = baseline = None
    try:
        baseline = _finite(state.get('baseline_equity'))
        if baseline <= 0:
            raise ValueError('invalid baseline')
    except (TypeError, ValueError, OverflowError):
        baseline = None
        errors.append('baseline_unavailable')
    try:
        equity = _finite(broker.fetch_account().payload.get('equity'))
    except Exception:
        errors.append('account_unavailable')
    try:
        positions = broker.fetch_positions().payload
        if not isinstance(positions, list):
            raise ValueError('positions unavailable')
        unrealized = math.fsum(_finite(p['unrealized_pl']) for p in positions)
        if not math.isfinite(unrealized):
            raise ValueError('nonfinite total')
    except Exception:
        unrealized = None
        errors.append('positions_unavailable')
    gains = math.fsum(x for x in pnl if x > 0)
    losses = -math.fsum(x for x in pnl if x < 0)
    # Historical correction is descriptive, not a clean cohort for PF/WR gates.
    out = dict(schema='performance-summary-lineage-v1-20261105',
        generated_at=datetime.now(timezone.utc).isoformat(),
        status='partial' if errors else 'descriptive_complete', errors=errors,
        measurement_provenance=provenance, performance_qualified=False, promotion_ready=False,
        scope='descriptive_active_ledger_not_performance_qualification',
        baseline_equity=baseline, account_equity=equity,
        realized_pnl=realized, unrealized_pnl=unrealized,
        total_pnl=realized + unrealized if unrealized is not None else None,
        pnl_vs_baseline=equity - baseline if equity is not None and baseline is not None else None,
        closed_trades=len(closed), open_trades=sum(t['status']=='open' for t in state['trades']),
        winning_trades=sum(x>0 for x in pnl), losing_trades=sum(x<0 for x in pnl),
        win_rate=None, profit_factor=None, metric_status='not_valid_for_promotion',
        descriptive_only=dict(win_rate=sum(x>0 for x in pnl)/len(pnl) if pnl else None,
            profit_factor=gains/losses if losses else None, gross_win=gains, gross_loss=losses),
        consistency_check=dict(realized_matches_tracker=True),
        semantics=dict(realized_pnl='active closed ledger PnL, not whole-account return',
            unrealized_pnl='verified broker positions only; null on unavailable',
            account_equity='external observation; not atomic with broker positions',
            baseline_equity='explicit tracking baseline only; no assumed principal'))
    data = json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
    target = root/'data/analysis/performance_summary.json'
    if any(p.is_symlink() for p in (target, *target.parents)):
        raise ValueError('symlinked export path')
    # Do not hold the writer lock across network I/O. Refuse a stale export if a
    # cooperating writer moved the input epoch during external observation.
    with ledger_transaction(root, recover=False):
        _, current = read_analysis_snapshot(state_path)
        if current != provenance:
            raise ValueError('ledger changed during export')
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=target.parent, prefix=target.name+'.')
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write(data); stream.flush(); os.fsync(stream.fileno())
            os.replace(name, target)
            directory = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    return out


def main() -> int:
    # Validate local inputs before even constructing an external client.
    try:
        read_analysis_snapshot(PROJECT_ROOT/'data/tracking/pnl_state.json')
        from stock_swing.cli.paper_demo import _load_env
        _load_env(PROJECT_ROOT/'.env')
        broker = BrokerClient(api_key=os.environ['BROKER_API_KEY'],
            api_secret=os.environ['BROKER_API_SECRET'], paper_mode=True)
        report = export(PROJECT_ROOT, broker)
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
        return 0 if report['status']=='descriptive_complete' else 1
    except Exception as exc:
        print(json.dumps(dict(status='unavailable', reason=type(exc).__name__,
            performance_qualified=False, promotion_ready=False)))
        return 2


if __name__ == '__main__':
    sys.exit(main())
