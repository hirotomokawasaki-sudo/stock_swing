"""Tests for distance_from_high.py (Plan C, 2026-08-07 NBIS incident follow-up).

Observability-only diagnostic: classify_bounce_candidate() must never block
or raise, and must correctly flag the NBIS-incident profile (deep discount
from 52-week high + strong short-term momentum) as a bounce candidate.
"""
from __future__ import annotations

import json

from stock_swing.risk.distance_from_high import (
    DistanceFromHighConfig,
    classify_bounce_candidate,
    compute_distance_from_high_pct,
    log_observation,
)


# ── compute_distance_from_high_pct ───────────────────────────────────────── #

def test_distance_computed_correctly():
    # NBIS: entry ~$224 vs 52w-high $299.86 -> about -25.3%
    pct = compute_distance_from_high_pct(224.315, 299.86)
    assert pct == -25.19


def test_distance_zero_at_high():
    pct = compute_distance_from_high_pct(100.0, 100.0)
    assert pct == 0.0


def test_distance_positive_above_recorded_high():
    """A price above the recorded 52w-high (stale high data) yields a
    positive distance -- should not be treated as an error."""
    pct = compute_distance_from_high_pct(110.0, 100.0)
    assert pct == 10.0


def test_distance_none_when_close_missing():
    assert compute_distance_from_high_pct(None, 100.0) is None


def test_distance_none_when_high_missing():
    assert compute_distance_from_high_pct(100.0, None) is None


def test_distance_none_when_high_is_zero():
    assert compute_distance_from_high_pct(100.0, 0.0) is None


def test_distance_none_on_unparseable_values():
    assert compute_distance_from_high_pct("abc", 100.0) is None
    assert compute_distance_from_high_pct(100.0, "xyz") is None


# ── classify_bounce_candidate: NBIS incident profile ─────────────────────── #

def test_nbis_incident_profile_flagged_as_bounce_candidate():
    """Reproduces the actual 2026-08-05 NBIS BUY: close=$219.62,
    momentum=+27.86%, 52w-high=$299.86 (set 2026-06-22)."""
    metric = {"52WeekHigh": 299.86, "52WeekHighDate": "2026-06-22"}
    result = classify_bounce_candidate(
        symbol="NBIS",
        latest_close=219.6174,
        momentum_pct=27.86,
        metric_payload=metric,
    )
    assert result.is_bounce_candidate is True
    assert result.distance_from_high_pct < -20.0
    assert result.week52_high == 299.86
    assert result.week52_high_date == "2026-06-22"


def test_fresh_breakout_near_high_not_flagged():
    """A genuine breakout near the 52-week high, even with strong momentum,
    must not be flagged as a bounce candidate."""
    metric = {"52WeekHigh": 100.0, "52WeekHighDate": "2026-08-01"}
    result = classify_bounce_candidate(
        symbol="AAA", latest_close=98.0, momentum_pct=15.0, metric_payload=metric
    )
    assert result.is_bounce_candidate is False


def test_deep_discount_but_weak_momentum_not_flagged():
    """Deep discount alone (no real bounce momentum) should not be flagged."""
    metric = {"52WeekHigh": 100.0, "52WeekHighDate": "2026-01-01"}
    result = classify_bounce_candidate(
        symbol="BBB", latest_close=70.0, momentum_pct=2.0, metric_payload=metric
    )
    assert result.is_bounce_candidate is False


def test_strong_momentum_but_near_high_not_flagged():
    """Strong momentum near the high (small discount) should not be flagged."""
    metric = {"52WeekHigh": 100.0, "52WeekHighDate": "2026-01-01"}
    result = classify_bounce_candidate(
        symbol="CCC", latest_close=95.0, momentum_pct=25.0, metric_payload=metric
    )
    assert result.is_bounce_candidate is False


# ── Boundary values ──────────────────────────────────────────────────────── #

def test_boundary_exactly_at_thresholds_flags_candidate():
    cfg = DistanceFromHighConfig(min_distance_from_high_pct=-20.0, min_bounce_momentum_pct=10.0)
    metric = {"52WeekHigh": 100.0}
    result = classify_bounce_candidate(
        symbol="DDD", latest_close=80.0, momentum_pct=10.0, metric_payload=metric, config=cfg
    )
    assert result.distance_from_high_pct == -20.0
    assert result.is_bounce_candidate is True  # inclusive boundary (<=, >=)


def test_boundary_just_inside_not_flagged():
    cfg = DistanceFromHighConfig(min_distance_from_high_pct=-20.0, min_bounce_momentum_pct=10.0)
    metric = {"52WeekHigh": 100.0}
    result = classify_bounce_candidate(
        symbol="EEE", latest_close=81.0, momentum_pct=9.9, metric_payload=metric, config=cfg
    )
    assert result.is_bounce_candidate is False


# ── Missing / malformed data fallback (never raises, never flags) ───────── #

def test_none_metric_payload_not_flagged():
    result = classify_bounce_candidate(
        symbol="NBIS", latest_close=220.0, momentum_pct=28.0, metric_payload=None
    )
    assert result.is_bounce_candidate is False
    assert "no_data" in result.reason


def test_missing_52w_high_in_metric_not_flagged():
    result = classify_bounce_candidate(
        symbol="NBIS", latest_close=220.0, momentum_pct=28.0, metric_payload={"beta": 1.0}
    )
    assert result.is_bounce_candidate is False


def test_none_latest_close_not_flagged():
    metric = {"52WeekHigh": 299.86}
    result = classify_bounce_candidate(
        symbol="NBIS", latest_close=None, momentum_pct=28.0, metric_payload=metric
    )
    assert result.is_bounce_candidate is False


def test_none_momentum_not_flagged():
    metric = {"52WeekHigh": 299.86}
    result = classify_bounce_candidate(
        symbol="NBIS", latest_close=220.0, momentum_pct=None, metric_payload=metric
    )
    assert result.is_bounce_candidate is False
    assert "no_momentum" in result.reason


def test_disabled_config_never_flags():
    cfg = DistanceFromHighConfig(disabled=True)
    metric = {"52WeekHigh": 299.86}
    result = classify_bounce_candidate(
        symbol="NBIS", latest_close=200.0, momentum_pct=30.0, metric_payload=metric, config=cfg
    )
    assert result.is_bounce_candidate is False
    assert result.reason == "disabled"


def test_config_from_env_defaults(monkeypatch):
    monkeypatch.delenv("DISTANCE_FROM_HIGH_MIN_PCT", raising=False)
    monkeypatch.delenv("DISTANCE_FROM_HIGH_MIN_MOMENTUM", raising=False)
    monkeypatch.delenv("DISTANCE_FROM_HIGH_DISABLED", raising=False)
    cfg = DistanceFromHighConfig.from_env()
    assert cfg.min_distance_from_high_pct == -20.0
    assert cfg.min_bounce_momentum_pct == 10.0
    assert cfg.disabled is False


def test_config_from_env_overrides(monkeypatch):
    monkeypatch.setenv("DISTANCE_FROM_HIGH_MIN_PCT", "-30")
    monkeypatch.setenv("DISTANCE_FROM_HIGH_MIN_MOMENTUM", "15")
    monkeypatch.setenv("DISTANCE_FROM_HIGH_DISABLED", "true")
    cfg = DistanceFromHighConfig.from_env()
    assert cfg.min_distance_from_high_pct == -30.0
    assert cfg.min_bounce_momentum_pct == 15.0
    assert cfg.disabled is True


# ── log_observation: never raises, writes JSONL only for candidates ─────── #

def test_log_observation_writes_jsonl_for_candidate(tmp_path):
    log_path = tmp_path / "distance_from_high_log.jsonl"
    metric = {"52WeekHigh": 299.86, "52WeekHighDate": "2026-06-22"}
    result = classify_bounce_candidate(
        symbol="NBIS", latest_close=219.6174, momentum_pct=27.86, metric_payload=metric
    )
    log_observation(result, log_path=log_path)

    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["symbol"] == "NBIS"
    assert record["is_bounce_candidate"] is True


def test_log_observation_without_path_does_not_raise():
    metric = {"52WeekHigh": 299.86}
    result = classify_bounce_candidate(
        symbol="NBIS", latest_close=219.6, momentum_pct=27.86, metric_payload=metric
    )
    log_observation(result, log_path=None)  # must not raise


def test_log_observation_still_writes_non_candidates_to_file(tmp_path):
    """Even non-candidates should be recorded to the log file for later
    threshold calibration, even though no INFO line is emitted for them."""
    log_path = tmp_path / "distance_from_high_log.jsonl"
    metric = {"52WeekHigh": 100.0}
    result = classify_bounce_candidate(
        symbol="AAA", latest_close=98.0, momentum_pct=15.0, metric_payload=metric
    )
    assert result.is_bounce_candidate is False
    log_observation(result, log_path=log_path)
    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
