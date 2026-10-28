"""Tests for runtime mode reading and validation (fail-closed behavior)."""

from pathlib import Path

import pytest

from stock_swing.core.runtime import (
    ALLOWED_RUNTIME_MODES,
    RuntimeModeError,
    read_runtime_mode,
)


def test_read_runtime_mode_valid(tmp_path: Path) -> None:
    """Test reading a valid runtime mode."""
    config_file = tmp_path / "config" / "runtime" / "current_mode.yaml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("mode: research\n")

    result = read_runtime_mode(tmp_path)
    assert result == "research"


def test_read_runtime_mode_paper(tmp_path: Path) -> None:
    """Test reading paper mode."""
    config_file = tmp_path / "config" / "runtime" / "current_mode.yaml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("mode: paper\n")

    result = read_runtime_mode(tmp_path)
    assert result == "paper"


def test_read_runtime_mode_invalid_fails_closed(tmp_path: Path) -> None:
    """Test that invalid runtime mode fails closed with RuntimeModeError."""
    config_file = tmp_path / "config" / "runtime" / "current_mode.yaml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("mode: invalid_mode\n")

    with pytest.raises(RuntimeModeError, match="invalid or missing runtime mode"):
        read_runtime_mode(tmp_path)


def test_read_runtime_mode_missing_fails_closed(tmp_path: Path) -> None:
    """Test that missing mode key fails closed with RuntimeModeError."""
    config_file = tmp_path / "config" / "runtime" / "current_mode.yaml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("other_key: value\n")

    with pytest.raises(RuntimeModeError, match="invalid or missing runtime mode"):
        read_runtime_mode(tmp_path)


def test_read_runtime_mode_missing_file_fails_closed(tmp_path: Path) -> None:
    """Test that missing config file fails closed."""
    # No config file created
    with pytest.raises(FileNotFoundError):
        read_runtime_mode(tmp_path)


def test_allowed_runtime_modes() -> None:
    """Test that ALLOWED_RUNTIME_MODES matches documented modes."""
    expected = {"research", "paper", "live_guarded", "live"}
    assert ALLOWED_RUNTIME_MODES == expected
