from datetime import datetime, timezone

from stock_swing.core.types import CanonicalRecord, RawEnvelope
from stock_swing.feature_engine.earnings_event_feature import EarningsEventFeature
from stock_swing.normalization.finnhub_normalizer import FinnhubNormalizer
from stock_swing.risk.earnings_proximity_shadow import classify_earnings_proximity


def _records(symbol: str, date: str, hour: str):
    raw = RawEnvelope(
        source="finnhub",
        endpoint="calendar/earnings",
        fetched_at=datetime(2026, 9, 2, 23, 5, tzinfo=timezone.utc),
        request_params={},
        payload={"earningsCalendar": [{"symbol": symbol, "date": date, "hour": hour}]},
    )
    return FinnhubNormalizer().normalize(raw)


def test_amc_timestamp_remains_upcoming_during_same_day_market_session():
    records = _records("PATH", "2026-09-03", "amc")
    assert records[0].event_time == datetime(2026, 9, 3, 20, 0, tzinfo=timezone.utc)

    results = EarningsEventFeature().compute(
        records,
        now=datetime(2026, 9, 3, 13, 35, tzinfo=timezone.utc),
    )
    assert results[0].values["has_upcoming_event"] is True


def test_bmo_timestamp_uses_exchange_local_morning():
    records = _records("AAPL", "2026-09-03", "bmo")
    assert records[0].event_time == datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def test_path_breakout_same_day_amc_is_shadow_block_candidate():
    observation = classify_earnings_proximity(
        "PATH",
        "breakout_momentum_v2_threshold_tuned",
        _records("PATH", "2026-09-03", "amc"),
        observed_at=datetime(2026, 9, 3, 13, 35, tzinfo=timezone.utc),
    )
    assert observation.phase == "pre_event"
    assert observation.would_block is True
    assert observation.relative_hours == 6.42


def test_snow_day_after_amc_is_post_event_shadow_block_candidate():
    observation = classify_earnings_proximity(
        "SNOW",
        "breakout_momentum_v2_threshold_tuned",
        _records("SNOW", "2026-09-02", "amc"),
        observed_at=datetime(2026, 9, 3, 13, 35, tzinfo=timezone.utc),
    )
    assert observation.phase == "post_event"
    assert observation.would_block is True


def test_event_swing_is_observed_but_not_labelled_for_blocking():
    observation = classify_earnings_proximity(
        "PATH",
        "event_swing_v1",
        _records("PATH", "2026-09-03", "amc"),
        observed_at=datetime(2026, 9, 3, 13, 35, tzinfo=timezone.utc),
    )
    assert observation.phase == "pre_event"
    assert observation.would_block is False
