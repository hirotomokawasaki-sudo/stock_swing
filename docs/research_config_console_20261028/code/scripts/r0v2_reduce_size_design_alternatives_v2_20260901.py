#!/usr/bin/env python3
"""R16 follow-up part 2 (2026-09-01): further tuning of the reduce_size
design alternatives -- Plan C+A tier/floor variants, and a Plan B+C blend
(tiered PER-ORDER size reduction, never touching the exposure cap).

Background
----------
scripts/r0v2_reduce_size_design_alternatives_20260901.py (same day, earlier)
found that flat Plan B (per-order size *0.5 whenever consecutive_losing_
trades>=5) outperformed both the current production mechanism and the
original Plan C+A (tiered exposure-cap cut + 3% floor) on every PF/net_pnl
metric, while also being the only mechanism that structurally cannot fully
block a day's candidates. Plan C+A's floor did reduce the block rate
(52.1% -> 20.6%) as designed, but the looser mild-tier cut (0.75x vs
current's flat 0.5x) appears to have let in extra losing trades this
period, dragging PF down (1.4745 vs 1.497 current / 1.5093 plan_b).

The user asked for two follow-ups:
1. Tune Plan C+A (tier thresholds/multipliers, floor size) to see whether
   the block-rate improvement can be kept without the PF cost.
2. Build a Plan B+C blend: apply Plan B's core mechanism (tiered PER-ORDER
   size multiplier, exposure cap never touched -> structurally cannot
   block) but grade the severity by consecutive-loss tier (mirroring Plan
   C's tiering idea) instead of Plan B's flat 0.5x.

This script generalizes the previous script's four hardcoded mechanisms
into a single parameterized simulation function driven by MECHANISM_CONFIGS,
so every variant below runs through byte-identical simulation code (same
entry/exit strategy, same real PositionSizingPolicy class, same price data)
-- only the (exposure_cap_tiers, min_floor_pct, per_order_tiers) config
differs per variant.

Usage:
    python scripts/r0v2_reduce_size_design_alternatives_v2_20260901.py [--save]
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
BASE_EXPOSURE_CAP = 0.68  # matches paper_demo.py's _BASE_EXPOSURE_CAP static base
                          # (dynamic signal-count bonus omitted for simplicity, same
                          # simplification used by the 2026-08-26/09-01 scripts)


@dataclass
class MechanismConfig:
    """One reduce_size design variant.

    exposure_cap_tiers: list of (consecutive_loss_threshold, cap_multiplier),
        evaluated highest-threshold-first (first match wins). Applied to
        BASE_EXPOSURE_CAP. None/empty means the exposure cap is never
        touched (structurally cannot fully block -- Plan B family).
    min_floor_pct: if set, guarantees at least this much FRESH headroom
        above the current open book's exposure, regardless of how low the
        tiered exposure cap pushed things. Only meaningful when
        exposure_cap_tiers is set.
    per_order_tiers: list of (consecutive_loss_threshold, size_multiplier)
        applied directly to the already-sized final_shares count (Plan B
        mechanism). None/empty means no per-order reduction.
    """

    label: str
    exposure_cap_tiers: list[tuple[int, float]] = field(default_factory=list)
    min_floor_pct: float | None = None
    per_order_tiers: list[tuple[int, float]] = field(default_factory=list)


def tiered_multiplier(consecutive: int, tiers: list[tuple[int, float]]) -> float:
    """Return the multiplier for the highest-threshold tier consecutive
    qualifies for (tiers need not be pre-sorted). 1.0 (no reduction) if
    consecutive is below every tier's threshold or tiers is empty.
    """
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


MECHANISM_CONFIGS: list[MechanismConfig] = [
    MechanismConfig(label="baseline"),
    MechanismConfig(label="current_mechanism", exposure_cap_tiers=[(5, 0.5)]),
    MechanismConfig(label="plan_b_flat", per_order_tiers=[(5, 0.5)]),
    MechanismConfig(
        label="plan_c_plus_a_v1_original",
        exposure_cap_tiers=[(5, 0.75), (9, 0.5), (13, 0.25)],
        min_floor_pct=0.03,
    ),
    # --- Plan C+A tuning variants (follow-up request 1) ---
    MechanismConfig(
        label="plan_c_plus_a_v2_strict_mild",
        # Match current mechanism's severity at the low end (0.5x, not the
        # looser 0.75x that seemed to hurt PF in v1), then get progressively
        # stricter -- tests whether the mild-tier looseness was the actual
        # cause of v1's PF drag.
        exposure_cap_tiers=[(5, 0.5), (9, 0.35), (13, 0.15)],
        min_floor_pct=0.03,
    ),
    MechanismConfig(
        label="plan_c_plus_a_v3_smaller_floor",
        # Same tiers as v1, but a smaller floor (1% instead of 3%) --
        # tests whether a smaller safety valve still captures most of the
        # block-rate benefit with less PF cost.
        exposure_cap_tiers=[(5, 0.75), (9, 0.5), (13, 0.25)],
        min_floor_pct=0.01,
    ),
    MechanismConfig(
        label="plan_c_plus_a_v4_no_floor",
        # Same tiers as v1, but NO floor -- isolates how much of v1's PF
        # drag came from the looser mild tier alone vs. the floor rescuing
        # candidates that "should have" stayed blocked.
        exposure_cap_tiers=[(5, 0.75), (9, 0.5), (13, 0.25)],
        min_floor_pct=None,
    ),
    MechanismConfig(
        label="plan_c_plus_a_v5_strict_mild_bigger_floor",
        # Combine v2's strict tiers with a slightly bigger floor (5%) --
        # tests whether floor size can be pushed further once the tiers
        # themselves are not the looser culprit.
        exposure_cap_tiers=[(5, 0.5), (9, 0.35), (13, 0.15)],
        min_floor_pct=0.05,
    ),
    # --- Plan B+C blend (follow-up request 2) ---
    MechanismConfig(
        label="plan_bc_blend_v1_tiered_per_order",
        # Plan B's core property (exposure cap never touched -> structurally
        # cannot fully block) but grade severity by consecutive-loss tier
        # instead of Plan B's flat 0.5x, mirroring Plan C's tiering idea.
        per_order_tiers=[(5, 0.75), (9, 0.5), (13, 0.25)],
    ),
    MechanismConfig(
        label="plan_bc_blend_v2_aggressive_severe",
        # Same mild/moderate tiers as v1, but cut harder at the severe tier
        # (0.1x instead of 0.25x) -- since this mechanism can never fully
        # block, testing how far the severe-tier cut can go before it
        # starts to matter, without the "zero" risk exposure-cap blocking has.
        per_order_tiers=[(5, 0.75), (9, 0.5), (13, 0.1)],
    ),
]


def to_pnl_tracker_shape(trade: dict[str, Any]) -> dict[str, Any]:
    return {"status": "closed", "exit_time": trade["exit_date"] + "T21:00:00+00:00", "pnl": trade["pnl"]}


def run_simulation(
    symbols: list[str],
    equity: float,
    config: MechanismConfig,
) -> dict[str, Any]:
    """Simulate R11-B's entry/exit logic under one parameterized reduce_size
    design variant (see MechanismConfig docstring).
    """
    price_data = base.load_price_data(symbols)
    all_dates = sorted(set().union(*[set(d.keys()) for d in price_data.values()]))
    print(f"Simulating {len(symbols)} symbols, equity=${equity:,.0f}, mechanism={config.label}")

    entry_strategy = base.BreakoutMomentumStrategy(min_momentum=0.05, min_signal_strength=0.40)
    exit_strategy = base.load_exit_strategy()
    sizing_policy = PositionSizingPolicy()

    open_positions: dict[str, base.Position] = {}
    closed_trades: list[dict[str, Any]] = []
    active_days = 0
    fully_blocked_days = 0
    candidates_seen_while_active = 0
    candidates_blocked_while_active = 0
    floor_rescued_candidates = 0

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

            # --- Exits (identical across all variants) ---
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

            # --- Determine state from consecutive losses ---
            trades_so_far = [to_pnl_tracker_shape(t) for t in closed_trades]
            consecutive = compute_consecutive_losing_trades(trades_so_far)

            exposure_mult = tiered_multiplier(consecutive, config.exposure_cap_tiers)
            per_order_mult = tiered_multiplier(consecutive, config.per_order_tiers)
            is_active = exposure_mult < 1.0 or per_order_mult < 1.0
            if is_active:
                active_days += 1

            exposure_cap = BASE_EXPOSURE_CAP * exposure_mult

            # --- Current portfolio-level open notional (mark-to-market at last close) ---
            current_total_exposure = sum(
                pos.qty * (price_data.get(sym, {}).get(date_str, {}).get("close") or pos.entry_price)
                for sym, pos in open_positions.items()
            )

            # Floor: guarantee at least min_floor_pct of fresh headroom above
            # the current book, regardless of how low the tiered cap pushed
            # max_total_exposure_usd. Only meaningful when exposure_cap_tiers
            # actually reduced the cap this step.
            effective_exposure_cap = exposure_cap
            if config.min_floor_pct is not None and exposure_mult < 1.0:
                current_exposure_pct = current_total_exposure / equity if equity > 0 else 0.0
                floor_cap = current_exposure_pct + config.min_floor_pct
                if floor_cap > effective_exposure_cap:
                    effective_exposure_cap = floor_cap

            # --- Entry candidates ---
            candidate_records = []
            for sym, recs in features_by_symbol.items():
                if sym not in open_positions:
                    candidate_records.extend(recs)
            if candidate_records:
                candidate_momentum = momentum_feat.compute(candidate_records)
                buy_signals = entry_strategy.generate(candidate_momentum)

                day_blocked = 0
                day_seen = 0
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

                    if is_active:
                        day_seen += 1
                        candidates_seen_while_active += 1
                        if (
                            config.min_floor_pct is not None
                            and effective_exposure_cap > exposure_cap
                            and final_shares >= 1
                        ):
                            tiered_only_remaining = equity * exposure_cap - current_total_exposure
                            if tiered_only_remaining <= 0 or floor(tiered_only_remaining / price) < 1:
                                floor_rescued_candidates += 1

                    if final_shares < 1:
                        if is_active:
                            day_blocked += 1
                            candidates_blocked_while_active += 1
                        continue

                    qty = final_shares
                    open_positions[sym] = base.Position(
                        symbol=sym, entry_date=current_dt, entry_price=price,
                        qty=qty, entry_signal_strength=sig.signal_strength,
                    )
                    current_total_exposure += qty * price

                if is_active and day_seen > 0 and day_blocked == day_seen:
                    fully_blocked_days += 1
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

    return {
        "trades": closed_trades,
        "active_days": active_days,
        "fully_blocked_days": fully_blocked_days,
        "candidates_seen_while_active": candidates_seen_while_active,
        "candidates_blocked_while_active": candidates_blocked_while_active,
        "floor_rescued_candidates": floor_rescued_candidates,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--equity", type=float, default=1_000_000.0)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    symbols = sorted(p.stem for p in CACHE_DIR.glob("*.json") if not p.stem.startswith("_"))
    print(f"Universe: {len(symbols)} symbols\n")

    results: dict[str, Any] = {}
    for config in MECHANISM_CONFIGS:
        print("=" * 90)
        print(f"Mechanism: {config.label}")
        print(f"  exposure_cap_tiers={config.exposure_cap_tiers} min_floor_pct={config.min_floor_pct} "
              f"per_order_tiers={config.per_order_tiers}")
        print("=" * 90)
        sim = run_simulation(symbols, args.equity, config)
        summary = base.summarize(sim["trades"], config.label)
        print(json.dumps(summary, indent=2, default=str))
        print(f"  active_days={sim['active_days']} fully_blocked_days={sim['fully_blocked_days']} "
              f"candidates_seen_while_active={sim['candidates_seen_while_active']} "
              f"candidates_blocked_while_active={sim['candidates_blocked_while_active']} "
              f"floor_rescued_candidates={sim['floor_rescued_candidates']}")
        results[config.label] = {**summary, **{k: v for k, v in sim.items() if k != "trades"}}
        print()

    print("=" * 130)
    print("COMPARISON SUMMARY")
    print("=" * 130)
    labels = [c.label for c in MECHANISM_CONFIGS]
    for metric in ["n", "win_rate", "profit_factor", "net_pnl", "avg_return_pct",
                   "active_days", "fully_blocked_days", "candidates_blocked_while_active",
                   "floor_rescued_candidates"]:
        row = f"  {metric:32}"
        for lbl in labels:
            row += f"{str(results[lbl].get(metric)):>16}"
        print(row)

    if args.save:
        out_dir = PROJECT_ROOT / "docs" / "r0v2_reduce_size_design_alternatives_20260901"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "results_v2_tuning.json"
        serializable = {
            lbl: {k: v for k, v in r.items() if k != "trades"}
            for lbl, r in results.items()
        }
        out_path.write_text(
            json.dumps(serializable, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nSaved: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
