#!/usr/bin/env python3
"""R0-v2/R9 addendum (2026-08-15): guardrail tolerance stress test using the
R11-B baseline historical backtest.

Motivation: R11-B's parameter search found that BreakoutMomentumStrategy's
edge is bull-market-dependent (validation window PF=0.56 during a real SPY/
QQQ correction). R11-C's follow-up found market-regime entry filters do not
fix this (the correction was a choppy/whipsaw regime, not a clean downtrend
a moving average can catch). As proposed in both writeups, this script
checks the OTHER side of the problem: does the existing R0-v2 guardrail
(config/guardrails/autonomous_stop.yaml, GuardrailEngine) actually catch and
limit the damage during that correction, via daily/weekly loss halts and
consecutive-losing-trade size reduction -- rather than trying to prevent the
entries in the first place?

Method: replay the R11-B baseline trades (min_momentum=0.05,
min_signal_strength=0.40, all 69 symbols, $10k fixed notional per trade) day
by day over the full 2-year window, maintaining a running equity curve
(baseline_equity + cumulative realized PnL from closed trades). Each day,
compute the exact same guardrail metrics production computes
(src/stock_swing/guardrails/risk_snapshot.py: daily_realized_loss_pct,
weekly_total_loss_pct, consecutive_losing_trades) and evaluate them through
the REAL GuardrailEngine (src/stock_swing/guardrails/rule_engine.py) loaded
from the actual production config file. Report which days would have
triggered which guardrail action, with particular attention to the
2025-10-27 - 2026-03-20 validation/correction window.

IMPORTANT LIMITATIONS (same class of caveats as the rest of R11):
  - daily_total_loss_pct (which also factors in intraday unrealized PnL
    delta) is NOT replayed here -- our backtest only has daily closes, no
    intraday mark-to-market, so this metric would need a same-day
    unrealized-PnL proxy we don't have. Only daily_realized_loss_pct,
    weekly_total_loss_pct, and consecutive_losing_trades (all computable
    from closed-trade history alone) are replayed.
  - stale_price_event_count / broker_tracker_mismatch_count / api_error_rate_pct
    / order_rejection_rate_pct / token_spend_spike_pct are operational
    metrics with no historical-backtest equivalent; assumed 0 (no trigger)
    for this replay, same as a perfectly clean run.
  - This is a SINGLE historical path with $10k fixed notional per trade,
    not the real position-sizing/allocation model (PortfolioAllocator,
    correlation cluster caps). Actual production equity swings will differ.
  - reduce_size's effect (50% smaller positions) is not simulated
    downstream -- this only reports WHEN it would have triggered, not what
    the counterfactual PnL would have been under reduced sizing.

Usage:
    python scripts/r0v2_guardrail_stress_test.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stock_swing.guardrails.risk_snapshot import (  # noqa: E402
    compute_daily_realized_loss_pct,
    compute_weekly_total_loss_pct,
    compute_consecutive_losing_trades,
)
from stock_swing.guardrails.rule_engine import GuardrailEngine, load_rules_from_dict, GuardAction  # noqa: E402

BASELINE_EQUITY = 1_000_000.0  # matches live account baseline (docs/console_improvement_tasks.md)
GUARDRAIL_CONFIG_PATH = PROJECT_ROOT / "config" / "guardrails" / "autonomous_stop.yaml"
BACKTEST_RESULTS_PATH = PROJECT_ROOT / "reports" / "r11_backtest_results.json"

# R11-B's backtest used a fixed $10,000 notional per trade for cross-symbol PF
# comparability (see r11_backtest_engine.py docstring), but LIVE average
# notional per trade is ~$29,100 (measured from data/tracking/pnl_state.json
# closed trades, 2026-08-15). Using the $10k backtest PnL directly against a
# $1M equity base would understate daily/weekly loss percentages by ~2.9x
# relative to what production actually risks per trade. Scale all trade PnL
# by this ratio to approximate realistic loss magnitudes for the guardrail
# metrics, while keeping the same win/loss PATTERN (which trades win/lose,
# and when) from the original backtest.
LIVE_AVG_NOTIONAL_PER_TRADE = 29100.0
BACKTEST_NOTIONAL_PER_TRADE = 10000.0
NOTIONAL_SCALE_FACTOR = LIVE_AVG_NOTIONAL_PER_TRADE / BACKTEST_NOTIONAL_PER_TRADE


def load_guardrail_engine() -> GuardrailEngine:
    with open(GUARDRAIL_CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    rules = load_rules_from_dict(cfg)
    warning_only = bool(cfg.get("paper_warning_only", False))
    return GuardrailEngine(rules, warning_only=warning_only)


def to_pnl_tracker_shape(trade: dict[str, Any], scale: float = 1.0) -> dict[str, Any]:
    """Convert an R11 backtest trade record into the shape risk_snapshot.py
    expects (pnl_tracker.state.trades format: status/exit_time/pnl).

    `scale` rescales pnl to approximate a realistic live notional per trade
    (see NOTIONAL_SCALE_FACTOR above) without altering the win/loss pattern.
    """
    return {
        "status": "closed",
        "exit_time": trade["exit_date"] + "T21:00:00+00:00",
        "pnl": trade["pnl"] * scale,
    }


def run_replay(all_trades: list[dict[str, Any]], scale: float, label: str) -> dict[str, Any]:
    print(f"\n{'=' * 70}\nReplay: {label} (notional scale factor = {scale:.2f}x)\n{'=' * 70}")

    all_dates = sorted(set(t["exit_date"] for t in all_trades) | set(t["entry_date"] for t in all_trades))
    engine = load_guardrail_engine()

    triggers: list[dict[str, Any]] = []
    running_equity = BASELINE_EQUITY

    for date_str in all_dates:
        # Trades closed up to and including this date (for cumulative equity + snapshot metrics)
        closed_so_far = [
            to_pnl_tracker_shape(t, scale=scale) for t in all_trades if t["exit_date"] <= date_str
        ]
        # Update running equity to reflect all realized PnL through this date
        running_equity = BASELINE_EQUITY + sum(t["pnl"] for t in closed_so_far)

        daily_realized = compute_daily_realized_loss_pct(closed_so_far, running_equity, reference_date=date_str)
        weekly_total = compute_weekly_total_loss_pct(closed_so_far, running_equity, reference_date=date_str)
        consecutive = compute_consecutive_losing_trades(closed_so_far)

        metrics = {
            "stale_price_event_count": 0,
            "broker_tracker_mismatch_count": 0,
            "daily_realized_loss_pct": daily_realized,
            "daily_total_loss_pct": 0.0,  # not replayable, see module docstring
            "weekly_total_loss_pct": weekly_total,
            "consecutive_losing_trades": consecutive,
            "api_error_rate_pct": 0.0,
            "order_rejection_rate_pct": 0.0,
            "token_spend_spike_pct": 0.0,
        }
        decision = engine.evaluate(metrics)
        if decision.action != GuardAction.allow:
            triggers.append({
                "date": date_str,
                "equity": round(running_equity, 2),
                "daily_realized_loss_pct": daily_realized,
                "weekly_total_loss_pct": weekly_total,
                "consecutive_losing_trades": consecutive,
                "action": decision.action.name,
                "triggered_rules": [t.name for t in decision.triggered],
            })

    print(f"\nTotal days simulated: {len(all_dates)}")
    print(f"Days with a non-allow guardrail action: {len(triggers)}")

    by_action: dict[str, int] = {}
    for t in triggers:
        by_action[t["action"]] = by_action.get(t["action"], 0) + 1
    print("\nBreakdown by action:")
    for action, count in sorted(by_action.items(), key=lambda x: -x[1]):
        print(f"  {action}: {count} day(s)")

    segments = {
        "train (2024-08-15 to 2025-10-24)": ("2024-08-15", "2025-10-24"),
        "validation (2025-10-27 to 2026-03-20)": ("2025-10-27", "2026-03-20"),
        "holdout (2026-03-23 to 2026-08-14)": ("2026-03-23", "2026-08-14"),
    }
    print("\nTriggers by R11-B segment:")
    for seg_label, (start, end) in segments.items():
        seg_triggers = [t for t in triggers if start <= t["date"] <= end]
        halt_count = len([t for t in seg_triggers if t["action"] == "halt"])
        print(f"  {seg_label}: {len(seg_triggers)} trigger day(s), {halt_count} halt(s)")

    print("\nDetail: all halt-level triggers (most severe action)")
    halts = [t for t in triggers if t["action"] == "halt"]
    for t in halts[:30]:
        print(f"  {t['date']}  equity=${t['equity']:,.0f}  "
              f"daily_realized={t['daily_realized_loss_pct']:+.2f}%  "
              f"weekly_total={t['weekly_total_loss_pct']:+.2f}%  "
              f"rules={t['triggered_rules']}")
    if len(halts) > 30:
        print(f"  ... and {len(halts) - 30} more")

    return {
        "label": label,
        "scale": scale,
        "total_days": len(all_dates),
        "total_triggers": len(triggers),
        "by_action": by_action,
        "triggers": triggers,
    }


def main() -> None:
    with open(BACKTEST_RESULTS_PATH) as f:
        backtest = json.load(f)
    all_trades = backtest["trades"]
    print(f"Loaded {len(all_trades)} R11-B baseline trades "
          f"(min_momentum=0.05, min_signal_strength=0.40)")

    result_unscaled = run_replay(
        all_trades, scale=1.0,
        label="unscaled ($10k/trade, matches R11-B backtest notional)",
    )
    result_scaled = run_replay(
        all_trades, scale=NOTIONAL_SCALE_FACTOR,
        label=f"scaled to live avg notional (~${LIVE_AVG_NOTIONAL_PER_TRADE:,.0f}/trade)",
    )

    out_path = PROJECT_ROOT / "reports" / "r0v2_guardrail_stress_test_results.json"
    with open(out_path, "w") as f:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "baseline_equity": BASELINE_EQUITY,
            "notional_scale_factor": NOTIONAL_SCALE_FACTOR,
            "unscaled": result_unscaled,
            "scaled_to_live_notional": result_scaled,
        }, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
