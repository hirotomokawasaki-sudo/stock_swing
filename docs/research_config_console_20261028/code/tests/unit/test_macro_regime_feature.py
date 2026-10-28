"""R7-v2 (2026-08-14): MacroRegimeFeature multi-indicator regime tests.

Replaces the old single-indicator (raw CPI level vs. constant 320) placeholder
with real CPI YoY / UNRATE trend / T10Y2Y yield curve / ICSA claims trend
classification. See macro_regime_feature.py module docstring for rationale.
"""
from __future__ import annotations

from datetime import datetime, timezone

from stock_swing.core.types import CanonicalRecord
from stock_swing.feature_engine.macro_regime_feature import MacroRegimeFeature


def _macro_record(series_id: str, period: str, value: float | None) -> CanonicalRecord:
    return CanonicalRecord(
        record_id=f"fred:{series_id}:{period}",
        schema_version="v1",
        source="fred",
        source_type="macro",
        symbol=None,
        event_type="macro_release",
        event_time=datetime.now(timezone.utc),
        as_of=period,
        ingested_at=datetime.now(timezone.utc),
        timezone="UTC",
        payload_version=None,
        payload={"series_id": series_id, "value": value, "period": period},
    )


def _cpi_series(values: list[float]) -> list[CanonicalRecord]:
    """13+ monthly points so YoY comparison (index -13) is available."""
    periods = [f"2025-{m:02d}-01" if m <= 12 else f"2026-{m-12:02d}-01" for m in range(1, len(values) + 1)]
    return [_macro_record("CPIAUCSL", p, v) for p, v in zip(periods, values)]


def _unrate_series(values: list[float]) -> list[CanonicalRecord]:
    return [_macro_record("UNRATE", f"2026-{i+1:02d}-01", v) for i, v in enumerate(values)]


def _curve_series(value: float) -> list[CanonicalRecord]:
    return [_macro_record("T10Y2Y", "2026-08-13", value)]


def _claims_series(values: list[float]) -> list[CanonicalRecord]:
    return [_macro_record("ICSA", f"2026-w{i}", v) for i, v in enumerate(values)]


class TestNoData:
    def test_empty_records_returns_unknown(self):
        feat = MacroRegimeFeature()
        results = feat.compute([])
        assert len(results) == 1
        assert results[0].values["regime"] == "unknown"
        assert results[0].values["confidence"] == 0.0
        assert "no_macro_data" in results[0].quality_flags

    def test_non_macro_records_ignored_returns_unknown(self):
        rec = CanonicalRecord(
            record_id="x", schema_version="v1", source="finnhub", source_type="news",
            symbol="AAPL", event_type="news", event_time=datetime.now(timezone.utc),
            as_of="2026-08-13", ingested_at=datetime.now(timezone.utc), timezone="UTC",
            payload_version=None, payload={},
        )
        feat = MacroRegimeFeature()
        results = feat.compute([rec])
        assert results[0].values["regime"] == "unknown"


class TestCpiYoy:
    def test_cpi_only_low_inflation_expansion(self):
        """13 flat CPI values (0% YoY) -> expansion (no other indicators)."""
        records = _cpi_series([300.0] * 13)
        feat = MacroRegimeFeature()
        result = feat.compute(records)[0]
        assert result.values["regime"] == "expansion"
        assert result.metadata["cpi_yoy_pct"] == 0.0
        assert result.metadata["indicators_used"] == ["CPIAUCSL"]

    def test_cpi_only_high_inflation_high_volatility(self):
        """CPI rose >4% YoY -> high_volatility."""
        values = [300.0] * 12 + [315.0]  # ~5% YoY
        records = _cpi_series(values)
        feat = MacroRegimeFeature()
        result = feat.compute(records)[0]
        assert result.values["regime"] == "high_volatility"
        assert result.metadata["cpi_yoy_pct"] > 4.0

    def test_cpi_insufficient_points_not_used(self):
        """Fewer than 13 points -> CPI indicator not evaluated -> unknown."""
        records = _cpi_series([300.0] * 5)
        feat = MacroRegimeFeature()
        result = feat.compute(records)[0]
        assert result.values["regime"] == "unknown"
        assert result.metadata["cpi_yoy_pct"] is None
        assert "insufficient_data" in result.quality_flags


class TestUnrateTrend:
    def test_rising_unrate_alone_is_recession(self):
        records = _unrate_series([4.0, 4.5])  # +0.5pp
        feat = MacroRegimeFeature()
        result = feat.compute(records)[0]
        assert result.values["regime"] == "recession"
        assert result.metadata["unrate_delta_pp"] == 0.5

    def test_stable_unrate_alone_is_expansion(self):
        records = _unrate_series([4.0, 4.05])  # below +0.3pp threshold
        feat = MacroRegimeFeature()
        result = feat.compute(records)[0]
        assert result.values["regime"] == "expansion"

    def test_single_unrate_point_not_evaluated(self):
        records = _unrate_series([4.0])
        feat = MacroRegimeFeature()
        result = feat.compute(records)[0]
        assert result.metadata["unrate_delta_pp"] is None
        assert result.values["regime"] == "unknown"


class TestYieldCurve:
    def test_inverted_curve_alone_is_recession(self):
        records = _curve_series(-0.1)
        feat = MacroRegimeFeature()
        result = feat.compute(records)[0]
        assert result.values["regime"] == "recession"
        assert result.metadata["yield_curve_spread"] == -0.1

    def test_zero_spread_is_recession_boundary(self):
        """Spread == 0.0 counts as inverted (threshold is <=)."""
        records = _curve_series(0.0)
        feat = MacroRegimeFeature()
        result = feat.compute(records)[0]
        assert result.values["regime"] == "recession"

    def test_positive_curve_alone_is_expansion(self):
        records = _curve_series(0.5)
        feat = MacroRegimeFeature()
        result = feat.compute(records)[0]
        assert result.values["regime"] == "expansion"


class TestClaimsTrend:
    def test_rising_claims_alone_is_recession(self):
        records = _claims_series([200000, 240000])  # +20%
        feat = MacroRegimeFeature()
        result = feat.compute(records)[0]
        assert result.values["regime"] == "recession"
        assert result.metadata["claims_change_pct"] > 15.0

    def test_stable_claims_alone_is_expansion(self):
        records = _claims_series([200000, 205000])  # +2.5%
        feat = MacroRegimeFeature()
        result = feat.compute(records)[0]
        assert result.values["regime"] == "expansion"


class TestCombinedIndicators:
    def test_recession_signal_takes_precedence_over_high_volatility(self):
        """High inflation + inverted curve -> recession wins (asymmetric risk)."""
        cpi_values = [300.0] * 12 + [315.0]  # high inflation
        records = _cpi_series(cpi_values) + _curve_series(-0.2)  # inverted curve
        feat = MacroRegimeFeature()
        result = feat.compute(records)[0]
        assert result.values["regime"] == "recession"

    def test_all_four_expansion_signals_full_confidence(self):
        cpi_values = [300.0] * 13  # 0% YoY
        records = (
            _cpi_series(cpi_values)
            + _unrate_series([4.0, 4.0])
            + _curve_series(0.5)
            + _claims_series([200000, 202000])
        )
        feat = MacroRegimeFeature()
        result = feat.compute(records)[0]
        assert result.values["regime"] == "expansion"
        assert result.values["confidence"] == 1.0
        assert set(result.metadata["indicators_used"]) == {
            "CPIAUCSL", "UNRATE", "T10Y2Y", "ICSA",
        }

    def test_partial_indicators_confidence_reflects_coverage(self):
        """Only 2 of 4 indicators available -> confidence denominator is 2, not 4."""
        records = _unrate_series([4.0, 4.0]) + _curve_series(0.5)
        feat = MacroRegimeFeature()
        result = feat.compute(records)[0]
        assert result.values["regime"] == "expansion"
        assert result.values["confidence"] == 1.0  # 2/2 expansion signals
        assert len(result.metadata["indicators_used"]) == 2
