"""Tests for UsOvernightBenchmarkFeature (2026-08-19, JP semiconductor/AI
expansion Phase 2 — see docs/jp_semiconductor_ai_expansion_phase2_design.md
section 2-A).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from stock_swing.core.types import CanonicalRecord
from stock_swing.feature_engine.us_overnight_benchmark_feature import (
    DEFAULT_BENCHMARK_SYMBOLS,
    PRIMARY_BENCHMARK_SYMBOL,
    UsOvernightBenchmarkFeature,
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


def _bars(symbol: str, closes: list[float]) -> list[CanonicalRecord]:
    base = datetime(2026, 8, 1, tzinfo=timezone.utc)
    return [
        _bar(symbol, base + timedelta(days=i), close)
        for i, close in enumerate(closes)
    ]


class TestUsOvernightBenchmarkFeature:
    def test_computes_return_for_all_configured_benchmarks(self) -> None:
        records = (
            _bars("SOXX", [100.0, 102.0])
            + _bars("SMH", [50.0, 51.0])
            + _bars("NVDA", [200.0, 196.0])
        )
        feature = UsOvernightBenchmarkFeature()

        results = feature.compute(records)

        assert len(results) == 1
        values = results[0].values
        assert values["soxx_return_pct"] == 2.0
        assert values["smh_return_pct"] == 2.0
        assert values["nvda_return_pct"] == -2.0

    def test_is_global_feature_symbol_none(self) -> None:
        """Acceptance: like MacroRegimeFeature, this feature is global (not
        per-JP-symbol), since the US benchmark return is the same input
        regardless of which JP symbol eventually consumes it."""
        records = _bars("SOXX", [100.0, 102.0])
        feature = UsOvernightBenchmarkFeature()

        results = feature.compute(records)

        assert results[0].symbol is None
        assert results[0].feature_name == "us_overnight_benchmark_return"

    def test_primary_return_pct_matches_soxx(self) -> None:
        """Acceptance: primary_return_pct must mirror the SOXX return, since
        SOXX had the strongest spillover correlation in Phase 1's analysis
        (docs/jp_semiconductor_ai_expansion_plan.md section 7-A)."""
        records = _bars("SOXX", [100.0, 95.0])
        feature = UsOvernightBenchmarkFeature()

        results = feature.compute(records)

        assert results[0].values["primary_benchmark_symbol"] == PRIMARY_BENCHMARK_SYMBOL
        assert results[0].values["primary_return_pct"] == -5.0

    def test_missing_benchmark_data_flags_quality_and_returns_none(self) -> None:
        """Fallback: a configured benchmark with no records must not crash,
        must report None for its return, and must be flagged in
        quality_flags (consistent with MacroRegimeFeature's missing-data
        handling)."""
        records = _bars("SOXX", [100.0, 102.0])  # SMH, NVDA missing entirely
        feature = UsOvernightBenchmarkFeature()

        results = feature.compute(records)

        assert results[0].values["smh_return_pct"] is None
        assert results[0].values["nvda_return_pct"] is None
        assert "missing_data:SMH" in results[0].quality_flags
        assert "missing_data:NVDA" in results[0].quality_flags

    def test_single_bar_is_insufficient_data(self) -> None:
        """Boundary: a benchmark with only one bar (no prior close to
        compare against) must return None, not raise or divide-by-zero."""
        records = _bars("SOXX", [100.0])
        feature = UsOvernightBenchmarkFeature()

        results = feature.compute(records)

        assert results[0].values["soxx_return_pct"] is None

    def test_empty_records_returns_all_none(self) -> None:
        """Fallback: completely empty input must not crash."""
        feature = UsOvernightBenchmarkFeature()

        results = feature.compute([])

        assert len(results) == 1
        assert all(
            results[0].values[f"{sym.lower()}_return_pct"] is None
            for sym in DEFAULT_BENCHMARK_SYMBOLS
        )

    def test_uses_most_recent_bar_pair_when_more_than_two_present(self) -> None:
        """Acceptance: with a longer bar history, the feature must use only
        the LATEST two bars for the return calculation (not e.g. first vs
        last), matching PriceMomentumFeature's "most recent" semantics."""
        # 100 -> 110 -> 105 -> 120: latest return should be (120/105 - 1)
        records = _bars("SOXX", [100.0, 110.0, 105.0, 120.0])
        feature = UsOvernightBenchmarkFeature()

        results = feature.compute(records)

        expected = round((120.0 / 105.0 - 1) * 100, 4)
        assert results[0].values["soxx_return_pct"] == expected

    def test_ignores_non_benchmark_symbols(self) -> None:
        """Boundary: price bars for symbols not in benchmark_symbols must be
        ignored entirely (e.g. a JP candidate symbol's own bars, if they
        happened to be in the same records batch, must not pollute the
        benchmark computation)."""
        records = _bars("SOXX", [100.0, 102.0]) + _bars("8035.T", [1000.0, 5000.0])
        feature = UsOvernightBenchmarkFeature()

        results = feature.compute(records)

        assert results[0].values["soxx_return_pct"] == 2.0
        assert "8035.t_return_pct" not in results[0].values

    def test_custom_benchmark_symbols_override_default(self) -> None:
        """Configuration: a custom benchmark_symbols tuple must be
        respected instead of the module default."""
        records = _bars("QQQ", [400.0, 404.0])
        feature = UsOvernightBenchmarkFeature(benchmark_symbols=("QQQ",))

        results = feature.compute(records)

        assert results[0].values["qqq_return_pct"] == 1.0
        assert "soxx_return_pct" not in results[0].values

    def test_zero_prior_close_does_not_crash(self) -> None:
        """Boundary: a degenerate zero prior close must not raise
        ZeroDivisionError."""
        records = _bars("SOXX", [0.0, 100.0])
        feature = UsOvernightBenchmarkFeature()

        results = feature.compute(records)

        assert results[0].values["soxx_return_pct"] is None
