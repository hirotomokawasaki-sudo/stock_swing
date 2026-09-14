import json

import pytest

from scripts.check_high_correlation_snapshot import read_observation


def _write_snapshot(root, name, pair_gate):
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(
        json.dumps(
            {
                "captured_at": "2026-09-14T00:30:03+00:00",
                "promotion": {"pairwise_correlation": pair_gate},
            }
        ),
        encoding="utf-8",
    )


def test_reads_latest_alert_and_stable_signature(tmp_path):
    _write_snapshot(
        tmp_path,
        "snapshot_20260913_003002.json",
        {"pass": True, "actual": []},
    )
    _write_snapshot(
        tmp_path,
        "snapshot_20260914_003003.json",
        {"pass": False, "actual": ["HPE/DELL=0.8835", "A/B=-0.82"], "detail": "checked"},
    )
    result = read_observation(tmp_path)
    assert result["status"] == "alert"
    assert result["pairs"] == ["A/B=-0.82", "HPE/DELL=0.8835"]
    assert result["signature"] == "A/B=-0.82|HPE/DELL=0.8835"
    assert result["snapshot"] == "snapshot_20260914_003003.json"


def test_clear_state(tmp_path):
    _write_snapshot(tmp_path, "snapshot_20260914_003003.json", {"pass": True, "actual": []})
    assert read_observation(tmp_path)["status"] == "clear"


def test_missing_snapshot_fails_closed(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_observation(tmp_path)


def test_missing_verdict_fails_closed(tmp_path):
    _write_snapshot(tmp_path, "snapshot_20260914_003003.json", {})
    with pytest.raises(ValueError):
        read_observation(tmp_path)
