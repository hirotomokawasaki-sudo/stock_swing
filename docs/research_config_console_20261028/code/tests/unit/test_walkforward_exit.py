"""Tests for P4-A: walk-forward exit analysis."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))


def test_simulate_exit_stop_loss() -> None:
    from walkforward_exit_analysis import ExitScenario, simulate_exit

    sc = ExitScenario("test", stop_loss_pct=-0.07, trailing_activation_pct=0.08, trailing_stop_pct=0.04)
    result = simulate_exit(entry_price=100.0, peak_price=101.0, exit_price=92.0, scenario=sc)
    assert result["exit_trigger"] == "stop_loss"
    assert result["simulated_return"] == pytest.approx(-0.07)


def test_simulate_exit_trailing_stop() -> None:
    from walkforward_exit_analysis import ExitScenario, simulate_exit

    sc = ExitScenario("test", stop_loss_pct=-0.07, trailing_activation_pct=0.08, trailing_stop_pct=0.04)
    result = simulate_exit(entry_price=100.0, peak_price=112.0, exit_price=106.0, scenario=sc)
    assert result["exit_trigger"] == "trailing_stop"
    assert result["simulated_return"] == pytest.approx((112.0 * 0.96 - 100.0) / 100.0, abs=0.001)


def test_simulate_exit_holds_to_actual_when_no_trigger() -> None:
    from walkforward_exit_analysis import ExitScenario, simulate_exit

    sc = ExitScenario("test", stop_loss_pct=-0.07, trailing_activation_pct=0.08, trailing_stop_pct=0.04)
    result = simulate_exit(entry_price=100.0, peak_price=103.0, exit_price=105.0, scenario=sc)
    assert result["exit_trigger"] == "held_to_actual"
    assert result["simulated_return"] == pytest.approx(0.05)
