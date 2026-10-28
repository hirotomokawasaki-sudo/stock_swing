"""Read-only review metrics. Run from repository root with venv/bin/python.
No fetch, logger execution, orders, state/config writes, or credentials.
Outputs aggregates and source hashes only; inputs may advance after the review.
"""
import collections
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'src'))
from stock_swing.risk.correlation_cluster import is_buy_blocked_by_cluster_cap


def cohort(rows):
    selections = [tuple(sorted(r['top_sectors'])) for r in rows]
    return {
        'days': len(rows),
        'sector_days': dict(collections.Counter(s for r in rows for s in r['top_sectors'])),
        'combinations': dict(collections.Counter('+'.join(s) for s in selections)),
        'transitions': max(len(rows) - 1, 0),
        'selection_flips': sum(a != b for a, b in zip(selections, selections[1:])),
        'ftxl_candidate_days': sum('FTXL' in r['candidate_symbols'] for r in rows),
        'chpx_candidate_days': sum('CHPX' in r['candidate_symbols'] for r in rows),
    }


def series(name):
    path = ROOT / 'data' / f'{name}_shadow_log.jsonl'
    parsed, invalid = [], 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError:
            invalid += 1
    by_date = {r['date']: r for r in parsed}
    dates = sorted(by_date)
    rows = [by_date[d] for d in dates]
    d, end = dt.date.fromisoformat(dates[0]), dt.date.fromisoformat(dates[-1])
    expected = []
    while d <= end:
        if d.weekday() < 5:
            expected.append(d.isoformat())
        d += dt.timedelta(days=1)
    return {
        'records': len(parsed), 'first_date': dates[0], 'last_date': dates[-1],
        'last_logged_at': rows[-1]['logged_at'], 'invalid_json': invalid,
        'error_records': sum(bool(r.get('error')) or r.get('mode') != 'shadow' for r in parsed),
        'duplicate_dates': {k: v for k, v in collections.Counter(r['date'] for r in parsed).items() if v > 1},
        'missing_weekdays': sorted(set(expected) - set(dates)),
        'rebalance_due': [{k: r[k] for k in ['date', 'prior_state_rebalance_count', 'diff_enter', 'diff_exit']} for r in parsed if r.get('rebalance_due')],
        'all': cohort(rows),
        'through_2026_10_02': cohort([r for r in rows if r['date'] <= '2026-10-02']),
        'after_2026_10_02': cohort([r for r in rows if r['date'] > '2026-10-02']),
        'headline_configs': [list(v) for v in sorted({(r['top_n'], r['lookback_days'], r['hold_days'], r.get('min_members') or 0) for r in rows})],
    }


def main():
    state = json.loads((ROOT / 'data/tracking/pnl_state.json').read_text())
    registry = yaml.safe_load((ROOT / 'config/reference/symbol_registry.yaml').read_text())['symbols']
    opens = [t for t in state['trades'] if t.get('status') == 'open']
    semis = [t for t in opens if registry.get(t['symbol'], {}).get('is_semiconductor_related')]
    snap = state['daily_snapshots'][-1]
    closed = [t for t in state['trades'] if t.get('status') == 'closed' and (t.get('exit_time') or '')[:10] >= '2026-08-14' and isinstance(t.get('pnl'), (int, float))]
    gp = sum(t['pnl'] for t in closed if t['pnl'] > 0)
    gl = -sum(t['pnl'] for t in closed if t['pnl'] < 0)
    notional = sum(t['qty'] * t['entry_price'] for t in semis)
    inputs = [
        'data/sector_rotation_new_headline_shadow_log.jsonl', 'data/sector_rotation_shadow_log.jsonl',
        'data/sector_rotation_new_headline_shadow_state.json', 'data/sector_rotation_shadow_state.json',
        'data/tracking/pnl_state.json', 'data/analysis/broker_tracker_reconciliation.md',
        'config/reference/symbol_registry.yaml', 'config/strategy/portfolio_allocation.yaml',
        'config/runtime/current_mode.yaml', 'src/stock_swing/risk/correlation_cluster.py',
        'src/stock_swing/cli/paper_demo.py', 'src/stock_swing/strategy_engine/sector_rotation_strategy.py',
        'src/stock_swing/strategy_engine/sector_rotation_state.py', 'scripts/log_sector_rotation_shadow.py',
        'scripts/check_go_no_go.py', 'docs/review_criteria_20260908.md',
    ]
    out = {
        'review_date_jst': '2026-10-21',
        'source_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'new_headline': series('sector_rotation_new_headline'), 'legacy': series('sector_rotation'),
        'new_shadow_state': json.loads((ROOT / 'data/sector_rotation_new_headline_shadow_state.json').read_text()),
        'portfolio': {'tracker_last_updated': state['last_updated'], 'open_lots': len(opens),
            'semiconductor_open_lots': len(semis), 'semiconductor_symbols': sorted({t['symbol'] for t in semis}),
            'entry_notional_proxy': round(notional, 2), 'latest_snapshot_date': snap['date'],
            'snapshot_equity': snap['equity'], 'entry_notional_equity_ratio': notional / snap['equity'],
            'unregistered_open_symbols': sorted({t['symbol'] for t in opens} - set(registry))},
        'economic_viability': {'cohort_start': '2026-08-14', 'n': len(closed),
            'gross_profit': round(gp, 2), 'gross_loss': round(gl, 2), 'pf': gp / gl,
            'expectancy': sum(t['pnl'] for t in closed) / len(closed),
            'pass': len(closed) >= 30 and gp / gl > 1 and sum(t['pnl'] for t in closed) > 0},
        'cluster_probe': {'existing_equity': 100000, 'existing_ARM_market_value': 29000,
            'ARM_buy_blocked': is_buy_blocked_by_cluster_cap('ARM', [{'symbol': 'ARM', 'market_value': 29000}], 100000)[0],
            'CRDO_buy_blocked': is_buy_blocked_by_cluster_cap('CRDO', [{'symbol': 'FTXL', 'market_value': 41000}], 100000)[0],
            'note': 'ARM at 29% is allowed without examining proposed size; CRDO is registry-semiconductor but absent from cluster membership. No proposed-order notional argument exists.'},
        'sha256': {s: hashlib.sha256((ROOT / s).read_bytes()).hexdigest() for s in inputs},
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
