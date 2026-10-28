"""Integration tests for R0, R1-A, R2-C changes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import importlib
import logging

import pytest

from stock_swing.feature_engine.base_feature import FeatureResult


def test_guardrail_warning_only_allows_all(tmp_path: Path) -> None:
    from stock_swing.guardrails.rule_engine import GuardAction, GuardrailEngine, GuardrailRule

    engine = GuardrailEngine(
        rules=[GuardrailRule("loss", "daily_loss", "<=", -2, GuardAction.halt)],
        warning_only=True,
    )
    decision = engine.evaluate({"daily_loss": -99})
    assert decision.action == GuardAction.allow
    assert len(decision.triggered) == 1


def test_guardrail_warning_only_false_enforces_halt(tmp_path: Path) -> None:
    from stock_swing.guardrails.rule_engine import GuardAction, GuardrailEngine, GuardrailRule

    engine = GuardrailEngine(
        rules=[GuardrailRule("loss", "daily_loss", "<=", -2, GuardAction.halt)],
        warning_only=False,
    )
    decision = engine.evaluate({"daily_loss": -99})
    assert decision.action == GuardAction.halt


def test_experiment_context_builds(tmp_path: Path) -> None:
    from stock_swing.experiments import ExperimentRegistry, build_experiment_context

    ctx = build_experiment_context(
        repo_root=tmp_path,
        run_id="run-test-r0",
        strategy_version="swing-v1",
        prompt_version="prompt-v1",
        feature_schema_version="features-v1",
        config_payload={"mode": "paper"},
        mode="paper",
    )
    assert ctx.experiment_id.startswith("exp-")
    reg = ExperimentRegistry(tmp_path / "experiments")
    exp_dir = reg.register(ctx)
    assert (exp_dir / "manifest.json").exists()


def test_stock_multiplier_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STOCK_POSITION_SIZE_MULTIPLIER", "0.5")
    import stock_swing.risk.position_sizing as ps

    importlib.reload(ps)
    assert ps.STOCK_POSITION_SIZE_MULTIPLIER == pytest.approx(0.5, abs=0.01)

    monkeypatch.setenv("STOCK_POSITION_SIZE_MULTIPLIER", "1.0")
    importlib.reload(ps)
    assert ps.STOCK_POSITION_SIZE_MULTIPLIER == pytest.approx(1.0, abs=0.01)


def test_exit_signal_fires_and_logs(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    from stock_swing.strategy_engine.simple_exit_v2_strategy import SimpleExitV2Strategy

    strategy = SimpleExitV2Strategy(stop_loss_pct=-0.07)
    positions = {
        "KLAC": {
            "symbol": "KLAC",
            "qty": 10,
            "avg_entry_price": 100.0,
            "current_price": 88.0,
            "peak_price": 100.0,
            "entry_time": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            "entry_signal_strength": 0.7,
        }
    }
    features = [
        FeatureResult(
            feature_name="price_momentum",
            symbol="KLAC",
            computed_at=datetime.now(timezone.utc),
            values={"latest_close": 88.0},
        )
    ]

    with caplog.at_level(logging.INFO, logger="stock_swing.strategy_engine.simple_exit_v2_strategy"):
        signals = strategy.generate(features, positions)

    sell_signals = [s for s in signals if getattr(s, "action", "") == "sell"]
    assert len(sell_signals) == 1, f"Expected 1 sell signal, got {signals}"
    assert any("exit_signal_fired" in r.message for r in caplog.records), (
        f"exit_signal_fired log not found. Records: {[r.message for r in caplog.records]}"
    )
