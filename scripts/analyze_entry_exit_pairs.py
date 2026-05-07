#!/usr/bin/env python3
"""Analyze closed trades by entry strategy × exit reason.

Reads data/tracking/pnl_state.json and prints cross-tab style summaries for:
- entry_strategy × exit_reason
- entry_strategy_version × exit_reason
- entry_strategy × exit_strategy × exit_reason

By default, only BUY-origin closed trades are analyzed because T22 is about
entry-quality evaluation. Use --include-sell-entries to include SELL-origin rows.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

import sys

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))

from stock_swing.utils.strategy_versioning import normalize_strategy_id


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def hold_hours(trade: dict[str, Any]) -> float | None:
    entry_dt = parse_dt(trade.get("entry_time"))
    exit_dt = parse_dt(trade.get("exit_time"))
    if not entry_dt or not exit_dt:
        return None
    return (exit_dt - entry_dt).total_seconds() / 3600.0


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def entry_strategy(trade: dict[str, Any]) -> str:
    return str(trade.get("original_strategy_id") or trade.get("strategy_id") or "unknown")


def entry_strategy_version(trade: dict[str, Any]) -> str:
    explicit = trade.get("strategy_version_id")
    if explicit:
        return str(explicit)
    return normalize_strategy_id(entry_strategy(trade), trade.get("entry_time"))


def make_bucket() -> dict[str, Any]:
    return {
        "count": 0,
        "wins": 0,
        "losses": 0,
        "breakeven": 0,
        "total_pnl": 0.0,
        "total_return_pct": 0.0,
        "return_count": 0,
        "total_hold_hours": 0.0,
        "hold_count": 0,
        "symbols": set(),
    }


def update_bucket(bucket: dict[str, Any], trade: dict[str, Any]) -> None:
    pnl = to_float(trade.get("pnl"), 0.0)
    ret = trade.get("return_pct")
    hold = hold_hours(trade)

    bucket["count"] += 1
    bucket["total_pnl"] += pnl
    if pnl > 0:
        bucket["wins"] += 1
    elif pnl < 0:
        bucket["losses"] += 1
    else:
        bucket["breakeven"] += 1

    if ret is not None:
        bucket["total_return_pct"] += to_float(ret, 0.0)
        bucket["return_count"] += 1

    if hold is not None:
        bucket["total_hold_hours"] += hold
        bucket["hold_count"] += 1

    symbol = trade.get("symbol")
    if symbol:
        bucket["symbols"].add(str(symbol))


def avg(value: float, count: int) -> float:
    return value / count if count else 0.0


def print_table(title: str, grouped: dict[tuple[str, ...], dict[str, Any]], headers: list[str]) -> None:
    print(f"\n=== {title} ===")
    print(f"{' | '.join(headers):<70}  Count  Win%   AvgPnL    TotPnL    AvgRet%  AvgHoldH  Symbols")
    print("-" * 130)

    for key, bucket in sorted(grouped.items(), key=lambda kv: (-kv[1]["total_pnl"], -kv[1]["count"], kv[0])):
        key_text = " | ".join(str(part) for part in key)
        count = bucket["count"]
        win_rate = avg(bucket["wins"] * 100.0, count)
        avg_pnl = avg(bucket["total_pnl"], count)
        avg_ret = avg(bucket["total_return_pct"] * 100.0, bucket["return_count"])
        avg_hold = avg(bucket["total_hold_hours"], bucket["hold_count"])
        symbols = ",".join(sorted(bucket["symbols"]))
        print(
            f"{key_text:<70}  "
            f"{count:>5}  "
            f"{win_rate:>5.1f}%  "
            f"${avg_pnl:>8.2f}  "
            f"${bucket['total_pnl']:>8.2f}  "
            f"{avg_ret:>7.2f}%  "
            f"{avg_hold:>8.2f}  "
            f"{symbols}"
        )


def load_decision_index(decisions_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    index: dict[tuple[str, str], dict[str, Any]] = {}
    if not decisions_dir.exists():
        return index
    for path in decisions_dir.glob("decision_*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        symbol = str(payload.get("symbol") or "")
        prefix = str(payload.get("decision_id") or "")[:8]
        if symbol and prefix:
            index[(symbol, prefix)] = payload
    return index


def attach_decision(trade: dict[str, Any], decision_index: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any] | None:
    trade_id = str(trade.get("trade_id") or "")
    symbol = str(trade.get("symbol") or "")
    prefix = trade_id.split("-")[-1] if "-" in trade_id else ""
    return decision_index.get((symbol, prefix))


def print_stop_loss_deep_dive(closed_trades: list[dict[str, Any]], project_root: Path) -> None:
    decision_index = load_decision_index(project_root / "data" / "decisions")
    matched: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for trade in closed_trades:
        decision = attach_decision(trade, decision_index)
        if decision:
            matched.append((trade, decision))

    print("\n=== STOP_LOSS ENTRY QUALITY DEEP DIVE ===")
    print(f"Decision matches: {len(matched)}/{len(closed_trades)}")
    if not matched:
        print("No decision matches found.")
        return

    for exit_reason in ("stop_loss", "strategy_exit"):
        rows = [(t, d) for t, d in matched if str(t.get("exit_reason") or "unknown") == exit_reason]
        if not rows:
            continue
        sig = [to_float(d.get("signal_strength"), 0.0) for t, d in rows]
        conf = [to_float(d.get("confidence"), 0.0) for t, d in rows]
        pnl_values = [to_float(t.get("pnl"), 0.0) for t, d in rows]
        hold_values = [h for h in (hold_hours(t) for t, d in rows) if h is not None]
        print(
            f"- {exit_reason}: count={len(rows)}, "
            f"avg_signal={mean(sig):.3f}, avg_confidence={mean(conf):.3f}, "
            f"avg_pnl=${mean(pnl_values):.2f}, avg_hold_hours={mean(hold_values):.2f}"
        )

    stop_loss_rows = [(t, d) for t, d in matched if str(t.get("exit_reason") or "") == "stop_loss"]
    if not stop_loss_rows:
        return

    print("\nTop stop_loss symbols:")
    by_symbol: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for trade, decision in stop_loss_rows:
        by_symbol[str(trade.get("symbol") or "unknown")].append((trade, decision))

    print("Symbol   Count  AvgSig  AvgConf  AvgPnL     Win%")
    print("-" * 52)
    for symbol, rows in sorted(by_symbol.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:12]:
        sig = [to_float(d.get("signal_strength"), 0.0) for t, d in rows]
        conf = [to_float(d.get("confidence"), 0.0) for t, d in rows]
        pnl_values = [to_float(t.get("pnl"), 0.0) for t, d in rows]
        wins = sum(1 for value in pnl_values if value > 0)
        print(f"{symbol:<7} {len(rows):>5}  {mean(sig):>6.3f}  {mean(conf):>7.3f}  ${mean(pnl_values):>8.2f}  {wins/len(rows)*100:>5.1f}%")

    high_signal_losers = [
        (t, d) for t, d in stop_loss_rows
        if to_float(d.get("signal_strength"), 0.0) >= 0.85 and to_float(t.get("pnl"), 0.0) < 0
    ]
    high_signal_losers.sort(key=lambda item: (to_float(item[0].get("pnl"), 0.0), item[0].get("symbol") or ""))

    print("\nHigh-signal stop_loss losers:")
    if not high_signal_losers:
        print("None")
    else:
        print("Symbol   PnL       Ret%    Signal  Conf   HoldH  Regime     EntryStrategyVersion")
        print("-" * 102)
        for trade, decision in high_signal_losers[:15]:
            hold = hold_hours(trade) or 0.0
            regime = str((decision.get('evidence') or {}).get('market_regime') or 'unknown')
            print(
                f"{str(trade.get('symbol') or 'unknown'):<7} "
                f"${to_float(trade.get('pnl'), 0.0):>8.2f}  "
                f"{to_float(trade.get('return_pct'), 0.0)*100:>6.2f}%  "
                f"{to_float(decision.get('signal_strength'), 0.0):>6.2f}  "
                f"{to_float(decision.get('confidence'), 0.0):>5.2f}  "
                f"{hold:>5.2f}  "
                f"{regime:<9}  "
                f"{entry_strategy_version(trade)}"
            )

    print("\nStop_loss by regime:")
    by_regime: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for trade, decision in stop_loss_rows:
        regime = str((decision.get('evidence') or {}).get('market_regime') or 'unknown')
        by_regime[regime].append((trade, decision))
    print("Regime     Count  AvgSig  AvgConf  AvgPnL     Win%   AvgHoldH")
    print("-" * 64)
    for regime, rows in sorted(by_regime.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        sig = [to_float(d.get('signal_strength'), 0.0) for t, d in rows]
        conf = [to_float(d.get('confidence'), 0.0) for t, d in rows]
        pnl_values = [to_float(t.get('pnl'), 0.0) for t, d in rows]
        holds = [h for h in (hold_hours(t) for t, d in rows) if h is not None]
        wins = sum(1 for value in pnl_values if value > 0)
        print(f"{regime:<9} {len(rows):>5}  {mean(sig):>6.3f}  {mean(conf):>7.3f}  ${mean(pnl_values):>8.2f}  {wins/len(rows)*100:>5.1f}%  {mean(holds):>8.2f}")

    print("\nStop_loss by symbol × regime:")
    by_symbol_regime: dict[tuple[str, str], list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for trade, decision in stop_loss_rows:
        symbol = str(trade.get('symbol') or 'unknown')
        regime = str((decision.get('evidence') or {}).get('market_regime') or 'unknown')
        by_symbol_regime[(symbol, regime)].append((trade, decision))
    print("Symbol   Regime     Count  AvgSig  AvgConf  AvgPnL     Win%   AvgHoldH")
    print("-" * 74)
    for (symbol, regime), rows in sorted(by_symbol_regime.items(), key=lambda kv: (-len(kv[1]), kv[0][0], kv[0][1]))[:20]:
        sig = [to_float(d.get('signal_strength'), 0.0) for t, d in rows]
        conf = [to_float(d.get('confidence'), 0.0) for t, d in rows]
        pnl_values = [to_float(t.get('pnl'), 0.0) for t, d in rows]
        holds = [h for h in (hold_hours(t) for t, d in rows) if h is not None]
        wins = sum(1 for value in pnl_values if value > 0)
        print(f"{symbol:<7} {regime:<9} {len(rows):>5}  {mean(sig):>6.3f}  {mean(conf):>7.3f}  ${mean(pnl_values):>8.2f}  {wins/len(rows)*100:>5.1f}%  {mean(holds):>8.2f}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze closed trades by entry strategy × exit reason")
    parser.add_argument(
        "--pnl-path",
        type=Path,
        default=project_root / "data" / "tracking" / "pnl_state.json",
        help="Path to pnl_state.json",
    )
    parser.add_argument(
        "--limit-symbols",
        type=int,
        default=8,
        help="Max symbols to display per row (0 = unlimited)",
    )
    parser.add_argument(
        "--include-sell-entries",
        action="store_true",
        help="Include SELL-origin closed trades as well (default: BUY-only)",
    )
    parser.add_argument(
        "--deep-dive-stop-loss",
        action="store_true",
        help="Add stop_loss entry-quality deep dive using matched decision files.",
    )
    args = parser.parse_args()

    data = json.loads(args.pnl_path.read_text(encoding="utf-8"))
    all_closed_trades = [t for t in data.get("trades", []) if t.get("status") == "closed"]
    closed_trades = all_closed_trades if args.include_sell_entries else [
        t for t in all_closed_trades if str(t.get("side") or "").lower() == "buy"
    ]

    print("=== ENTRY / EXIT PAIR ANALYSIS ===")
    print(f"P&L file: {args.pnl_path}")
    print(f"Closed trades analyzed: {len(closed_trades)}")
    if not args.include_sell_entries:
        print(f"(Filtered to BUY-origin trades from total closed trades: {len(all_closed_trades)})")

    by_entry_reason: dict[tuple[str, str], dict[str, Any]] = defaultdict(make_bucket)
    by_entry_version_reason: dict[tuple[str, str], dict[str, Any]] = defaultdict(make_bucket)
    by_entry_exit_strategy_reason: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(make_bucket)

    for trade in closed_trades:
        ent = entry_strategy(trade)
        ent_ver = entry_strategy_version(trade)
        exit_strat = str(trade.get("exit_strategy_id") or "unknown")
        exit_reason = str(trade.get("exit_reason") or "unknown")

        update_bucket(by_entry_reason[(ent, exit_reason)], trade)
        update_bucket(by_entry_version_reason[(ent_ver, exit_reason)], trade)
        update_bucket(by_entry_exit_strategy_reason[(ent, exit_strat, exit_reason)], trade)

    if args.limit_symbols > 0:
        for grouped in (by_entry_reason, by_entry_version_reason, by_entry_exit_strategy_reason):
            for bucket in grouped.values():
                bucket["symbols"] = set(sorted(bucket["symbols"])[: args.limit_symbols])

    print_table(
        "ENTRY STRATEGY × EXIT REASON",
        by_entry_reason,
        ["EntryStrategy", "ExitReason"],
    )
    print_table(
        "ENTRY STRATEGY VERSION × EXIT REASON",
        by_entry_version_reason,
        ["EntryStrategyVersion", "ExitReason"],
    )
    print_table(
        "ENTRY STRATEGY × EXIT STRATEGY × EXIT REASON",
        by_entry_exit_strategy_reason,
        ["EntryStrategy", "ExitStrategy", "ExitReason"],
    )

    if args.deep_dive_stop_loss:
        print_stop_loss_deep_dive(closed_trades, project_root)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
