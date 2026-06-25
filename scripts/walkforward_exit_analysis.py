#!/usr/bin/env python3
"""Walk-forward exit analysis using closed trade history (P4-A).

Evaluates whether different exit parameters would have improved outcomes
by replaying exit rules against each closed trade's peak_price and return path.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stock_swing.tracking.pnl_tracker import PnLTracker


@dataclass
class ExitScenario:
    name: str
    stop_loss_pct: float
    trailing_activation_pct: float
    trailing_stop_pct: float


SCENARIOS: list[ExitScenario] = [
    ExitScenario("current", -0.07, 0.08, 0.04),
    ExitScenario("tighter_stop", -0.05, 0.08, 0.04),
    ExitScenario("wider_stop", -0.09, 0.08, 0.04),
    ExitScenario("earlier_trail", -0.07, 0.05, 0.03),
    ExitScenario("later_trail", -0.07, 0.10, 0.05),
    ExitScenario("aggressive", -0.05, 0.05, 0.03),
    ExitScenario("conservative", -0.09, 0.12, 0.06),
]


def simulate_exit(
    entry_price: float,
    peak_price: float,
    exit_price: float,
    scenario: ExitScenario,
) -> dict[str, float]:
    """Simulate exit under scenario params. Returns simulated return_pct."""
    if entry_price <= 0:
        return {"simulated_return": 0.0, "exit_trigger": "invalid"}

    stop_price = entry_price * (1 + scenario.stop_loss_pct)
    if exit_price <= stop_price:
        return {"simulated_return": scenario.stop_loss_pct, "exit_trigger": "stop_loss"}

    peak_return = (peak_price - entry_price) / entry_price if entry_price > 0 else 0
    if peak_return >= scenario.trailing_activation_pct:
        trail_price = peak_price * (1 - scenario.trailing_stop_pct)
        if exit_price <= trail_price:
            sim_return = (trail_price - entry_price) / entry_price
            return {
                "simulated_return": round(sim_return, 4),
                "exit_trigger": "trailing_stop",
            }
        actual_return = (exit_price - entry_price) / entry_price
        return {
            "simulated_return": round(actual_return, 4),
            "exit_trigger": "held_to_actual",
        }

    actual_return = (exit_price - entry_price) / entry_price
    return {"simulated_return": round(actual_return, 4), "exit_trigger": "held_to_actual"}


def main() -> None:
    tracker = PnLTracker(PROJECT_ROOT)
    closed = [
        t for t in tracker.state.trades
        if t.get("status") == "closed"
        and t.get("entry_price")
        and t.get("exit_price")
    ]
    if not closed:
        print("No closed trades to analyse.")
        return

    scenario_totals: dict[str, float] = {s.name: 0.0 for s in SCENARIOS}
    scenario_wins: dict[str, int] = {s.name: 0 for s in SCENARIOS}

    for t in closed:
        ep = float(t.get("entry_price", 0))
        xp = float(t.get("exit_price", 0))
        peak = float(t.get("peak_price") or ep)
        qty = int(t.get("qty", 1))
        if ep <= 0 or xp <= 0:
            continue
        for sc in SCENARIOS:
            result = simulate_exit(ep, peak, xp, sc)
            sim_pnl = result["simulated_return"] * ep * qty
            scenario_totals[sc.name] += sim_pnl
            if sim_pnl > 0:
                scenario_wins[sc.name] += 1

    print(f"Walk-forward exit analysis: {len(closed)} closed trades\n")
    print(f"{'Scenario':<18} {'Simulated PnL':>14} {'Win Count':>10} {'Δ vs current':>14}")
    print("-" * 60)
    baseline = scenario_totals["current"]
    for sc in SCENARIOS:
        total = scenario_totals[sc.name]
        wins = scenario_wins[sc.name]
        delta = total - baseline
        marker = " ← best" if sc.name != "current" and total > max(
            v for k, v in scenario_totals.items() if k != sc.name
        ) else ""
        print(f"  {sc.name:<16} ${total:>13,.2f} {wins:>10}  {delta:>+13,.2f}{marker}")

    best = max(scenario_totals, key=lambda k: scenario_totals[k])
    print(f"\nBest scenario: {best} (${scenario_totals[best]:,.2f})")

    out = PROJECT_ROOT / "data" / "analysis" / "walkforward_exit_analysis.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "trades_analysed": len(closed),
                "scenarios": {
                    sc.name: {
                        "total_pnl": round(scenario_totals[sc.name], 2),
                        "win_count": scenario_wins[sc.name],
                        "delta_vs_current": round(scenario_totals[sc.name] - baseline, 2),
                    }
                    for sc in SCENARIOS
                },
                "best_scenario": best,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nSaved to: {out}")


if __name__ == "__main__":
    main()
