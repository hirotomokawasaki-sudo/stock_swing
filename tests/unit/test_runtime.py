from pathlib import Path

import pytest

from stock_swing.core.runtime import read_runtime_mode


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
