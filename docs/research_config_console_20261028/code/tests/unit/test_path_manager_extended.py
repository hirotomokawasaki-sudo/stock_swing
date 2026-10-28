"""Extended tests for PathManager including failure cases."""

from pathlib import Path

import pytest

from stock_swing.core.path_manager import PathManager


def test_data_stage_valid_stages(tmp_path: Path) -> None:
    """Test that all valid data stages are accepted."""
    pm = PathManager(tmp_path)
    valid_stages = {"raw", "normalized", "features", "signals", "decisions", "audits", "archive"}

    for stage in valid_stages:
        path = pm.data_stage(stage)
        assert path.name == stage
        assert path.parent.name == "data"
        assert path.exists()


def test_data_stage_invalid_fails_closed(tmp_path: Path) -> None:
    """Test that invalid data stage raises ValueError (fail closed)."""
    pm = PathManager(tmp_path)

    with pytest.raises(ValueError, match="unsupported data stage"):
        pm.data_stage("invalid_stage")


def test_source_raw_creates_source_subdirectory(tmp_path: Path) -> None:
    """Test that source_raw creates source-specific subdirectories under raw."""
    pm = PathManager(tmp_path)
    path = pm.source_raw("finnhub")

    assert path.name == "finnhub"
    assert path.parent.name == "raw"
    assert path.exists()


def test_config_file_path_resolution(tmp_path: Path) -> None:
    """Test that config_file resolves paths correctly relative to project root."""
    pm = PathManager(tmp_path)
    path = pm.config_file("runtime", "current_mode.yaml")

    assert path == tmp_path / "config" / "runtime" / "current_mode.yaml"


def test_project_root_is_resolved(tmp_path: Path) -> None:
    """Test that project_root is resolved to absolute path."""
    pm = PathManager(tmp_path / "." / ".")
    assert pm.project_root.is_absolute()
    assert pm.project_root == tmp_path.resolve()
