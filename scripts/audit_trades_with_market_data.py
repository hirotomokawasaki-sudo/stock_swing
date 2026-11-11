#!/usr/bin/env python3
"""Audit PnL tracker trades against market prices and broker position truth.

This script checks two failure modes:
1. Historical price anomalies using Yahoo Finance daily bars
2. Tracker integrity anomalies by comparing tracker open positions with broker positions

Usage:
    python scripts/audit_trades_with_market_data.py [--anomaly-threshold 0.30]

Exit codes:
    0: Success, no anomalies detected
    1: Error or anomalies detected
    2: Input unavailable or incomplete audit coverage
"""

import argparse
import base64
from copy import deepcopy
import json
import math
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stock_swing.sources.broker_client import BrokerClient
from stock_swing.tracking.compatibility import read_analysis_snapshot
from stock_swing.tracking.ledger_transaction import LedgerConflict, digest, json_revision

# Relative price-delta threshold for tracker/broker avg-cost mismatch detection.
# Matches scripts/build_broker_tracker_reconciliation.py's WARN threshold so the
# two scripts agree on what counts as a real discrepancy vs. weighted-avg
# cost-basis rounding noise (see 2026-08-15 fix note below at point of use).
PRICE_DIFF_THRESHOLD_PCT = 0.05


def fetch_yahoo_finance_bars(symbol: str, start_date: str, end_date: str) -> dict:
    """Fetch historical bars from Yahoo Finance."""
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1mo'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            result = data.get('chart', {}).get('result', [{}])[0]
            timestamps = result.get('timestamp', [])
            quotes = result.get('indicators', {}).get('quote', [{}])[0]

            bars = {}
            for i, ts in enumerate(timestamps):
                date = datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
                close = quotes.get('close', [])[i]
                high = quotes.get('high', [])[i]
                low = quotes.get('low', [])[i]

                if close and high and low:
                    bars[date] = (float(low), float(high), float(close))

            return bars
    except Exception as e:
        print(f"WARN: Could not fetch Yahoo Finance data for {symbol}: {e}", file=sys.stderr)
        return {}


def load_env(env_file: Path) -> None:
    """Load environment variables from .env file if present."""
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip())


def normalize_timestamp(value) -> str:
    """Return a comparable timestamp string for optional datetime fields."""
    return value if isinstance(value, str) else ""


def normalize_position_price(
    symbol: str,
    price: float,
    market_cache: dict[str, dict[str, tuple[float, float, float]]],
) -> float:
    """Correct obvious 10x/100x broker position price anomalies using recent market data."""
    if price <= 0:
        return price

    bars = market_cache.get(symbol)
    if bars is None:
        bars = fetch_yahoo_finance_bars(symbol, "", "")
        market_cache[symbol] = bars
    if not bars:
        return price

    latest_day = max(bars)
    recent = list(sorted(bars.items())[-5:])
    lows = [bar[0] for _, bar in recent]
    highs = [bar[1] for _, bar in recent]
    closes = [bar[2] for _, bar in recent]
    recent_low = min(lows)
    recent_high = max(highs)
    latest_close = bars[latest_day][2]

    if recent_low <= price <= recent_high:
        return round(price, 4)

    for factor in (10, 100):
        candidate = price / factor
        if (recent_low * 0.9) <= candidate <= (recent_high * 1.1):
            return round(candidate, 4)
        if latest_close > 0 and abs(candidate - latest_close) / latest_close <= 0.20:
            return round(candidate, 4)

    return round(price, 4)


def _positive_number(value):
    if isinstance(value, bool):
        raise ValueError('invalid position number')
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError('invalid position number')
    return number


def _whole_qty(value):
    number = _positive_number(value)
    if not number.is_integer():
        raise ValueError('unsupported fractional position')
    return int(number)


def build_tracker_open_positions(trades: list[dict]) -> dict[str, dict]:
    """Aggregate tracker open positions by symbol."""
    positions: dict[str, dict] = {}
    for trade in trades:
        if trade.get("status") != "open":
            continue
        symbol = trade.get('symbol')
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError('missing tracker symbol')
        symbol = symbol.upper()
        qty = _whole_qty(trade.get('qty'))
        entry_price = _positive_number(trade.get('entry_price'))
        row = positions.setdefault(symbol, {
            "symbol": symbol,
            "qty": 0,
            "entry_notional": 0.0,
            "trade_count": 0,
        })
        row["qty"] += qty
        row['entry_notional'] = _positive_number(row['entry_notional'] + entry_price * qty)
        row["trade_count"] += 1

    for row in positions.values():
        qty = row["qty"]
        row["avg_entry_price"] = round((row["entry_notional"] / qty), 4) if qty else 0.0
    return positions


def analyze_tracker_integrity(trades: list[dict], broker_positions: list[dict]) -> dict:
    """Compare tracker open positions with broker positions."""
    if not isinstance(broker_positions, list) or any(not isinstance(row, dict) for row in broker_positions):
        raise ValueError('invalid broker positions')
    tracker_positions = build_tracker_open_positions(trades)
    broker_map = {}
    market_cache: dict[str, dict[str, tuple[float, float, float]]] = {}
    for pos in broker_positions:
        symbol = pos.get('symbol')
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError('missing broker symbol')
        symbol = symbol.upper()
        if symbol in broker_map:
            raise ValueError('duplicate broker position')
        raw_avg_entry = _positive_number(pos.get('avg_entry_price'))
        broker_map[symbol] = {
            "symbol": symbol,
            "qty": _whole_qty(pos.get('qty')),
            "avg_entry_price": normalize_position_price(symbol, raw_avg_entry, market_cache),
            "raw_avg_entry_price": raw_avg_entry,
        }

    tracker_symbols = set(tracker_positions.keys())
    broker_symbols = set(broker_map.keys())
    mismatches = []
    multi_lot_symbols = []
    consistent = []

    for symbol in sorted(tracker_symbols):
        tracker_pos = tracker_positions[symbol]
        if tracker_pos.get("trade_count", 0) > 1:
            multi_lot_symbols.append({
                "symbol": symbol,
                "trade_count": tracker_pos["trade_count"],
                "tracker_qty": tracker_pos["qty"],
            })

    for symbol in sorted(tracker_symbols & broker_symbols):
        tracker_pos = tracker_positions[symbol]
        broker_pos = broker_map[symbol]
        qty_match = tracker_pos["qty"] == broker_pos["qty"]
        price_diff = abs(tracker_pos["avg_entry_price"] - broker_pos["avg_entry_price"])
        # 2026-08-15 fix: was an absolute $0.01 threshold, which flags essentially
        # every multi-lot position as a "mismatch" once share price is above ~$10
        # (weighted-avg cost-basis rounding routinely produces sub-$1 deltas on
        # $100-$1800 stocks). This caused stock_swing_daily_audit to report ~10-20
        # false-positive "tracker integrity" issues every single day for weeks
        # (see docs/daily_logs/2026-08-*.md), even though the dedicated
        # build_broker_tracker_reconciliation.py script (which already uses a
        # relative % threshold) consistently confirmed 0 real mismatches on the
        # same data. Switched to a relative threshold to match that script and
        # eliminate the noise; real anomalies (e.g. missed corporate-action
        # splits, which move price by 100s of %) are still caught easily.
        price_diff_pct = (
            price_diff / broker_pos["avg_entry_price"]
            if broker_pos["avg_entry_price"] > 0
            else (0.0 if price_diff == 0 else float("inf"))
        )
        if not qty_match or price_diff_pct > PRICE_DIFF_THRESHOLD_PCT:
            mismatches.append({
                "symbol": symbol,
                "tracker_qty": tracker_pos["qty"],
                "broker_qty": broker_pos["qty"],
                "tracker_entry": tracker_pos["avg_entry_price"],
                "broker_entry": round(broker_pos["avg_entry_price"], 4),
                "broker_raw_entry": round(broker_pos["raw_avg_entry_price"], 4),
                "tracker_trade_count": tracker_pos["trade_count"],
            })
        else:
            consistent.append(symbol)

    return {
        "tracker_positions": tracker_positions,
        "broker_positions": broker_map,
        "multi_lot_symbols": multi_lot_symbols,
        "mismatches": mismatches,
        "tracker_only": sorted(tracker_symbols - broker_symbols),
        "broker_only": sorted(broker_symbols - tracker_symbols),
        "consistent": consistent,
    }


def load_broker_positions(project_root: Path) -> list[dict]:
    """Load current broker positions if credentials are available."""
    load_env(project_root / ".env")
    api_key = os.environ.get("BROKER_API_KEY")
    api_secret = os.environ.get("BROKER_API_SECRET")
    if not api_key or not api_secret:
        raise RuntimeError("BROKER_API_KEY / BROKER_API_SECRET are not set")

    broker = BrokerClient(api_key=api_key, api_secret=api_secret, paper_mode=True)
    resp = broker.fetch_positions()
    return resp.payload if hasattr(resp, "payload") else resp



def check_ledger_invariants(state: dict) -> dict:
    """R0-v2-B: Check closed-trade ledger invariants.

    Returns a dict with counts and a boolean 'passed' flag.
    Called by audit_trades_with_market_data.py every day so that
    ledger degradation is detected the morning after it occurs.
    """
    from datetime import datetime as _dt

    trades = state.get("trades", [])
    closed = [t for t in trades if t.get("status") == "closed"]

    # Invariant 1: closed ∩ quarantine = ∅
    # Use (broker_order_id, exit_broker_order_id) pairs as the canonical key.
    # Root cause of previous false-positives (2026-07-28): trade_id like
    # 'broker_match_NNNN_SYMBOL' is a sequential index re-assigned on every rebuild;
    # after a rebuild with new fills the same index number can point to a completely
    # different trade.  broker_order_id is the immutable broker-assigned UUID and is
    # the correct identity for overlap detection.
    quar_pairs = {
        (
            t.get("broker_order_id") or t.get("entry_broker_order_id") or "",
            t.get("exit_broker_order_id") or "",
        )
        for t in state.get("quarantined_trades", [])
    }
    overlap = [
        t for t in closed
        if (
            t.get("broker_order_id") or "",
            t.get("exit_broker_order_id") or "",
        ) in quar_pairs
    ]

    # Invariant 2: entry_time ≤ exit_time for all closed
    reversed_trades = []
    for t in closed:
        et, xt = t.get("entry_time", ""), t.get("exit_time", "")
        if not et or not xt:
            raise ValueError('closed trade timestamp unavailable')
        try:
            e = _dt.fromisoformat(str(et).replace("Z", "+00:00"))
            x = _dt.fromisoformat(str(xt).replace("Z", "+00:00"))
            if e > x:
                reversed_trades.append(t)
        except (ValueError, TypeError) as exc:
            raise ValueError('invalid closed trade timestamp') from exc

    # Invariant 3: holding_days not None
    hd_missing = [t for t in closed if t.get("holding_days") is None]

    # Invariant 4: PnL consistency
    values = [t.get('pnl') for t in closed]
    cum = state.get('cumulative_realized_pnl', 0 if not closed else None)
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
           for v in [*values, cum]):
        raise ValueError('invalid closed/cumulative PnL')
    closed_sum = math.fsum(values)
    pnl_diff = abs(closed_sum - cum)
    if not math.isfinite(closed_sum) or not math.isfinite(pnl_diff):
        raise ValueError('nonfinite PnL aggregate')

    # Invariant 5: asset_class must be set (not None / 'unknown' / missing)
    # Root cause: rebuild_pnl_state_from_broker.py used to wipe asset_class on every
    # rebuild because --preserve-attribution only saved exit_reason + quarantined_trades.
    # Detected 2026-07-28: 203 closed trades reverted to None after 07-25 SKYY rebuild.
    VALID_ASSET_CLASSES = {"stock", "etf"}
    ac_unknown = [
        t for t in closed
        if (t.get("asset_class") or "").lower() not in VALID_ASSET_CLASSES
    ]

    passed = (
        len(overlap) == 0
        and len(reversed_trades) == 0
        and pnl_diff <= 1.0
        and len(ac_unknown) == 0
        # hd_missing is a warning, not a hard fail (may be pre-fix data)
    )

    return {
        "overlap_count": len(overlap),
        "reversed_count": len(reversed_trades),
        "hd_missing_count": len(hd_missing),
        "ac_unknown_count": len(ac_unknown),
        "pnl_diff": round(pnl_diff, 2),
        "closed_count": len(closed),
        "quarantined_count": len(state.get("quarantined_trades", [])),
        "passed": passed,
    }


def recover_archived_asset_classes(state: dict) -> tuple[dict, dict]:
    """Recover recorded classification in an audit view, never rewrite history.

    Input must come from read_analysis_snapshot (validated state/event pair).
    Only exact replacement rows and their exact retired BUY identities qualify.
    This is archived metadata, not proof of trade-time classification or a new
    strategy attribution. Current registry/symbol defaults are never consulted.
    """
    view = deepcopy(state)
    missing = [r for r in view['trades'] if r.get('status') == 'closed'
               and (r.get('asset_class') or '').lower() not in {'stock', 'etf'}]
    receipt = dict(schema_version=1, scope='audit_view_recorded_metadata_not_trade_time_qualification',
                   raw_missing=len(missing), recovered=0, unresolved=len(missing), rows=[],
                   raw_ledger_modified=False, economic_fields_changed=False, promotion_ready=False)
    if not missing or not state.get('history_migrations'):
        return view, receipt
    try:
        history = state['history_migrations']
        if not isinstance(history, list) or len(history) != 1:
            raise ValueError('unsupported history archive')
        h = history[0]
        intent = h['intent']
        raw = base64.b64decode(h['original_state_b64'], validate=True)
        if (h['migration_id'] != json_revision(intent)
                or h['before_sha256'] != intent['before_sha256']
                or digest(raw) != h['before_sha256']['pnl_state.json']
                or state['measurement_lineage']['ledger_revision'] != h['migration_id']):
            raise ValueError('unbound history archive')
        archive = json.loads(raw)
        retired = []
        for ref in intent['retire_records']:
            c, i = ref['collection'], ref['row_index']
            if c not in {'trades', 'quarantined_trades'} or type(i) is not int or i < 0:
                raise ValueError('invalid retired row reference')
            original = archive[c][i]
            if original != ref['before']:
                raise ValueError('retired metadata differs from archive')
            retired.append((c, i, original))

        def identity(row):
            stamp = datetime.fromisoformat(row['entry_time'].replace('Z', '+00:00'))
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError('ambiguous BUY timestamp')
            if (not row.get('broker_order_id') or not row.get('symbol')
                    or row.get('side') != 'buy'):
                raise ValueError('incomplete BUY identity')
            return row['broker_order_id'], row['symbol'], stamp.astimezone(timezone.utc)

        receipt.update(ledger_revision=h['migration_id'], archive_sha256=digest(raw))
        for row in missing:
            # Invalid explicit values must not be laundered into a valid class.
            if row.get('asset_class') not in (None, '', 'unknown'):
                continue
            if sum(row == r for r in intent['replacement_rows']) != 1:
                continue
            if sum(row == r for r in state['trades']) != 1:
                raise ValueError('duplicate replacement identity')
            key = identity(row)
            matches = [(c, i, old) for c, i, old in retired if identity(old) == key]
            classes = {old.get('asset_class') for _, _, old in matches}
            if not matches or len(classes) != 1 or not classes <= {'stock', 'etf'}:
                continue  # Missing or conflicting recorded evidence stays unknown.
            ac = classes.pop()
            receipt['rows'].append(dict(trade_id=row['trade_id'],
                execution_leg_id=row.get('execution_leg_id'), before_row_sha256=json_revision(row),
                broker_order_id=row['broker_order_id'], symbol=row['symbol'],
                entry_time=row['entry_time'], asset_class=ac,
                archived_sources=[dict(collection=c, row_index=i, row_sha256=json_revision(old))
                                  for c, i, old in matches]))
            row['asset_class'] = ac
        receipt['recovered'] = len(receipt['rows'])
        receipt['unresolved'] -= receipt['recovered']
    except (ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValueError('classification archive unavailable: ' + str(exc)) from exc
    return view, receipt


def audit_ledger_invariants(state: dict) -> dict:
    """Report immutable raw gaps separately from evidenced audit-view recovery."""
    raw = check_ledger_invariants(state)
    view, evidence = recover_archived_asset_classes(state)
    inv = check_ledger_invariants(view)
    print('RAW_LEDGER_INVARIANTS_JSON=' + json.dumps(raw, sort_keys=True))
    print('CLASSIFICATION_RECOVERY_JSON=' + json.dumps(evidence, sort_keys=True))
    print('AUDIT_VIEW_INVARIANTS_JSON=' + json.dumps(inv, sort_keys=True))
    print(f"Closed trades:    {inv['closed_count']}")
    print(f"Quarantined:      {inv['quarantined_count']}")
    print(f"Raw asset-class gaps: {evidence['raw_missing']}; archived recovery: "
          f"{evidence['recovered']}; unresolved: {evidence['unresolved']}")
    if evidence['recovered']:
        print('WARNING: raw historical rows remain immutable; only the audit view recovers recorded asset_class.')
    issues = []
    for field, label in [('overlap_count', 'closed/quarantine overlap'),
                         ('reversed_count', 'entry_time > exit_time'),
                         ('ac_unknown_count', 'unknown asset class')]:
        if inv[field]:
            issues.append(f"INVARIANT FAIL: {label} = {inv[field]} trades")
    if inv['pnl_diff'] > 1.0:
        issues.append(f"INVARIANT FAIL: PnL inconsistency = ${inv['pnl_diff']:,.2f}")
    if inv['hd_missing_count']:
        issues.append(f"WARNING: holding_days = None in {inv['hd_missing_count']} closed trades")
    for issue in issues:
        print(issue)
    if inv['passed']:
        print('Ledger audit view: no unresolved invariant violations (not performance qualification).')
    else:
        print('See docs/runbooks/r0v2b_ledger_repair_runbook.md; do not use legacy backfill on corrected history.')
    return inv


def main():
    parser = argparse.ArgumentParser(description="Audit trades against market prices")
    parser.add_argument("--anomaly-threshold", type=float, default=0.30,
                       help="Price deviation threshold for anomaly detection (default: 0.30 = 30%%)")
    parser.add_argument("--symbols", nargs="*", help="Only audit specific symbols (default: all)")
    parser.add_argument("--recent-days", type=int, help="Only audit trades from recent N days")
    parser.add_argument('--ledger-only', action='store_true',
                        help='Read-only ledger metadata audit; no broker or market calls; not a full daily audit')
    args = parser.parse_args()
    if not math.isfinite(args.anomaly_threshold) or args.anomaly_threshold < 0:
        parser.error('anomaly threshold must be finite and nonnegative')

    project_root = PROJECT_ROOT
    state_file = project_root / "data" / "tracking" / "pnl_state.json"

    if not state_file.exists():
        print(f"ERROR: {state_file} not found", file=sys.stderr)
        return 1

    try:
        state, provenance = read_analysis_snapshot(state_file)
    except (OSError, ValueError, LedgerConflict) as exc:
        print(f"UNAVAILABLE: coherent ledger input: {exc}", file=sys.stderr)
        return 2
    print('MEASUREMENT_PROVENANCE_JSON=' + json.dumps(provenance, sort_keys=True))
    print('INFO: descriptive integrity/price audit, not qualified strategy performance', file=sys.stderr)
    if args.ledger_only:
        print('AUDIT_SCOPE_JSON=' + json.dumps(dict(scope='ledger_metadata_only',
              broker_check='not_checked', price_checks='not_checked', promotion_ready=False)))
        try:
            return 0 if audit_ledger_invariants(state)['passed'] else 1
        except (ValueError, TypeError, OverflowError) as exc:
            print(f'UNAVAILABLE: ledger invariants: {exc}', file=sys.stderr)
            return 2
    all_trades = state.get("trades", [])

    if args.symbols:
        all_trades = [t for t in all_trades if t.get("symbol") in args.symbols]

    trades = all_trades
    if args.recent_days:
        cutoff = (datetime.now() - timedelta(days=args.recent_days)).isoformat()
        trades = [
            t for t in all_trades
            if t.get("status") != "closed" or normalize_timestamp(t.get("entry_time")) > cutoff
        ]

    closed_trades = [t for t in trades if t.get("status") == "closed"]

    print(f"INFO: Auditing {len(closed_trades)} closed trades (threshold={args.anomaly_threshold:.0%})", file=sys.stderr)
    print()

    trades_by_symbol = {}
    for t in closed_trades:
        symbol = t.get("symbol")
        if symbol:
            trades_by_symbol.setdefault(symbol, []).append(t)

    total_anomalies = 0
    entry_anomalies = 0
    exit_anomalies = 0
    both_anomalies = 0
    audited_count = 0
    unavailable_count = len([t for t in closed_trades if not t.get('symbol')])

    for symbol, symbol_trades in sorted(trades_by_symbol.items()):
        print(f"\n{'='*100}")
        print(f"SYMBOL: {symbol} ({len(symbol_trades)} trades)")
        print('='*100)

        all_dates = set()
        for t in symbol_trades:
            entry_date = normalize_timestamp(t.get("entry_time"))[:10]
            exit_date = normalize_timestamp(t.get("exit_time"))[:10]
            if entry_date:
                all_dates.add(entry_date)
            if exit_date:
                all_dates.add(exit_date)

        if not all_dates:
            unavailable_count += len(symbol_trades)
            continue

        market_bars = fetch_yahoo_finance_bars(symbol, min(all_dates), max(all_dates))

        if not market_bars:
            print(f"WARN: No market data available for {symbol}, skipping", file=sys.stderr)
            unavailable_count += len(symbol_trades)
            continue

        for t in sorted(
            symbol_trades,
            key=lambda x: (
                normalize_timestamp(x.get("entry_time")),
                normalize_timestamp(x.get("exit_time")),
                x.get("trade_id", ""),
            ),
        ):
            trade_id = t.get("trade_id", "unknown")
            entry_time = normalize_timestamp(t.get("entry_time"))[:19]
            exit_time = normalize_timestamp(t.get("exit_time"))[:19]
            entry_date = entry_time[:10]
            exit_date = exit_time[:10]
            entry_price = t.get("entry_price", 0)
            exit_price = t.get("exit_price", 0)
            ret = t.get("return_pct", 0)
            pnl = t.get("pnl", 0)

            if not entry_date or not exit_date:
                print(f"SKIP: {trade_id} (missing entry_time or exit_time)")
                unavailable_count += 1
                continue

            entry_market = market_bars.get(entry_date)
            exit_market = market_bars.get(exit_date)

            if not entry_market or not exit_market:
                print(f"SKIP: {trade_id} (missing market data for {entry_date} or {exit_date})")
                unavailable_count += 1
                continue

            try:
                values = [entry_price, exit_price, *entry_market, *exit_market]
                if (len(entry_market) != 3 or len(exit_market) != 3
                        or any(isinstance(v, bool) or not isinstance(v, (int, float))
                               or not math.isfinite(v) or v <= 0 for v in values)
                        or entry_market[0] > entry_market[1]
                        or exit_market[0] > exit_market[1]):
                    raise ValueError('invalid prices')
            except (ValueError, TypeError):
                print(f'UNAVAILABLE: invalid trade/market prices for {trade_id}', file=sys.stderr)
                unavailable_count += 1
                continue
            audited_count += 1

            entry_low, entry_high, entry_close = entry_market
            exit_low, exit_high, exit_close = exit_market

            entry_in_range = entry_low <= entry_price <= entry_high
            exit_in_range = exit_low <= exit_price <= exit_high

            entry_dev = 0
            exit_dev = 0

            if not entry_in_range:
                if entry_price < entry_low:
                    entry_dev = (entry_low - entry_price) / entry_low
                else:
                    entry_dev = (entry_price - entry_high) / entry_high

            if not exit_in_range:
                if exit_price < exit_low:
                    exit_dev = (exit_low - exit_price) / exit_low
                else:
                    exit_dev = (exit_price - exit_high) / exit_high

            is_anomaly = (not entry_in_range and entry_dev > args.anomaly_threshold) or \
                        (not exit_in_range and exit_dev > args.anomaly_threshold)

            if is_anomaly:
                total_anomalies += 1

                if not entry_in_range and not exit_in_range:
                    status = "❌ BOTH ANOMALOUS"
                    both_anomalies += 1
                elif not entry_in_range:
                    status = f"⚠️  ENTRY ANOMALOUS ({entry_dev:+.1%})"
                    entry_anomalies += 1
                else:
                    status = f"⚠️  EXIT ANOMALOUS ({exit_dev:+.1%})"
                    exit_anomalies += 1

                print(f"\n{status}")
                print(f"  Trade ID: {trade_id}")
                print(f"  Entry: {entry_date} ${entry_price:.2f} (market ${entry_low:.2f}-${entry_high:.2f})")
                print(f"  Exit:  {exit_date} ${exit_price:.2f} (market ${exit_low:.2f}-${exit_high:.2f})")
                print(f"  Return: {ret:+.2%}  P&L: ${pnl:,.2f}")

    print("\n" + "="*100)
    print("\nAUDIT SUMMARY")
    print("="*100)
    print(f"Total closed trades selected: {len(closed_trades)}")
    print(f"Total closed trades audited: {audited_count}")
    print(f"Unavailable price checks:    {unavailable_count}")
    print(f"Total anomalies detected:    {total_anomalies}")
    print(f"  Entry price anomalies:     {entry_anomalies}")
    print(f"  Exit price anomalies:      {exit_anomalies}")
    print(f"  Both anomalous:            {both_anomalies}")

    integrity_issue_count = 0
    broker_check_failed = False
    print("\n" + "="*100)
    print("TRACKER INTEGRITY SUMMARY")
    print("="*100)
    try:
        broker_positions = load_broker_positions(project_root)
        integrity = analyze_tracker_integrity(all_trades, broker_positions)
        multi_lot_symbols = integrity["multi_lot_symbols"]
        mismatches = integrity["mismatches"]
        tracker_only = integrity["tracker_only"]
        broker_only = integrity["broker_only"]
        integrity_issue_count = len(mismatches) + len(tracker_only) + len(broker_only)

        print(f"Broker positions: {len(broker_positions)}")
        print(f"Tracker open symbols: {len(integrity['tracker_positions'])}")
        print(f"Integrity issue count: {integrity_issue_count}")

        if multi_lot_symbols:
            print("\nℹ️  MULTI-LOT TRACKER OPEN POSITIONS (aggregate matched broker)")
            for row in multi_lot_symbols:
                print(f"  {row['symbol']}: {row['trade_count']} tracker lots / qty={row['tracker_qty']}")

        if mismatches:
            print("\n⚠️  BROKER/TRACKER MISMATCHES")
            for row in mismatches:
                print(
                    f"  {row['symbol']}: tracker qty={row['tracker_qty']} @ ${row['tracker_entry']:.2f} "
                    f"vs broker qty={row['broker_qty']} @ ${row['broker_entry']:.2f} "
                    f"(lots={row['tracker_trade_count']})"
                )

        if tracker_only:
            print("\n⚠️  TRACKER-ONLY OPEN SYMBOLS")
            print("  " + ", ".join(tracker_only))

        if broker_only:
            print("\n⚠️  BROKER-ONLY OPEN SYMBOLS")
            print("  " + ", ".join(broker_only))

        if integrity_issue_count == 0:
            print("\n✅ Tracker open positions match broker positions.")
    except Exception as e:
        broker_check_failed = True
        print(f"WARN: Could not run broker/tracker integrity check: {e}", file=sys.stderr)

    has_prior_issues = (total_anomalies > 0 or integrity_issue_count > 0 or broker_check_failed)

    # ── R0-v2-B: Ledger invariant check (always runs, even when prior issues exist) ───
    print()
    print("=" * 100)
    print("LEDGER INVARIANT CHECK")
    print("=" * 100)
    try:
        inv = audit_ledger_invariants(state)
    except (ValueError, TypeError, OverflowError) as exc:
        print(f'UNAVAILABLE: ledger invariants: {exc}', file=sys.stderr)
        return 2

    inv_failed = not inv["passed"]

    # ── Final summary ─────────────────────────────────────────────────
    if unavailable_count:
        print('UNAVAILABLE: incomplete price coverage; this audit is not a clean pass', file=sys.stderr)
        return 2
    any_failure = has_prior_issues or inv_failed
    if has_prior_issues:
        print("\n⚠️  ACTION REQUIRED (price/tracker issues):")
        if total_anomalies > 0:
            print(f"   Review {total_anomalies} anomalous trade(s) above")
        if integrity_issue_count > 0:
            print(f"   Review {integrity_issue_count} tracker integrity issue(s) above")
        if broker_check_failed:
            print("   Fix broker integrity check environment/credentials and rerun audit")
        print("\nNext steps:")
        print("  1. Backup pnl_state.json")
        if total_anomalies > 0:
            print("  2. Investigate price anomalies against market data")
        elif integrity_issue_count > 0:
            print("  2. Review a versioned repair proposal; do not run an unreviewed rebuild")
            print("  4. Restart console to clear cache")
        else:
            print("  2. Fix the broker check environment (virtualenv/dependencies/credentials)")
            print("  3. Rerun: python scripts/audit_trades_with_market_data.py")

    if not any_failure:
        print("\n✅ No price anomalies, tracker issues, or unresolved audit-view invariant violations detected.")
    return 1 if any_failure else 0


if __name__ == "__main__":
    sys.exit(main())
