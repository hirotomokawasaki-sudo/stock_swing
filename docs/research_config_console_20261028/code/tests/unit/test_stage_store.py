"""Tests for StageStore - stage-aware storage with path safety and raw immutability."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest

from stock_swing.core.path_manager import PathManager
from stock_swing.storage.stage_store import RawOverwriteError, StageStore


@dataclass
class SampleData:
    """Sample dataclass for testing."""

    id: str
    timestamp: datetime
    value: float


def test_write_raw_creates_source_subdirectory(tmp_path: Path) -> None:
    """Test that write_raw creates source-specific subdirectories under raw."""
    pm = PathManager(tmp_path)
    store = StageStore(pm)

    data = {"symbol": "AAPL", "value": 100}
    result = store.write_raw("finnhub", "test.json", data)

    assert result.exists()
    assert result.parent.name == "finnhub"
    assert result.parent.parent.name == "raw"


def test_write_raw_fails_on_overwrite_by_default(tmp_path: Path) -> None:
    """Test that write_raw raises RawOverwriteError when file exists (immutability)."""
    pm = PathManager(tmp_path)
    store = StageStore(pm)

    data = {"symbol": "AAPL", "value": 100}
    store.write_raw("finnhub", "test.json", data)

    # Attempt to overwrite should fail
    with pytest.raises(RawOverwriteError, match="raw file already exists"):
        store.write_raw("finnhub", "test.json", data)


def test_write_raw_allows_overwrite_when_configured(tmp_path: Path) -> None:
    """Test that write_raw allows overwrite when allow_raw_overwrite=True."""
    pm = PathManager(tmp_path)
    store = StageStore(pm, allow_raw_overwrite=True)

    data1 = {"symbol": "AAPL", "value": 100}
    data2 = {"symbol": "AAPL", "value": 200}

    path1 = store.write_raw("finnhub", "test.json", data1)
    path2 = store.write_raw("finnhub", "test.json", data2)

    assert path1 == path2
    assert path2.exists()


def test_write_normalized_to_correct_stage(tmp_path: Path) -> None:
    """Test that write_normalized writes to data/normalized/."""
    pm = PathManager(tmp_path)
    store = StageStore(pm)

    data = {"record_id": "123", "symbol": "AAPL"}
    result = store.write_normalized("canonical_test.json", data)

    assert result.exists()
    assert result.parent.name == "normalized"
    assert result.parent.parent.name == "data"


def test_write_features_to_correct_stage(tmp_path: Path) -> None:
    """Test that write_features writes to data/features/."""
    pm = PathManager(tmp_path)
    store = StageStore(pm)

    data = {"symbol": "AAPL", "momentum": 0.75}
    result = store.write_features("features_test.json", data)

    assert result.exists()
    assert result.parent.name == "features"


def test_write_signals_to_correct_stage(tmp_path: Path) -> None:
    """Test that write_signals writes to data/signals/."""
    pm = PathManager(tmp_path)
    store = StageStore(pm)

    data = {"symbol": "AAPL", "signal": "buy", "strength": 0.8}
    result = store.write_signals("signal_test.json", data)

    assert result.exists()
    assert result.parent.name == "signals"


def test_write_decisions_to_correct_stage(tmp_path: Path) -> None:
    """Test that write_decisions writes to data/decisions/."""
    pm = PathManager(tmp_path)
    store = StageStore(pm)

    data = {"decision_id": "456", "action": "buy"}
    result = store.write_decisions("decision_test.json", data)

    assert result.exists()
    assert result.parent.name == "decisions"


def test_write_audit_to_correct_stage(tmp_path: Path) -> None:
    """Test that write_audit writes to data/audits/."""
    pm = PathManager(tmp_path)
    store = StageStore(pm)

    data = {"event": "execution", "status": "success"}
    result = store.write_audit("audit_test.json", data)

    assert result.exists()
    assert result.parent.name == "audits"


def test_write_dataclass_with_datetime(tmp_path: Path) -> None:
    """Test that dataclasses with datetime fields are serialized correctly."""
    pm = PathManager(tmp_path)
    store = StageStore(pm)

    now = datetime(2026, 3, 6, 14, 30, 0)
    data = SampleData(id="test", timestamp=now, value=123.45)

    result = store.write_normalized("dataclass_test.json", data)
    assert result.exists()

    # Verify content
    import json

    content = json.loads(result.read_text())
    assert content["id"] == "test"
    assert content["timestamp"] == "2026-03-06T14:30:00"
    assert content["value"] == 123.45


def test_stage_separation_enforced(tmp_path: Path) -> None:
    """Test that different stages write to different directories."""
    pm = PathManager(tmp_path)
    store = StageStore(pm)

    data = {"test": "data"}

    raw_path = store.write_raw("test_source", "file.json", data)
    normalized_path = store.write_normalized("file.json", data)
    features_path = store.write_features("file.json", data)
    signals_path = store.write_signals("file.json", data)
    decisions_path = store.write_decisions("file.json", data)
    audits_path = store.write_audit("file.json", data)

    # All files should exist in different directories
    assert raw_path.parent.name == "test_source"
    assert normalized_path.parent.name == "normalized"
    assert features_path.parent.name == "features"
    assert signals_path.parent.name == "signals"
    assert decisions_path.parent.name == "decisions"
    assert audits_path.parent.name == "audits"

    # Verify no cross-stage contamination
    unique_parents = {
        raw_path.parent.parent,
        normalized_path.parent,
        features_path.parent,
        signals_path.parent,
        decisions_path.parent,
        audits_path.parent,
    }
    assert len(unique_parents) == 6  # All different
