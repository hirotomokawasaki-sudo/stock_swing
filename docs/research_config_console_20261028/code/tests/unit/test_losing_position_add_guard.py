"""Regression tests for CIEN-style losing-position pyramiding."""
from __future__ import annotations

import json
from types import SimpleNamespace

from stock_swing.risk.losing_position_add_guard import (
    LosingPositionAddGuardConfig,
    evaluate_losing_position_adds,
    log_losing_position_add_shadow,
)


def _buy(symbol: str = "CIEN") -> SimpleNamespace:
    return SimpleNamespace(action="buy", symbol=symbol, decision_id="decision-1")


def test_1013_cien_add_would_be_blocked_while_existing_lot_down_10pct():
    observations = evaluate_losing_position_adds(
        [_buy()],
        {"CIEN": {"qty": "120", "unrealized_plpc": "-0.10"}},
        config=LosingPositionAddGuardConfig(),
    )
    assert len(observations) == 1
    assert observations[0].would_block
    assert observations[0].data_valid


def test_small_existing_loss_does_not_block():
    observations = evaluate_losing_position_adds(
        [_buy()],
        {"CIEN": {"qty": "120", "unrealized_plpc": "-0.02"}},
        config=LosingPositionAddGuardConfig(),
    )
    assert not observations[0].would_block


def test_new_symbol_buy_is_not_an_add_evaluation():
    observations = evaluate_losing_position_adds(
        [_buy("AMAT")],
        {"CIEN": {"qty": "120", "unrealized_plpc": "-0.10"}},
        config=LosingPositionAddGuardConfig(),
    )
    assert observations == []


def test_missing_existing_return_is_fail_closed_shadow():
    observations = evaluate_losing_position_adds(
        [_buy()],
        {"CIEN": {"qty": "120"}},
        config=LosingPositionAddGuardConfig(),
    )
    assert observations[0].would_block
    assert not observations[0].data_valid


def test_invalid_threshold_uses_default(monkeypatch):
    monkeypatch.setenv("LOSING_POSITION_ADD_GUARD_MAX_LOSS_PCT", "1.0")
    assert LosingPositionAddGuardConfig.from_env().max_existing_loss_pct == -0.03


def test_shadow_log_is_structured_jsonl(tmp_path):
    observation = evaluate_losing_position_adds(
        [_buy()],
        {"CIEN": {"qty": "120", "unrealized_plpc": "-0.10"}},
        config=LosingPositionAddGuardConfig(),
    )[0]
    path = tmp_path / "adds.jsonl"
    log_losing_position_add_shadow(observation, shadow_log_path=path, run_id="run-1")
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["symbol"] == "CIEN"
    assert record["would_block"] is True
