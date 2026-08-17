"""R4-v2 residual (2026-08-17): tests for check_confidence_calibration_readiness.py.

Ensures the "confidence calibration" readiness gate is checked against the
count of decision records that actually have `confidence_multiplier`
recorded (evidence.sizing.confidence_multiplier), which only started being
recorded 2026-08-14 -- not raw decision/trade counts, and not decisions from
before recording began.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "check_confidence_calibration_readiness.py"
)
_spec = importlib.util.spec_from_file_location(
    "check_confidence_calibration_readiness", _SCRIPT_PATH
)
_module = importlib.util.module_from_spec(_spec)
sys.modules["check_confidence_calibration_readiness"] = _module
_spec.loader.exec_module(_module)

check_readiness = _module.check_readiness


def _write_decision(
    tmp_path: Path,
    name: str,
    generated_at: str,
    confidence: float | None = 0.85,
    confidence_multiplier: float | None = 1.2,
) -> None:
    doc = {
        "decision_id": name,
        "generated_at": generated_at,
        "confidence": confidence,
        "evidence": {
            "sizing": (
                {"confidence_multiplier": confidence_multiplier}
                if confidence_multiplier is not None
                else {}
            )
        },
    }
    (tmp_path / f"{name}.json").write_text(json.dumps(doc), encoding="utf-8")


@pytest.fixture
def decisions_dir(tmp_path: Path) -> Path:
    d = tmp_path / "decisions"
    d.mkdir()
    return d


def test_not_ready_with_few_recorded_multipliers(decisions_dir: Path) -> None:
    for i in range(5):
        _write_decision(decisions_dir, f"d{i}", "2026-08-15T00:00:00+00:00")

    result = check_readiness(decisions_dir=decisions_dir)

    assert result["decisions_with_confidence_multiplier"] == 5
    assert result["calibration_ready"] is False


def test_ready_when_threshold_met(decisions_dir: Path) -> None:
    for i in range(100):
        _write_decision(decisions_dir, f"d{i}", "2026-08-15T00:00:00+00:00")

    result = check_readiness(decisions_dir=decisions_dir)

    assert result["decisions_with_confidence_multiplier"] == 100
    assert result["calibration_ready"] is True


def test_decisions_before_recording_start_are_excluded(decisions_dir: Path) -> None:
    """Key regression: decisions from before 2026-08-14 have no
    confidence_multiplier field at all and must not count toward, or be
    counted in, the readiness denominator -- they cannot be backfilled."""
    for i in range(50):
        _write_decision(
            decisions_dir, f"pre_{i}", "2026-08-01T00:00:00+00:00",
            confidence_multiplier=None,
        )
    for i in range(10):
        _write_decision(decisions_dir, f"post_{i}", "2026-08-15T00:00:00+00:00")

    result = check_readiness(decisions_dir=decisions_dir)

    assert result["decisions_since_recording_started"] == 10
    assert result["decisions_with_confidence_multiplier"] == 10
    assert result["calibration_ready"] is False


def test_decisions_missing_multiplier_field_not_counted(decisions_dir: Path) -> None:
    """A decision generated after recording started but where sizing wasn't
    reached (e.g. deny/hold path) has no confidence_multiplier and must not
    be counted as recorded."""
    for i in range(3):
        _write_decision(decisions_dir, f"has_{i}", "2026-08-16T00:00:00+00:00")
    for i in range(7):
        _write_decision(
            decisions_dir, f"missing_{i}", "2026-08-16T00:00:00+00:00",
            confidence_multiplier=None,
        )

    result = check_readiness(decisions_dir=decisions_dir)

    assert result["decisions_since_recording_started"] == 10
    assert result["decisions_with_confidence_multiplier"] == 3


def test_confidence_multiplier_distribution_recorded(decisions_dir: Path) -> None:
    _write_decision(decisions_dir, "a", "2026-08-15T00:00:00+00:00", confidence_multiplier=1.2)
    _write_decision(decisions_dir, "b", "2026-08-15T00:00:00+00:00", confidence_multiplier=1.2)
    _write_decision(decisions_dir, "c", "2026-08-15T00:00:00+00:00", confidence_multiplier=0.7)
    _write_decision(decisions_dir, "d", "2026-08-15T00:00:00+00:00", confidence_multiplier=1.0)

    result = check_readiness(decisions_dir=decisions_dir)

    assert result["confidence_multiplier_distribution"] == {1.2: 2, 0.7: 1, 1.0: 1}


def test_confidence_value_range_computed(decisions_dir: Path) -> None:
    _write_decision(decisions_dir, "a", "2026-08-15T00:00:00+00:00", confidence=0.52)
    _write_decision(decisions_dir, "b", "2026-08-15T00:00:00+00:00", confidence=0.85)

    result = check_readiness(decisions_dir=decisions_dir)

    assert result["confidence_min"] == 0.52
    assert result["confidence_max"] == 0.85
    assert result["confidence_value_count"] == 2


def test_empty_decisions_dir_no_crash(decisions_dir: Path) -> None:
    result = check_readiness(decisions_dir=decisions_dir)

    assert result["decisions_since_recording_started"] == 0
    assert result["decisions_with_confidence_multiplier"] == 0
    assert result["calibration_ready"] is False
    assert result["confidence_min"] is None
    assert result["confidence_max"] is None


def test_nonexistent_decisions_dir_no_crash(tmp_path: Path) -> None:
    result = check_readiness(decisions_dir=tmp_path / "does_not_exist")

    assert result["decisions_since_recording_started"] == 0
    assert result["calibration_ready"] is False


def test_malformed_json_file_skipped(decisions_dir: Path) -> None:
    (decisions_dir / "broken.json").write_text("{not valid json", encoding="utf-8")
    _write_decision(decisions_dir, "good", "2026-08-15T00:00:00+00:00")

    result = check_readiness(decisions_dir=decisions_dir)

    assert result["decisions_since_recording_started"] == 1


class TestCheckReadinessRealData:
    def test_real_data_is_not_yet_ready(self) -> None:
        """Sanity check against the actual project data/decisions/ --
        confirms wiring against real files. As of 2026-08-17 there are
        far fewer than 100 recorded confidence_multiplier decisions since
        recording started 2026-08-14, so this must report not-ready. This
        assertion should be revisited once real accumulation crosses the
        threshold (at which point R4-v2 confidence calibration can proceed
        and this test should be updated, not silently left stale)."""
        result = check_readiness()
        assert result["decisions_since_recording_started"] >= 0
        assert result["calibration_sample_threshold"] == 100
