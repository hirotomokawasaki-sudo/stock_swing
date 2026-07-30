from pathlib import Path

import pytest

from stock_swing.core.runtime import (
    read_circuit_breaker_config,
    read_ledger_quality_gate,
    read_runtime_mode,
)


def test_read_runtime_mode_paper(tmp_path: Path) -> None:
    """read_runtime_mode returns the mode written in current_mode.yaml."""
    (tmp_path / "config" / "runtime").mkdir(parents=True)
    (tmp_path / "config" / "runtime" / "current_mode.yaml").write_text("mode: paper\n")
    assert read_runtime_mode(tmp_path) == "paper"


def test_read_runtime_mode_research(tmp_path: Path) -> None:
    """read_runtime_mode returns research when set to research."""
    (tmp_path / "config" / "runtime").mkdir(parents=True)
    (tmp_path / "config" / "runtime" / "current_mode.yaml").write_text("mode: research\n")
    assert read_runtime_mode(tmp_path) == "research"


def test_read_runtime_mode_missing_raises(tmp_path: Path) -> None:
    """read_runtime_mode raises when config file is absent."""
    from stock_swing.core.runtime import RuntimeModeError
    with pytest.raises((FileNotFoundError, RuntimeModeError)):
        read_runtime_mode(tmp_path)


def _write_mode_yaml(tmp_path: Path, content: str) -> None:
    p = tmp_path / "config" / "runtime"
    p.mkdir(parents=True, exist_ok=True)
    (p / "current_mode.yaml").write_text(content, encoding="utf-8")


# ── R0-v2-A: read_ledger_quality_gate ──────────────────────────────── #

def test_read_ledger_quality_gate_returns_correct_status(tmp_path: Path) -> None:
    _write_mode_yaml(tmp_path, """
mode: paper
ledger_quality_gate:
  current_status: INVALID
  enforce_invalid_ledger_blocks_live_ready: true
""")
    gate = read_ledger_quality_gate(tmp_path)
    assert gate["current_status"] == "INVALID"
    assert gate["enforce_invalid_ledger_blocks_live_ready"] is True


def test_read_ledger_quality_gate_valid_status(tmp_path: Path) -> None:
    _write_mode_yaml(tmp_path, """
mode: paper
ledger_quality_gate:
  current_status: VALID
  enforce_invalid_ledger_blocks_live_ready: true
""")
    gate = read_ledger_quality_gate(tmp_path)
    assert gate["current_status"] == "VALID"


def test_read_ledger_quality_gate_missing_key_returns_fallback(tmp_path: Path) -> None:
    """YAML exists but has no ledger_quality_gate key → safe fallback."""
    _write_mode_yaml(tmp_path, "mode: paper\n")
    gate = read_ledger_quality_gate(tmp_path)
    assert gate["current_status"] == "UNKNOWN"
    assert gate["enforce_invalid_ledger_blocks_live_ready"] is True


def test_read_ledger_quality_gate_missing_file_returns_fallback(tmp_path: Path) -> None:
    """Config file absent → safe fallback (never raises)."""
    gate = read_ledger_quality_gate(tmp_path)
    assert gate["current_status"] == "UNKNOWN"
    assert gate["enforce_invalid_ledger_blocks_live_ready"] is True


def test_read_ledger_quality_gate_corrupted_yaml_returns_fallback(tmp_path: Path) -> None:
    """Corrupted YAML → safe fallback (never raises)."""
    p = tmp_path / "config" / "runtime"
    p.mkdir(parents=True, exist_ok=True)
    (p / "current_mode.yaml").write_text("{{{{invalid yaml{{{{", encoding="utf-8")
    gate = read_ledger_quality_gate(tmp_path)
    assert gate["current_status"] == "UNKNOWN"


# ── R0-v2-A: read_circuit_breaker_config ───────────────────────────── #

def test_read_circuit_breaker_config_returns_require_flag(tmp_path: Path) -> None:
    _write_mode_yaml(tmp_path, """
mode: paper
circuit_breaker:
  require_clean_run_after_manual_clear: true
""")
    cfg = read_circuit_breaker_config(tmp_path)
    assert cfg["require_clean_run_after_manual_clear"] is True


def test_read_circuit_breaker_config_false(tmp_path: Path) -> None:
    _write_mode_yaml(tmp_path, """
mode: paper
circuit_breaker:
  require_clean_run_after_manual_clear: false
""")
    cfg = read_circuit_breaker_config(tmp_path)
    assert cfg["require_clean_run_after_manual_clear"] is False


def test_read_circuit_breaker_config_missing_key_returns_safe_default(tmp_path: Path) -> None:
    """No circuit_breaker key → fail-closed default (require=True)."""
    _write_mode_yaml(tmp_path, "mode: paper\n")
    cfg = read_circuit_breaker_config(tmp_path)
    assert cfg["require_clean_run_after_manual_clear"] is True


def test_read_circuit_breaker_config_missing_file_returns_safe_default(tmp_path: Path) -> None:
    cfg = read_circuit_breaker_config(tmp_path)
    assert cfg["require_clean_run_after_manual_clear"] is True
