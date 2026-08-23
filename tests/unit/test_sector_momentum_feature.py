"""Tests for SectorMomentumFeature (2026-08-23, R13-D Phase 2 — ETF sector
rotation strategy design).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from stock_swing.core.types import CanonicalRecord
from stock_swing.feature_engine.sector_momentum_feature import (
    DEFAULT_LOOKBACK_DAYS,
    SectorMomentumFeature,
    _daily_returns_from_bars,
)


def _bar(symbol: str, event_time: datetime, close: float) -> CanonicalRecord:
    return CanonicalRecord(
        record_id=f"test:{symbol}:{event_time.isoformat()}",
        schema_version="v1",
        source="broker",
        source_type="price",
        symbol=symbol,
        event_type="bar_daily",
        event_time=event_time,
        as_of=event_time.isoformat(),
        ingested_at=datetime.now(timezone.utc),
        timezone="UTC",
        payload_version="v1",
        payload={"close": close},
    )


def _bars(symbol: str, closes: list[float], start: datetime | None = None) -> list[CanonicalRecord]:
    base = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [_bar(symbol, base + timedelta(days=i), close) for i, close in enumerate(closes)]


class TestDailyReturnsFromBars:
    def test_computes_simple_returns(self) -> None:
        records = _bars("AAA", [100.0, 110.0, 99.0])
        returns = _daily_returns_from_bars(records)
        assert len(returns) == 2
        values = sorted(returns.values())
        assert abs(values[1] - 0.10) < 1e-9 or abs(values[0] - 0.10) < 1e-9

    def test_empty_for_single_bar(self) -> None:
        records = _bars("AAA", [100.0])
        assert _daily_returns_from_bars(records) == {}


class TestSectorMomentumFeature:
    def _make_records(self, sector_map: dict[str, str], n_days: int = 70) -> list[CanonicalRecord]:
        """Sector A (symbols A1,A2) trends up strongly; sector B (B1) is flat;
        sector C (C1) trends down."""
        records: list[CanonicalRecord] = []
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for sym, sector in sector_map.items():
            if sector == "up":
                closes = [100.0 * (1.01 ** i) for i in range(n_days)]
            elif sector == "flat":
                closes = [100.0 for _ in range(n_days)]
            else:
                closes = [100.0 * (0.99 ** i) for i in range(n_days)]
            records.extend(_bars(sym, closes, start=base))
        return records

    def test_ranks_sectors_by_trailing_return(self) -> None:
        sector_map = {"A1": "up", "A2": "up", "B1": "flat", "C1": "down"}
        records = self._make_records(sector_map)
        feature = SectorMomentumFeature(sector_map=sector_map, lookback_days=60)

        results = feature.compute(records)
        assert len(results) == 1
        values = results[0].values

        assert values["ranked_sectors"] == ["up", "flat", "down"]
        assert values["up_score"] > values["flat_score"] > values["down_score"]

    def test_is_global_feature_symbol_none(self) -> None:
        sector_map = {"A1": "up"}
        records = self._make_records(sector_map)
        feature = SectorMomentumFeature(sector_map=sector_map, lookback_days=60)
        results = feature.compute(records)
        assert results[0].symbol is None
        assert results[0].feature_name == "sector_momentum"

    def test_sector_members_included_in_metadata(self) -> None:
        sector_map = {"A1": "up", "A2": "up", "B1": "flat"}
        records = self._make_records(sector_map)
        feature = SectorMomentumFeature(sector_map=sector_map, lookback_days=60)
        results = feature.compute(records)
        members = results[0].metadata["sector_members"]
        assert sorted(members["up"]) == ["A1", "A2"]
        assert members["flat"] == ["B1"]

    def test_insufficient_coverage_yields_none_score_and_quality_flag(self) -> None:
        sector_map = {"THIN": "sparse"}
        # Only 3 days of data but lookback_days requires more coverage.
        records = _bars("THIN", [100.0, 101.0, 102.0])
        feature = SectorMomentumFeature(sector_map=sector_map, lookback_days=60, min_coverage_ratio=0.8)
        results = feature.compute(records)
        values = results[0].values
        assert values.get("sparse_score") is None
        assert any("insufficient_coverage:sparse" in f for f in results[0].quality_flags)
        assert "sparse" not in values["ranked_sectors"]

    def test_no_records_returns_empty_ranking(self) -> None:
        feature = SectorMomentumFeature(sector_map={"A1": "up"}, lookback_days=60)
        results = feature.compute([])
        assert results[0].values["ranked_sectors"] == []

    def test_ignores_symbols_not_in_sector_map(self) -> None:
        sector_map = {"A1": "up"}
        records = self._make_records({"A1": "up", "ZZZ": "flat"})
        feature = SectorMomentumFeature(sector_map=sector_map, lookback_days=60)
        results = feature.compute(records)
        assert "ZZZ" not in str(results[0].metadata["sector_members"])

    def test_default_lookback_days_matches_phase1_default(self) -> None:
        assert DEFAULT_LOOKBACK_DAYS == 63

    def test_requires_lookback_days_plus_one_closes_for_full_coverage(self) -> None:
        """Regression guard for the off-by-one found during R13-D Phase 2's
        feature/strategy consistency check (2026-08-23, see
        scripts/r13d_sector_rotation_feature_strategy_validation.py):
        computing a `lookback_days`-length return window requires
        `lookback_days + 1` underlying close prices (the return for the
        first day in the window needs the prior day's close too). Exactly
        `lookback_days` closes yields exactly `lookback_days - 1` days of
        return coverage -- below the 80% default min_coverage_ratio only
        for small lookback windows, so this test uses a small window where
        the shortfall is large enough to be unambiguous.
        """
        sector_map = {"A1": "onlysector"}
        # Exactly 5 closes -> only 4 days of returns computable.
        records = _bars("A1", [100.0, 101.0, 102.0, 103.0, 104.0])
        feature = SectorMomentumFeature(sector_map=sector_map, lookback_days=5, min_coverage_ratio=0.8)
        results = feature.compute(records)
        # 4/5 = 80% coverage exactly meets the default min_coverage_ratio
        # threshold (>=), so the score IS still reported here -- this test
        # documents the boundary, not a failure case.
        assert results[0].values["onlysector_score"] is not None

        # One fewer close (4 total) drops coverage to 3/5 = 60%, below the
        # 80% floor -- score must become None.
        records_short = _bars("A1", [100.0, 101.0, 102.0, 103.0])
        results_short = feature.compute(records_short)
        assert results_short[0].values["onlysector_score"] is None
