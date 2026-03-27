"""Tests for ConfigLoader."""

from pathlib import Path

import pytest

from stock_swing.core.config_loader import ConfigLoader


def test_load_yaml_success(tmp_path: Path) -> None:
    """Test successful YAML loading."""
    config_file = tmp_path / "config" / "test.yaml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("key: value\n")

    loader = ConfigLoader(tmp_path)
    result = loader.load_yaml("config/test.yaml")

    assert result == {"key": "value"}


def test_load_yaml_missing_file(tmp_path: Path) -> None:
    """Test that loading a missing file raises FileNotFoundError."""
    loader = ConfigLoader(tmp_path)
    with pytest.raises(FileNotFoundError):
        loader.load_yaml("config/missing.yaml")


def test_load_yaml_invalid_mapping(tmp_path: Path) -> None:
    """Test that non-dict YAML raises ValueError."""
    config_file = tmp_path / "config" / "bad.yaml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("- item1\n- item2\n")  # List, not dict

    loader = ConfigLoader(tmp_path)
    with pytest.raises(ValueError, match="expected mapping"):
        loader.load_yaml("config/bad.yaml")


def test_load_yaml_empty_file(tmp_path: Path) -> None:
    """Test that empty YAML returns empty dict."""
    config_file = tmp_path / "config" / "empty.yaml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("")

    loader = ConfigLoader(tmp_path)
    result = loader.load_yaml("config/empty.yaml")

    assert result == {}
