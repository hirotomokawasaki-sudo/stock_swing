"""Tests for rsi_diagnostic.py (Plan E, 2026-08-08 R10 follow-up #2).

Observability-only diagnostic: classify_rsi_overbought() must never block
or raise, and fetch_latest_rsi() must tolerate any client/data failure by
returning None rather than propagating an exception.
"""
from __future__ import annotations

import json
from datetime import datetime

from stock_swing.risk.rsi_diagnostic import (
    RsiDiagnosticConfig,
    classify_rsi_overbought,
    fetch_latest_rsi,
    log_shadow,
)


# ── classify_rsi_overbought ────────────────────────────────────────────────── #

def test_overbought_rsi_flagged():
    result = classify_rsi_overbought("NVDA", 82.5)
    assert result.is_overbought is True
    assert result.rsi_value == 82.5
    assert "overbought" in result.reason


def test_neutral_rsi_not_flagged():
    result = classify_rsi_overbought("AAPL", 55.0)
    assert result.is_overbought is False
    assert "not_flagged" in result.reason


def test_oversold_rsi_not_flagged():
    result = classify_rsi_overbought("XYZ", 20.0)
    assert result.is_overbought is False


# ── Boundary values ──────────────────────────────────────────────────────── #

def test_boundary_exactly_at_threshold_flags():
    cfg = RsiDiagnosticConfig(overbought_threshold=75.0)
    result = classify_rsi_overbought("AAA", 75.0, config=cfg)
    assert result.is_overbought is True  # inclusive boundary (>=)


def test_boundary_just_below_threshold_not_flagged():
    cfg = RsiDiagnosticConfig(overbought_threshold=75.0)
    result = classify_rsi_overbought("BBB", 74.9, config=cfg)
    assert result.is_overbought is False


# ── Missing / malformed data fallback (never raises, never flags) ────────── #

def test_none_rsi_value_not_flagged():
    result = classify_rsi_overbought("NVDA", None)
    assert result.is_overbought is False
    assert "no_data" in result.reason
    assert result.rsi_value is None


def test_disabled_config_never_flags():
    cfg = RsiDiagnosticConfig(disabled=True)
    result = classify_rsi_overbought("NVDA", 95.0, config=cfg)
    assert result.is_overbought is False
    assert result.reason == "disabled"
    assert result.rsi_value is None


def test_config_from_env_defaults(monkeypatch):
    monkeypatch.delenv("RSI_DIAGNOSTIC_WINDOW", raising=False)
    monkeypatch.delenv("RSI_DIAGNOSTIC_OVERBOUGHT_THRESHOLD", raising=False)
    monkeypatch.delenv("RSI_DIAGNOSTIC_DISABLED", raising=False)
    cfg = RsiDiagnosticConfig.from_env()
    assert cfg.window == 14
    assert cfg.overbought_threshold == 75.0
    assert cfg.disabled is False


def test_config_from_env_overrides(monkeypatch):
    monkeypatch.setenv("RSI_DIAGNOSTIC_WINDOW", "21")
    monkeypatch.setenv("RSI_DIAGNOSTIC_OVERBOUGHT_THRESHOLD", "80")
    monkeypatch.setenv("RSI_DIAGNOSTIC_DISABLED", "true")
    cfg = RsiDiagnosticConfig.from_env()
    assert cfg.window == 21
    assert cfg.overbought_threshold == 80.0
    assert cfg.disabled is True


# ── fetch_latest_rsi: never raises, tolerates client/data errors ─────────── #

class _FakeMassiveClient:
    def __init__(self, rows=None, raise_exc=None):
        self._rows = rows
        self._raise_exc = raise_exc

    def fetch_rsi(self, symbol, window=14):
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._rows


def test_fetch_latest_rsi_returns_latest_by_timestamp():
    rows = [
        {"timestamp": datetime(2026, 8, 1), "value": 60.0},
        {"timestamp": datetime(2026, 8, 5), "value": 82.3},
        {"timestamp": datetime(2026, 8, 3), "value": 70.0},
    ]
    client = _FakeMassiveClient(rows=rows)
    value = fetch_latest_rsi("NVDA", client)
    assert value == 82.3


def test_fetch_latest_rsi_empty_rows_returns_none():
    client = _FakeMassiveClient(rows=[])
    value = fetch_latest_rsi("NVDA", client)
    assert value is None


def test_fetch_latest_rsi_none_rows_returns_none():
    client = _FakeMassiveClient(rows=None)
    value = fetch_latest_rsi("NVDA", client)
    assert value is None


def test_fetch_latest_rsi_client_exception_returns_none():
    client = _FakeMassiveClient(raise_exc=ConnectionError("boom"))
    value = fetch_latest_rsi("NVDA", client)
    assert value is None


def test_fetch_latest_rsi_missing_value_field_returns_none():
    rows = [{"timestamp": datetime(2026, 8, 1)}]
    client = _FakeMassiveClient(rows=rows)
    value = fetch_latest_rsi("NVDA", client)
    assert value is None


def test_fetch_latest_rsi_unparseable_value_returns_none():
    rows = [{"timestamp": datetime(2026, 8, 1), "value": "not_a_number"}]
    client = _FakeMassiveClient(rows=rows)
    value = fetch_latest_rsi("NVDA", client)
    assert value is None


def test_fetch_latest_rsi_passes_window_through():
    seen = {}

    class _WindowCheckClient:
        def fetch_rsi(self, symbol, window=14):
            seen["window"] = window
            return [{"timestamp": datetime(2026, 8, 1), "value": 50.0}]

    fetch_latest_rsi("NVDA", _WindowCheckClient(), window=21)
    assert seen["window"] == 21


# ── log_shadow: never raises, writes JSONL always ─────────────────────────── #

def test_log_shadow_writes_jsonl_for_overbought(tmp_path):
    log_path = tmp_path / "rsi_diagnostic_shadow_log.jsonl"
    result = classify_rsi_overbought("NVDA", 90.0)
    log_shadow(result, shadow_log_path=log_path)

    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["symbol"] == "NVDA"
    assert record["is_overbought"] is True


def test_log_shadow_without_path_does_not_raise():
    result = classify_rsi_overbought("NVDA", 90.0)
    log_shadow(result, shadow_log_path=None)  # must not raise


def test_log_shadow_still_writes_non_overbought_to_file(tmp_path):
    """Even non-flagged results should be recorded for later threshold
    calibration, even though no INFO line is emitted for them."""
    log_path = tmp_path / "rsi_diagnostic_shadow_log.jsonl"
    result = classify_rsi_overbought("AAPL", 50.0)
    assert result.is_overbought is False
    log_shadow(result, shadow_log_path=log_path)
    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
