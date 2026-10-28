"""Tests for volatility_gate.py (Plan B, 2026-08-07 NBIS incident follow-up).

Shadow-mode diagnostic: classify_buy_volatility() must never raise on
missing/malformed data, and would_block() must correctly reflect mode
(active vs shadow/paper_ab), matching the sector_shock_hold.py rollout
pattern (shadow logs only; active would actually gate).
"""
from __future__ import annotations

import json

from stock_swing.risk.volatility_gate import (
    VolatilityGateConfig,
    classify_buy_volatility,
    log_shadow,
)


def test_config_defaults():
    cfg = VolatilityGateConfig()
    assert cfg.mode == "shadow"
    assert cfg.max_3m_return_std_pct == 120.0
    assert cfg.is_enabled() is True
    assert cfg.would_block() is False  # shadow mode never blocks


def test_config_active_mode_would_block():
    cfg = VolatilityGateConfig(mode="active")
    assert cfg.would_block() is True


def test_config_disabled_mode_not_enabled():
    cfg = VolatilityGateConfig(mode="disabled")
    assert cfg.is_enabled() is False
    assert cfg.would_block() is False


def test_config_from_env_defaults(monkeypatch):
    monkeypatch.delenv("VOLATILITY_GATE_MODE", raising=False)
    monkeypatch.delenv("VOLATILITY_GATE_MAX_3M_STD_PCT", raising=False)
    cfg = VolatilityGateConfig.from_env()
    assert cfg.mode == "shadow"
    assert cfg.max_3m_return_std_pct == 120.0


def test_config_from_env_overrides(monkeypatch):
    monkeypatch.setenv("VOLATILITY_GATE_MODE", "active")
    monkeypatch.setenv("VOLATILITY_GATE_MAX_3M_STD_PCT", "100")
    cfg = VolatilityGateConfig.from_env()
    assert cfg.mode == "active"
    assert cfg.max_3m_return_std_pct == 100.0


# ── classify_buy_volatility: normal path ─────────────────────────────────── #

def test_symbol_over_cap_flagged_would_block():
    result = classify_buy_volatility(
        "NBIS", {"3MonthADReturnStd": 132.56}, VolatilityGateConfig(max_3m_return_std_pct=120.0)
    )
    assert result.would_block is True
    assert result.return_std_3m_pct == 132.56
    assert "volatility_gate" in result.reason


def test_symbol_under_cap_not_flagged():
    result = classify_buy_volatility(
        "GOOGL", {"3MonthADReturnStd": 37.74}, VolatilityGateConfig(max_3m_return_std_pct=120.0)
    )
    assert result.would_block is False
    assert result.return_std_3m_pct == 37.74


def test_symbol_exactly_at_cap_not_flagged():
    """Boundary: exactly at the cap must not block (strict >)."""
    result = classify_buy_volatility(
        "TEST", {"3MonthADReturnStd": 120.0}, VolatilityGateConfig(max_3m_return_std_pct=120.0)
    )
    assert result.would_block is False


def test_symbol_just_over_cap_flagged():
    result = classify_buy_volatility(
        "TEST", {"3MonthADReturnStd": 120.01}, VolatilityGateConfig(max_3m_return_std_pct=120.0)
    )
    assert result.would_block is True


# ── Missing / malformed data fallback (must never raise, never block) ───── #

def test_none_metric_payload_does_not_block():
    result = classify_buy_volatility("NBIS", None)
    assert result.would_block is False
    assert "no_metric_data" in result.reason


def test_missing_3m_std_field_does_not_block():
    result = classify_buy_volatility("NBIS", {"beta": 1.05})
    assert result.would_block is False
    assert "missing_3m_std" in result.reason


def test_invalid_3m_std_value_does_not_raise_or_block():
    result = classify_buy_volatility("NBIS", {"3MonthADReturnStd": "not-a-number"})
    assert result.would_block is False
    assert "invalid_3m_std" in result.reason


def test_none_3m_std_value_does_not_block():
    result = classify_buy_volatility("NBIS", {"3MonthADReturnStd": None})
    assert result.would_block is False


# ── mode is carried through to the result ────────────────────────────────── #

def test_result_carries_config_mode():
    cfg = VolatilityGateConfig(mode="paper_ab", max_3m_return_std_pct=120.0)
    result = classify_buy_volatility("NBIS", {"3MonthADReturnStd": 132.56}, cfg)
    assert result.mode == "paper_ab"
    # would_block reflects the RULE outcome, not whether mode enforces it.
    assert result.would_block is True
    assert cfg.would_block() is False  # paper_ab does not actually gate


# ── log_shadow: never raises, writes JSONL when path given ──────────────── #

def test_log_shadow_writes_jsonl_record(tmp_path):
    log_path = tmp_path / "volatility_shadow_log.jsonl"
    result = classify_buy_volatility(
        "NBIS", {"3MonthADReturnStd": 132.56}, VolatilityGateConfig(max_3m_return_std_pct=120.0)
    )
    log_shadow(result, shadow_log_path=log_path)

    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["symbol"] == "NBIS"
    assert record["would_block"] is True
    assert record["return_std_3m_pct"] == 132.56


def test_log_shadow_appends_multiple_records(tmp_path):
    log_path = tmp_path / "volatility_shadow_log.jsonl"
    for sym, std in [("NBIS", 132.56), ("GOOGL", 37.74)]:
        result = classify_buy_volatility(sym, {"3MonthADReturnStd": std})
        log_shadow(result, shadow_log_path=log_path)

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_log_shadow_without_path_does_not_raise():
    result = classify_buy_volatility("NBIS", {"3MonthADReturnStd": 132.56})
    log_shadow(result, shadow_log_path=None)  # must not raise


def test_log_shadow_creates_parent_dirs(tmp_path):
    log_path = tmp_path / "nested" / "dir" / "volatility_shadow_log.jsonl"
    result = classify_buy_volatility("NBIS", {"3MonthADReturnStd": 132.56})
    log_shadow(result, shadow_log_path=log_path)
    assert log_path.exists()
