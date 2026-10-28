#!/usr/bin/env python3
"""R16 follow-up (2026-09-01): reduce_size design alternatives -- historical
re-simulation of Plan B (per-order size halving) and Plan C+A (tiered
reduction + minimum floor) against the ACTUAL production mechanism
(portfolio-level exposure-cap halving, binary block-or-allow) already
validated in scripts/r0v2_reduce_size_portfolio_level_check.py (2026-08-26).

Background
----------
2026-08-26 found that reduce_size does NOT halve each new order's size --
it halves the portfolio-wide exposure cap, which becomes a binary
block-or-allow switch once the existing open book already exceeds the
halved cap (52.1% of candidates fully blocked while active, vs 63 active
days / 13 fully-blocked days out of 2 years). 2026-09-01, the user asked
"why is cash sitting idle for so long -- isn't that an opportunity cost
too?" and requested a design review. Three alternatives were proposed;
this script re-simulates two of them (Plan B, Plan C+A) against the SAME
baseline and the SAME actual-mechanism control run, using the identical
R11-B universe/strategy/exit config as every prior script in this family,
so results are directly comparable apples-to-apples.

Mechanisms simulated
--------------------
1. baseline          : no reduce_size at all.
2. current_mechanism : production's ACTUAL behavior (exposure_cap_override
                        = dynamic_cap * 0.5 whenever consecutive_losing_
                        trades >= 5). Re-derived here (not re-using the
                        08-26 script's saved JSON) so all four mechanisms
                        run through byte-identical simulation code in one
                        pass, avoiding any subtle drift between separate
                        script runs.
3. plan_b            : exposure_cap_override is NEVER touched (stays at
                        the full dynamic cap at all times) -- instead,
                        final_shares from the normal-cap sizing result is
                        multiplied by 0.5 whenever consecutive_losing_
                        trades >= 5. This is a true per-order size
                        reduction: it can never fully zero out a candidate
                        the way the portfolio-cap mechanism can, because
                        it acts on the already-computed share count, not
                        on the exposure headroom used to compute it.
4. plan_c_plus_a     : tiered exposure-cap multiplier by severity
                        (5-8 losses: 0.75x, 9-12: 0.5x, 13+: 0.25x) PLUS a
                        minimum floor that guarantees at least
                        MIN_FLOOR_PCT (3%) of fresh headroom above the
                        current open book's exposure, regardless of how
                        reduced the tiered cap is. This directly targets
                        the "cash sits idle for weeks" complaint: even at
                        the most severe tier, a small amount of new buying
                        is still possible if a genuinely attractive
                        candidate appears.

All four mechanisms share the exact same entry/exit strategy, price data,
and PositionSizingPolicy (real production class, not a re-implementation)
as scripts/r0v2_reduce_size_portfolio_level_check.py -- only the exposure-
cap-override / final_shares computation differs per mechanism.

Usage:
    python scripts/r0v2_reduce_size_design_alternatives_20260901.py [--save]
"""
from __future__ import annotations

import argparse
import json
import sys
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
REDUCE_SIZE_THRESHOLD = 5
BASE_EXPOSURE_CAP = 0.68  # matches paper_demo.py's _BASE_EXPOSURE_CAP static base
                          # (dynamic signal-count bonus omitted for simplicity, same
                          # simplification used by the 2026-08-26 script -- see LIMITATIONS)

# Plan C tier thresholds (proposed 2026-09-01, not yet tuned against this data --
# this run's job is to see whether the SHAPE of the idea helps before any tuning)
PLAN_C_TIERS = [
    (13, 0.25),  # 13+ consecutive losses -> most severe cut
    (9, 0.50),   # 9-12 -> matches current mechanism's severity
    (5, 0.75),   # 5-8  -> mild cut (current mechanism has no tier this gentle)
]
# Plan A floor: always guarantee at least this much FRESH headroom above the
# current open book, no matter how severe the active tier's multiplier is.
PLAN_A_MIN_FLOOR_PCT = 0.03


def to_pnl_tracker_shape(trade: dict[str, Any]) -> dict[str, Any]:
    return {"status": "closed", "exit_time": trade["exit_date"] + "T21:00:00+00:00", "pnl": trade["pnl"]}


def plan_c_tier_multiplier(consecutive: int) -> float:
    """Return the tiered exposure-cap multiplier for a given consecutive-loss
    count. 1.0 (no reduction) below the lowest tier's threshold.
    """
    for threshold, multiplier in PLAN_C_TIERS:
        if consecutive >= threshold:
            return multiplier
    return 1.0


def run_simulation(
    symbols: list[str],
    equity: float,
    mechanism: str,
) -> dict[str, Any]:
    """Simulate R11-B's entry/exit logic under one of four sizing mechanisms.

    mechanism one of: "baseline", "current_mechanism", "plan_b", "plan_c_plus_a".
    """
    price_data = base.load_price_data(symbols)
    all_dates = sorted(set().union(*[set(d.keys()) for d in price_data.values()]))
    print(f"Simulating {len(symbols)} symbols, equity=${equity:,.0f}, mechanism={mechanism}")

    entry_strategy = base.BreakoutMomentumStrategy(min_momentum=0.05, min_signal_strength=0.40)
    exit_strategy = base.load_exit_strategy()
    sizing_policy = PositionSizingPolicy()

    open_positions: dict[str, base.Position] = {}
    closed_trades: list[dict[str, Any]] = []
    reduce_size_active_days = 0
    fully_blocked_days = 0
    candidates_seen_while_reduced = 0
    candidates_blocked_while_reduced = 0
    # Plan C+A specific: track which tier was active and how often the floor
    # rescued an otherwise-blocked candidate.
    tier_active_days: dict[str, int] = {"mild_5to8": 0, "moderate_9to12": 0, "severe_13plus": 0}
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

            # --- Exits (identical across all mechanisms) ---
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

            # --- Determine reduce_size / tier state ---
            trades_so_far = [to_pnl_tracker_shape(t) for t in closed_trades]
            consecutive = compute_consecutive_losing_trades(trades_so_far)

            if mechanism == "baseline":
                reduce_size_active = False
                exposure_cap = BASE_EXPOSURE_CAP
                per_order_multiplier = 1.0
            elif mechanism == "current_mechanism":
                reduce_size_active = consecutive >= REDUCE_SIZE_THRESHOLD
                exposure_cap = BASE_EXPOSURE_CAP * (0.5 if reduce_size_active else 1.0)
                per_order_multiplier = 1.0
            elif mechanism == "plan_b":
                # Exposure cap is NEVER touched -- per-order size is halved instead.
                reduce_size_active = consecutive >= REDUCE_SIZE_THRESHOLD
                exposure_cap = BASE_EXPOSURE_CAP
                per_order_multiplier = 0.5 if reduce_size_active else 1.0
            elif mechanism == "plan_c_plus_a":
                tier_mult = plan_c_tier_multiplier(consecutive)
                reduce_size_active = tier_mult < 1.0
                exposure_cap = BASE_EXPOSURE_CAP * tier_mult
                per_order_multiplier = 1.0
                if reduce_size_active:
                    if consecutive >= 13:
                        tier_active_days["severe_13plus"] += 1
                    elif consecutive >= 9:
                        tier_active_days["moderate_9to12"] += 1
                    else:
                        tier_active_days["mild_5to8"] += 1
            else:
                raise ValueError(f"unknown mechanism: {mechanism}")

            if reduce_size_active:
                reduce_size_active_days += 1

            # --- Current portfolio-level open notional (mark-to-market at last close) ---
            current_total_exposure = sum(
                pos.qty * (price_data.get(sym, {}).get(date_str, {}).get("close") or pos.entry_price)
                for sym, pos in open_positions.items()
            )

            # Plan A floor: guarantee at least PLAN_A_MIN_FLOOR_PCT of fresh
            # headroom above the current book, regardless of how low the
            # tiered cap pushed max_total_exposure_usd.
            effective_exposure_cap = exposure_cap
            if mechanism == "plan_c_plus_a" and reduce_size_active:
                current_exposure_pct = current_total_exposure / equity if equity > 0 else 0.0
                floor_cap = current_exposure_pct + PLAN_A_MIN_FLOOR_PCT
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
                    # Plan B: apply the per-order halving AFTER normal-cap sizing.
                    if per_order_multiplier != 1.0 and final_shares > 0:
                        final_shares = max(floor(final_shares * per_order_multiplier), 0)

                    if reduce_size_active:
                        day_seen += 1
                        candidates_seen_while_reduced += 1
                        # Track whether the Plan A floor is what saved this
                        # candidate (i.e. it would have been blocked under the
                        # tiered cap alone, but the floor gave it headroom).
                        if (
                            mechanism == "plan_c_plus_a"
                            and effective_exposure_cap > exposure_cap
                            and final_shares >= 1
                        ):
                            # Re-check: would the tiered cap alone (no floor) have
                            # blocked this candidate?
                            tiered_only_remaining = equity * exposure_cap - current_total_exposure
                            if tiered_only_remaining <= 0 or floor(tiered_only_remaining / price) < 1:
                                floor_rescued_candidates += 1

                    if final_shares < 1:
                        if reduce_size_active:
                            day_blocked += 1
                            candidates_blocked_while_reduced += 1
                        continue

                    qty = final_shares
                    open_positions[sym] = base.Position(
                        symbol=sym, entry_date=current_dt, entry_price=price,
                        qty=qty, entry_signal_strength=sig.signal_strength,
                    )
                    current_total_exposure += qty * price

                if reduce_size_active and day_seen > 0 and day_blocked == day_seen:
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
        "reduce_size_active_days": reduce_size_active_days,
        "fully_blocked_days": fully_blocked_days,
        "candidates_seen_while_reduced": candidates_seen_while_reduced,
        "candidates_blocked_while_reduced": candidates_blocked_while_reduced,
        "tier_active_days": tier_active_days,
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
    for mechanism in ["baseline", "current_mechanism", "plan_b", "plan_c_plus_a"]:
        print("=" * 90)
        print(f"Mechanism: {mechanism}")
        print("=" * 90)
        sim = run_simulation(symbols, args.equity, mechanism)
        summary = base.summarize(sim["trades"], mechanism)
        print(json.dumps(summary, indent=2, default=str))
        print(f"  reduce_size_active_days={sim['reduce_size_active_days']} "
              f"fully_blocked_days={sim['fully_blocked_days']} "
              f"candidates_seen_while_reduced={sim['candidates_seen_while_reduced']} "
              f"candidates_blocked_while_reduced={sim['candidates_blocked_while_reduced']}")
        if mechanism == "plan_c_plus_a":
            print(f"  tier_active_days={sim['tier_active_days']} "
                  f"floor_rescued_candidates={sim['floor_rescued_candidates']}")
        results[mechanism] = {**summary, **{k: v for k, v in sim.items() if k != "trades"}}
        print()

    print("=" * 90)
    print("COMPARISON SUMMARY")
    print("=" * 90)
    header = f"  {'metric':22}"
    for m in ["baseline", "current_mechanism", "plan_b", "plan_c_plus_a"]:
        header += f"{m:>20}"
    print(header)
    for metric in ["n", "win_rate", "profit_factor", "net_pnl", "avg_return_pct"]:
        row = f"  {metric:22}"
        for m in ["baseline", "current_mechanism", "plan_b", "plan_c_plus_a"]:
            row += f"{str(results[m].get(metric)):>20}"
        print(row)
    print()
    for metric in ["reduce_size_active_days", "fully_blocked_days",
                   "candidates_seen_while_reduced", "candidates_blocked_while_reduced"]:
        row = f"  {metric:32}"
        for m in ["current_mechanism", "plan_b", "plan_c_plus_a"]:
            row += f"{str(results[m].get(metric)):>18}"
        print(row)

    print(f"\n  plan_c_plus_a tier_active_days: {results['plan_c_plus_a']['tier_active_days']}")
    print(f"  plan_c_plus_a floor_rescued_candidates: {results['plan_c_plus_a']['floor_rescued_candidates']}")

    if args.save:
        out_dir = PROJECT_ROOT / "docs" / "r0v2_reduce_size_design_alternatives_20260901"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "results.json"
        serializable = {
            m: {k: v for k, v in r.items() if k != "trades"}
            for m, r in results.items()
        }
        out_path.write_text(
            json.dumps(serializable, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nSaved: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
