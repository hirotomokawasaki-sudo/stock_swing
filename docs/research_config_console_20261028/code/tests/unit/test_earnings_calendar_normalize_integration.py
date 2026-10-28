"""Integration test: raw finnhub earnings_calendar snapshot -> FinnhubNormalizer
-> EarningsEventFeature, matching the exact read/normalize/compute pipeline
wired into paper_demo.py (2026-08-07).

This locks in the end-to-end plumbing between collect_earnings_calendar()'s
output format and EarningsEventFeature's input requirements, independent of
paper_demo.py's own (heavily-mocked) integration tests.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from stock_swing.core.types import RawEnvelope
from stock_swing.feature_engine.earnings_event_feature import EarningsEventFeature
from stock_swing.normalization.finnhub_normalizer import FinnhubNormalizer


def _raw_snapshot_dict(rows: list[dict], fetched_at: datetime) -> dict:
    """Build the exact JSON shape collect_data._write_raw_snapshot() writes
    for an earnings_calendar snapshot (see collect_earnings_calendar())."""
    return {
        "source": "finnhub",
        "endpoint": "calendar/earnings",
        "fetched_at": fetched_at.isoformat(),
        "event_time": fetched_at.isoformat(),
        "available_at": fetched_at.isoformat(),
        "ingested_at": fetched_at.isoformat(),
        "source_id": "abc123",
        "revision_id": None,
        "quality_status": "ok",
        "is_synthetic": False,
        "request_params": {"from": "2026-08-07", "to": "2026-08-17"},
        "payload": {"earningsCalendar": rows},
    }


def _load_and_compute(raw_dict: dict, universe: set[str]):
    """Mirror paper_demo.py's earnings_event_results block exactly."""
    envelope = RawEnvelope(
        source=raw_dict.get("source", "finnhub"),
        endpoint=raw_dict.get("endpoint", "calendar/earnings"),
        fetched_at=datetime.fromisoformat(raw_dict["fetched_at"]),
        request_params=raw_dict.get("request_params") or {},
        payload=raw_dict.get("payload") or {},
    )
    records = FinnhubNormalizer().normalize(envelope)
    records = [r for r in records if r.symbol in universe]
    return EarningsEventFeature().compute(records)


def test_upcoming_earnings_flagged_has_upcoming_event_true():
    now = datetime.now(timezone.utc)
    upcoming_date = (now + timedelta(days=3)).date().isoformat()
    raw = _raw_snapshot_dict(
        [{"symbol": "AAPL", "date": upcoming_date, "epsEstimate": 1.5, "quarter": 3, "year": 2026}],
        fetched_at=now,
    )
    results = _load_and_compute(raw, universe={"AAPL"})

    aapl = next(r for r in results if r.symbol == "AAPL")
    assert aapl.values["has_upcoming_event"] is True
    assert aapl.values["days_until_event"] in (2, 3)  # tz/rounding tolerance


def test_universe_filter_excludes_non_traded_symbols():
    now = datetime.now(timezone.utc)
    upcoming_date = (now + timedelta(days=3)).date().isoformat()
    raw = _raw_snapshot_dict(
        [
            {"symbol": "AAPL", "date": upcoming_date},
            {"symbol": "RANDOMCO", "date": upcoming_date},
        ],
        fetched_at=now,
    )
    results = _load_and_compute(raw, universe={"AAPL"})

    symbols = {r.symbol for r in results}
    assert symbols == {"AAPL"}


def test_event_swing_strategy_generates_signal_from_earnings_plus_momentum():
    """End-to-end: earnings feature + bullish momentum feature must produce
    an event_swing_v1 CandidateSignal (the exact gap this fix closes --
    previously always 0 signals because earnings_event was never present)."""
    from stock_swing.feature_engine.base_feature import FeatureResult
    from stock_swing.strategy_engine.event_swing_strategy import EventSwingStrategy

    now = datetime.now(timezone.utc)
    upcoming_date = (now + timedelta(days=3)).date().isoformat()
    raw = _raw_snapshot_dict([{"symbol": "AAPL", "date": upcoming_date}], fetched_at=now)
    earnings_results = _load_and_compute(raw, universe={"AAPL"})

    momentum_result = FeatureResult(
        feature_name="price_momentum",
        symbol="AAPL",
        computed_at=now,
        values={"momentum": 0.05, "trend": "bullish", "bars_used": 10},
        metadata={},
        quality_flags=[],
    )

    strat = EventSwingStrategy(min_signal_strength=0.1, min_momentum=0.01)
    signals = strat.generate(earnings_results + [momentum_result])

    assert len(signals) == 1
    assert signals[0].symbol == "AAPL"
    assert signals[0].strategy_id == "event_swing_v1"


def test_no_upcoming_events_produces_no_event_swing_signals():
    """Symbols with has_upcoming_event=False must not generate signals
    (matches EventSwingStrategy.generate()'s early-continue)."""
    from stock_swing.feature_engine.base_feature import FeatureResult
    from stock_swing.strategy_engine.event_swing_strategy import EventSwingStrategy

    now = datetime.now(timezone.utc)
    far_future_date = (now + timedelta(days=60)).date().isoformat()  # outside 7d lookahead
    raw = _raw_snapshot_dict([{"symbol": "AAPL", "date": far_future_date}], fetched_at=now)
    earnings_results = _load_and_compute(raw, universe={"AAPL"})

    momentum_result = FeatureResult(
        feature_name="price_momentum", symbol="AAPL", computed_at=now,
        values={"momentum": 0.05, "trend": "bullish", "bars_used": 10},
        metadata={}, quality_flags=[],
    )

    strat = EventSwingStrategy(min_signal_strength=0.1, min_momentum=0.01)
    signals = strat.generate(earnings_results + [momentum_result])
    assert signals == []


def test_empty_earnings_calendar_snapshot_does_not_raise():
    now = datetime.now(timezone.utc)
    raw = _raw_snapshot_dict([], fetched_at=now)
    results = _load_and_compute(raw, universe={"AAPL"})
    assert results == []
