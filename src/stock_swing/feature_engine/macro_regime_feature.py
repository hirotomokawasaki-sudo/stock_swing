"""Macro regime feature for classifying economic environment.

This feature uses FRED macro data to classify the current macro regime
(e.g., expansion, recession, high volatility).

R7-v2 (2026-08-14): replaced the single-indicator CPI-level placeholder
heuristic with a real multi-indicator classification using the FRED series
collected by collect_data.collect_fred() (CPIAUCSL/UNRATE/T10Y2Y/ICSA -- see
FRED_MACRO_SERIES in cli/collect_data.py). The previous implementation
compared a raw CPI index level against a fixed constant (320), which is not
a meaningful economic signal (CPI is a non-stationary index that trends
upward over decades regardless of regime) and could never detect
'recession'. This version derives:
  - CPI YoY inflation rate (high_volatility signal when elevated)
  - UNRATE trend direction (rising unemployment -> recession signal)
  - T10Y2Y yield curve spread (inverted / near-inverted -> recession risk)
  - ICSA (initial jobless claims) trend (rising claims -> labor stress)
and combines them into a single regime label with a confidence score based
on how many of the four indicators actually had enough data to evaluate.
"""

from __future__ import annotations

from datetime import datetime, timezone

from stock_swing.core.types import CanonicalRecord
from stock_swing.feature_engine.base_feature import BaseFeature, FeatureResult

# Series IDs -- kept in sync with collect_data.FRED_MACRO_SERIES.
_CPI_SERIES = "CPIAUCSL"
_UNRATE_SERIES = "UNRATE"
_YIELD_CURVE_SERIES = "T10Y2Y"
_CLAIMS_SERIES = "ICSA"

# Thresholds (deliberately simple/transparent -- documented here rather than
# tuned against a backtest, since this feature is regime-context only and
# does not directly size positions).
_CPI_YOY_HIGH_PCT = 4.0  # annualized CPI YoY % above this -> inflationary pressure
_UNRATE_RISING_DELTA = 0.3  # +0.3pp over the lookback -> deteriorating labor market
_YIELD_CURVE_INVERTED = 0.0  # T10Y2Y <= 0 -> inverted curve (classic recession signal)
_CLAIMS_RISING_PCT = 15.0  # +15% over the lookback -> rising claims trend


def _series_records(records: list[CanonicalRecord], series_id: str) -> list[dict]:
    """Return payloads for a given FRED series_id, sorted ascending by 'period'."""
    rows = [
        r.payload
        for r in records
        if r.source_type == "macro" and r.payload.get("series_id") == series_id
    ]
    return sorted(rows, key=lambda p: p.get("period") or "")


def _cpi_yoy_pct(rows: list[dict]) -> float | None:
    """Approximate YoY CPI inflation from the most recent observations.

    FRED CPIAUCSL is monthly; with the last ~24 observations (collect_fred
    requests limit=24) we can compare the latest value to ~12 months prior.
    """
    values = [r.get("value") for r in rows if r.get("value") is not None]
    if len(values) < 13:
        return None
    latest = values[-1]
    year_ago = values[-13]
    if not year_ago:
        return None
    return (latest - year_ago) / year_ago * 100.0


def _unrate_delta(rows: list[dict]) -> float | None:
    """Change in unemployment rate over the available lookback (percentage points)."""
    values = [r.get("value") for r in rows if r.get("value") is not None]
    if len(values) < 2:
        return None
    return values[-1] - values[0]


def _latest_value(rows: list[dict]) -> float | None:
    values = [r.get("value") for r in rows if r.get("value") is not None]
    return values[-1] if values else None


def _claims_pct_change(rows: list[dict]) -> float | None:
    values = [r.get("value") for r in rows if r.get("value") is not None]
    if len(values) < 2 or not values[0]:
        return None
    return (values[-1] - values[0]) / values[0] * 100.0


class MacroRegimeFeature(BaseFeature):
    """Macro regime classification feature.

    Uses macro indicators (CPI YoY, unemployment trend, yield curve, jobless
    claims trend) to classify the current regime.

    Regime categories:
    - expansion: Growing economy, low inflation/volatility signals
    - recession: Yield curve inverted and/or unemployment/claims rising
    - high_volatility: Elevated inflation without clear recession signal
    - unknown: Insufficient data across all indicators
    """

    def compute(self, records: list[CanonicalRecord]) -> list[FeatureResult]:
        """Compute macro regime from macro data records.

        Args:
            records: Canonical records from FRED (macro data).

        Returns:
            List with one FeatureResult (macro regime is global).
        """
        macro_records = [r for r in records if r.source_type == "macro"]

        if not macro_records:
            return [self._unknown_regime()]

        cpi_rows = _series_records(macro_records, _CPI_SERIES)
        unrate_rows = _series_records(macro_records, _UNRATE_SERIES)
        curve_rows = _series_records(macro_records, _YIELD_CURVE_SERIES)
        claims_rows = _series_records(macro_records, _CLAIMS_SERIES)

        cpi_yoy = _cpi_yoy_pct(cpi_rows)
        unrate_delta = _unrate_delta(unrate_rows)
        curve_spread = _latest_value(curve_rows)
        claims_change = _claims_pct_change(claims_rows)

        indicators_used = []
        signals = {"recession": 0, "high_volatility": 0, "expansion": 0}

        if cpi_yoy is not None:
            indicators_used.append(_CPI_SERIES)
            if cpi_yoy >= _CPI_YOY_HIGH_PCT:
                signals["high_volatility"] += 1
            else:
                signals["expansion"] += 1

        if unrate_delta is not None:
            indicators_used.append(_UNRATE_SERIES)
            if unrate_delta >= _UNRATE_RISING_DELTA:
                signals["recession"] += 1
            else:
                signals["expansion"] += 1

        if curve_spread is not None:
            indicators_used.append(_YIELD_CURVE_SERIES)
            if curve_spread <= _YIELD_CURVE_INVERTED:
                signals["recession"] += 1
            else:
                signals["expansion"] += 1

        if claims_change is not None:
            indicators_used.append(_CLAIMS_SERIES)
            if claims_change >= _CLAIMS_RISING_PCT:
                signals["recession"] += 1
            else:
                signals["expansion"] += 1

        total_indicators = len(indicators_used)
        if total_indicators == 0:
            regime = "unknown"
            confidence = 0.0
        else:
            # Recession signals take precedence (asymmetric risk: missing a
            # recession warning is worse than staying cautious during a false
            # positive). Otherwise fall back to whichever of
            # expansion/high_volatility has more support.
            if signals["recession"] > 0:
                regime = "recession"
                confidence = round(signals["recession"] / total_indicators, 3)
            elif signals["high_volatility"] >= signals["expansion"] and signals["high_volatility"] > 0:
                regime = "high_volatility"
                confidence = round(signals["high_volatility"] / total_indicators, 3)
            else:
                regime = "expansion"
                confidence = round(signals["expansion"] / total_indicators, 3)

        result = FeatureResult(
            feature_name="macro_regime",
            symbol=None,  # Global feature
            computed_at=datetime.now(timezone.utc),
            values={
                "regime": regime,
                "confidence": confidence,
            },
            metadata={
                "input_records": len(macro_records),
                "indicators_used": indicators_used,
                "cpi_yoy_pct": None if cpi_yoy is None else round(cpi_yoy, 3),
                "unrate_delta_pp": None if unrate_delta is None else round(unrate_delta, 3),
                "yield_curve_spread": curve_spread,
                "claims_change_pct": None if claims_change is None else round(claims_change, 3),
            },
            quality_flags=[] if total_indicators else ["insufficient_data"],
        )

        return [result]

    def _unknown_regime(self) -> FeatureResult:
        """Return unknown regime when no data available."""
        return FeatureResult(
            feature_name="macro_regime",
            symbol=None,
            computed_at=datetime.now(timezone.utc),
            values={
                "regime": "unknown",
                "confidence": 0.0,
            },
            metadata={},
            quality_flags=["no_macro_data"],
        )
