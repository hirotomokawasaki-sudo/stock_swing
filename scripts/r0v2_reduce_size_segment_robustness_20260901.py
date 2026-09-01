#!/usr/bin/env python3
"""R16 follow-up part 3 (2026-09-01): train/validation/holdout robustness
check for the reduce_size design candidates identified in part 2
(plan_c_plus_a_v2_strict_mild in particular).

Background
----------
Part 2 (r0v2_reduce_size_design_alternatives_v2_20260901.py) found
plan_c_plus_a_v2_strict_mild (tiers 0.5/0.35/0.15 + 3% floor) outperformed
every other candidate (including flat Plan B) on the FULL 2-year
simulation: PF 1.5372 vs current_mechanism's 1.497 and plan_b_flat's
1.5093. The user explicitly flagged the risk that a narrow 9-point search
over one continuous backtest window can overfit to that specific window
(same overfitting trap R11-B's parameter search was designed to avoid --
see docs/console_improvement_tasks.md's R11-B follow-up section and
scripts/r11b_param_search.py) and asked for one more check before treating
part 2's result as decision-ready.

Method
------
Reuses the EXACT same train(60%)/validation(20%)/holdout(20%) date
segmentation already established and used for BreakoutMomentumStrategy's
own parameter search (scripts/r11b_param_search.py's
compute_date_segments()), applied to the SAME price-data date range this
whole script family shares. Rather than re-running each mechanism 3x (one
simulation per segment), each mechanism's SINGLE already-run 2-year trade
list (identical simulation to part 1/2, byte-for-byte) is partitioned by
entry_date into the three segments, and PF/win_rate/net_pnl is computed
independently per segment. This is the same "partition trades from one run
by entry_date" technique r11b_param_search.py uses for its own robustness
check, applied here to the reduce_size design candidates instead of
strategy entry parameters.

A candidate is treated as "segment-robust" only if it beats or matches
current_mechanism's PF in BOTH the validation AND holdout segments
independently (not just in aggregate) -- mirroring r11b_param_search.py's
selection rule (train PF>1 AND validation PF>1, never picked on train
alone).

Candidates re-tested (from part 2's results): current_mechanism,
plan_b_flat, plan_c_plus_a_v1_original, plan_c_plus_a_v2_strict_mild
(part-2 winner), plan_c_plus_a_v4_no_floor, plan_bc_blend_v1.

Usage:
    python scripts/r0v2_reduce_size_segment_robustness_20260901.py [--save]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import floor
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import r11_backtest_engine as base  # noqa: E402
from stock_swing.guardrails.risk_snapshot import compute_consecutive_losing_trades  # noqa: E402
from stock_swing.risk.position_sizing import PositionSizingInputs, PositionSizingPolicy  # noqa: E402

CACHE_DIR = PROJECT_ROOT / "data" / "r11_price_cache"
BASE_EXPOSURE_CAP = 0.68


@dataclass
class MechanismConfig:
    label: str
    exposure_cap_tiers: list[tuple[int, float]] = field(default_factory=list)
    min_floor_pct: float | None = None
    per_order_tiers: list[tuple[int, float]] = field(default_factory=list)


def tiered_multiplier(consecutive: int, tiers: list[tuple[int, float]]) -> float:
    if not tiers:
        return 1.0
    best = 1.0
    matched = False
    for threshold, multiplier in sorted(tiers, key=lambda t: -t[0]):
        if consecutive >= threshold:
            best = multiplier
            matched = True
            break
    return best if matched else 1.0


# Re-test the top candidates from part 2, plus baseline for reference.
MECHANISM_CONFIGS: list[MechanismConfig] = [
    MechanismConfig(label="baseline"),
    MechanismConfig(label="current_mechanism", exposure_cap_tiers=[(5, 0.5)]),
    MechanismConfig(label="plan_b_flat", per_order_tiers=[(5, 0.5)]),
    MechanismConfig(
        label="plan_c_plus_a_v1_original",
        exposure_cap_tiers=[(5, 0.75), (9, 0.5), (13, 0.25)],
        min_floor_pct=0.03,
    ),
    MechanismConfig(
        label="plan_c_plus_a_v2_strict_mild",
        exposure_cap_tiers=[(5, 0.5), (9, 0.35), (13, 0.15)],
        min_floor_pct=0.03,
    ),
    MechanismConfig(
        label="plan_c_plus_a_v4_no_floor",
        exposure_cap_tiers=[(5, 0.75), (9, 0.5), (13, 0.25)],
        min_floor_pct=None,
    ),
    MechanismConfig(
        label="plan_bc_blend_v1_tiered_per_order",
        per_order_tiers=[(5, 0.75), (9, 0.5), (13, 0.25)],
    ),
]


def compute_date_segments(all_dates: list[str]) -> dict[str, tuple[str, str]]:
    """Identical logic to scripts/r11b_param_search.py's compute_date_segments():
    train(60%) / validation(20%) / holdout(20%), non-overlapping, in date order.
    """
    n = len(all_dates)
    i60 = int(n * 0.6)
    i80 = int(n * 0.8)
    return {
        "train": (all_dates[0], all_dates[i60 - 1]),
        "validation": (all_dates[i60], all_dates[i80 - 1]),
        "holdout": (all_dates[i80], all_dates[-1]),
    }


def partition_trades(trades: list[dict[str, Any]], segments: dict[str, tuple[str, str]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {name: [] for name in segments}
    for t in trades:
        entry_date = t["entry_date"]
        for name, (start, end) in segments.items():
            if start <= entry_date <= end:
                out[name].append(t)
                break
    return out


def to_pnl_tracker_shape(trade: dict[str, Any]) -> dict[str, Any]:
    return {"status": "closed", "exit_time": trade["exit_date"] + "T21:00:00+00:00", "pnl": trade["pnl"]}


def run_simulation(symbols: list[str], equity: float, config: MechanismConfig) -> list[dict[str, Any]]:
    """Same simulation as part 2's run_simulation(), returns only the trade
    list (this script partitions it by date afterward rather than needing
    per-segment tracking fields).
    """
    price_data = base.load_price_data(symbols)
    all_dates = sorted(set().union(*[set(d.keys()) for d in price_data.values()]))

    entry_strategy = base.BreakoutMomentumStrategy(min_momentum=0.05, min_signal_strength=0.40)
    exit_strategy = base.load_exit_strategy()
    sizing_policy = PositionSizingPolicy()

    open_positions: dict[str, base.Position] = {}
    closed_trades: list[dict[str, Any]] = []

    for i, date_str in enumerate(all_dates):
        current_dt = datetime.fromisoformat(date_str).replace(hour=21, tzinfo=timezone.utc)
        base._freeze(current_dt)
        try:
            window_start_idx = max(0, i - base.BAR_LIMIT + 1)
            window_dates = all_dates[window_start_idx : i + 1]

            features_by_symbol: dict[str, list] = {}
            for sym, bars in price_data.items():
                recs = [base.make_record(sym, d, bars[d]) for d in window_dates if d in bars]
                if recs:
                    features_by_symbol[sym] = recs

            momentum_feat = base.PriceMomentumFeature(period_days=base.BAR_LIMIT)
            all_records = []
            for recs in features_by_symbol.values():
                all_records.extend(recs)
            momentum_results = momentum_feat.compute(all_records)

            if open_positions:
                current_positions_payload = {}
                for sym, pos in open_positions.items():
                    bar = price_data.get(sym, {}).get(date_str)
                    if bar is None:
                        continue
                    close_px = bar["close"]
                    pos.peak_price = max(pos.peak_price, close_px)
                    current_positions_payload[sym] = {
                        "qty": pos.qty, "avg_entry_price": pos.entry_price,
                        "current_price": close_px, "peak_price": pos.peak_price,
                        "created_at": pos.entry_date.isoformat(),
                        "entry_signal_strength": pos.entry_signal_strength,
                    }
                if current_positions_payload:
                    exit_signals = exit_strategy.generate(
                        features=list(momentum_results), current_positions=current_positions_payload,
                    )
                    for sig in exit_signals:
                        sym = sig.symbol
                        pos = open_positions.get(sym)
                        if pos is None:
                            continue
                        exit_price = sig.metadata.get("current_price", price_data[sym][date_str]["close"])
                        pnl = (exit_price - pos.entry_price) * pos.qty
                        return_pct = (exit_price - pos.entry_price) / pos.entry_price
                        hold_days = (current_dt - pos.entry_date).days
                        closed_trades.append({
                            "symbol": sym, "entry_date": pos.entry_date.date().isoformat(),
                            "entry_price": pos.entry_price, "exit_date": date_str,
                            "exit_price": exit_price, "qty": pos.qty, "pnl": pnl,
                            "return_pct": return_pct, "holding_days": hold_days,
                            "exit_reason": sig.metadata.get("exit_trigger", "unknown"),
                            "entry_signal_strength": pos.entry_signal_strength,
                        })
                        del open_positions[sym]

            trades_so_far = [to_pnl_tracker_shape(t) for t in closed_trades]
            consecutive = compute_consecutive_losing_trades(trades_so_far)

            exposure_mult = tiered_multiplier(consecutive, config.exposure_cap_tiers)
            per_order_mult = tiered_multiplier(consecutive, config.per_order_tiers)
            exposure_cap = BASE_EXPOSURE_CAP * exposure_mult

            current_total_exposure = sum(
                pos.qty * (price_data.get(sym, {}).get(date_str, {}).get("close") or pos.entry_price)
                for sym, pos in open_positions.items()
            )

            effective_exposure_cap = exposure_cap
            if config.min_floor_pct is not None and exposure_mult < 1.0:
                current_exposure_pct = current_total_exposure / equity if equity > 0 else 0.0
                floor_cap = current_exposure_pct + config.min_floor_pct
                if floor_cap > effective_exposure_cap:
                    effective_exposure_cap = floor_cap

            candidate_records = []
            for sym, recs in features_by_symbol.items():
                if sym not in open_positions:
                    candidate_records.extend(recs)
            if candidate_records:
                candidate_momentum = momentum_feat.compute(candidate_records)
                buy_signals = entry_strategy.generate(candidate_momentum)

                for sig in buy_signals:
                    sym = sig.symbol
                    if sym in open_positions:
                        continue
                    bar = price_data.get(sym, {}).get(date_str)
                    if bar is None or bar.get("close", 0) <= 0:
                        continue
                    price = bar["close"]

                    sizing_result = sizing_policy.size(PositionSizingInputs(
                        account_equity=equity,
                        current_price=price,
                        current_total_exposure=current_total_exposure,
                        market_regime="bullish",
                        symbol=sym,
                        confidence=sig.confidence if hasattr(sig, "confidence") else None,
                        exposure_cap_override=effective_exposure_cap,
                    ))

                    final_shares = sizing_result.final_shares
                    if per_order_mult != 1.0 and final_shares > 0:
                        final_shares = max(floor(final_shares * per_order_mult), 0)

                    if final_shares < 1:
                        continue

                    qty = final_shares
                    open_positions[sym] = base.Position(
                        symbol=sym, entry_date=current_dt, entry_price=price,
                        qty=qty, entry_signal_strength=sig.signal_strength,
                    )
                    current_total_exposure += qty * price
        finally:
            base._unfreeze()

    final_date = all_dates[-1]
    for sym, pos in open_positions.items():
        bar = price_data.get(sym, {}).get(final_date)
        if bar is None:
            continue
        exit_price = bar["close"]
        pnl = (exit_price - pos.entry_price) * pos.qty
        return_pct = (exit_price - pos.entry_price) / pos.entry_price
        hold_days = (datetime.fromisoformat(final_date).replace(tzinfo=timezone.utc) - pos.entry_date).days
        closed_trades.append({
            "symbol": sym, "entry_date": pos.entry_date.date().isoformat(),
            "entry_price": pos.entry_price, "exit_date": final_date,
            "exit_price": exit_price, "qty": pos.qty, "pnl": pnl,
            "return_pct": return_pct, "holding_days": hold_days,
            "exit_reason": "backtest_end_forced_close",
            "entry_signal_strength": pos.entry_signal_strength,
        })

    return closed_trades


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--equity", type=float, default=1_000_000.0)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    symbols = sorted(p.stem for p in CACHE_DIR.glob("*.json") if not p.stem.startswith("_"))
    print(f"Universe: {len(symbols)} symbols\n")

    price_data = base.load_price_data(symbols)
    all_dates = sorted(set().union(*[set(d.keys()) for d in price_data.values()]))
    segments = compute_date_segments(all_dates)
    print(f"Segments: train={segments['train']} validation={segments['validation']} "
          f"holdout={segments['holdout']}\n")

    results: dict[str, dict[str, Any]] = {}
    for config in MECHANISM_CONFIGS:
        print("=" * 90)
        print(f"Mechanism: {config.label}")
        print("=" * 90)
        trades = run_simulation(symbols, args.equity, config)
        by_segment = partition_trades(trades, segments)
        seg_summaries = {}
        for seg_name in ["train", "validation", "holdout"]:
            seg_trades = by_segment[seg_name]
            summary = base.summarize(seg_trades, f"{config.label}_{seg_name}")
            seg_summaries[seg_name] = summary
            print(f"  {seg_name:12} n={summary.get('n'):>5} "
                  f"win_rate={summary.get('win_rate')!s:>8} "
                  f"PF={summary.get('profit_factor')!s:>8} "
                  f"net_pnl={summary.get('net_pnl')!s:>14}")
        overall = base.summarize(trades, config.label)
        print(f"  {'overall':12} n={overall.get('n'):>5} "
              f"win_rate={overall.get('win_rate')!s:>8} "
              f"PF={overall.get('profit_factor')!s:>8} "
              f"net_pnl={overall.get('net_pnl')!s:>14}")
        results[config.label] = {"segments": seg_summaries, "overall": overall}
        print()

    print("=" * 130)
    print("ROBUSTNESS SUMMARY: PF per segment (candidate must beat current_mechanism in")
    print("BOTH validation AND holdout independently to be considered segment-robust)")
    print("=" * 130)
    header = f"  {'mechanism':38}{'train_PF':>12}{'val_PF':>12}{'holdout_PF':>12}{'overall_PF':>12}"
    print(header)
    current_val_pf = results["current_mechanism"]["segments"]["validation"].get("profit_factor")
    current_hold_pf = results["current_mechanism"]["segments"]["holdout"].get("profit_factor")
    for config in MECHANISM_CONFIGS:
        lbl = config.label
        r = results[lbl]
        row = f"  {lbl:38}"
        row += f"{str(r['segments']['train'].get('profit_factor')):>12}"
        row += f"{str(r['segments']['validation'].get('profit_factor')):>12}"
        row += f"{str(r['segments']['holdout'].get('profit_factor')):>12}"
        row += f"{str(r['overall'].get('profit_factor')):>12}"
        print(row)

    print()
    print("Segment-robust check (val_PF >= current AND holdout_PF >= current, current excluded):")
    for config in MECHANISM_CONFIGS:
        lbl = config.label
        if lbl in ("baseline", "current_mechanism"):
            continue
        val_pf = results[lbl]["segments"]["validation"].get("profit_factor")
        hold_pf = results[lbl]["segments"]["holdout"].get("profit_factor")
        try:
            val_ok = isinstance(val_pf, (int, float)) and isinstance(current_val_pf, (int, float)) and val_pf >= current_val_pf
        except TypeError:
            val_ok = False
        try:
            hold_ok = isinstance(hold_pf, (int, float)) and isinstance(current_hold_pf, (int, float)) and hold_pf >= current_hold_pf
        except TypeError:
            hold_ok = False
        verdict = "ROBUST" if (val_ok and hold_ok) else ("PARTIAL" if (val_ok or hold_ok) else "NOT ROBUST")
        print(f"  {lbl:38} val_ok={val_ok!s:6} hold_ok={hold_ok!s:6} -> {verdict}")

    if args.save:
        out_dir = PROJECT_ROOT / "docs" / "r0v2_reduce_size_design_alternatives_20260901"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "results_v3_segment_robustness.json"
        out_path.write_text(
            json.dumps({
                "segments": {k: list(v) for k, v in segments.items()},
                "results": results,
            }, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nSaved: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
