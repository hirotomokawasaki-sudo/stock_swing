"""Tests for the JP semiconductor correlation analysis research script.

See docs/jp_semiconductor_ai_expansion_plan.md (Phase 1) for context. This
script is read-only research tooling (no broker/order interaction), so tests
focus on the pure computation functions using synthetic data rather than
live network calls.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from analyze_jp_semiconductor_correlation import (  # noqa: E402
    compute_conditional_gap_analysis,
    compute_correlation,
)


def _make_price_df(closes: list[float], opens: list[float] | None = None) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=len(closes), freq="D")
    opens = opens or closes
    df = pd.DataFrame({"Open": opens, "Close": closes}, index=dates)
    df["ret"] = df["Close"].pct_change()
    return df


class TestComputeCorrelation:
    def test_perfect_same_day_correlation(self) -> None:
        """Acceptance: identical return series must yield same_day_correlation == 1.0."""
        closes = [100, 102, 101, 105, 103, 108, 106, 110, 109, 112, 111, 115]
        us_df = _make_price_df(closes)
        jp_df = _make_price_df(closes)

        result = compute_correlation(us_df, jp_df, "US", "JP")

        assert result["n_same_day"] >= 10
        assert result["same_day_correlation"] == pytest.approx(1.0, abs=1e-6)

    def test_spillover_correlation_shifts_jp_forward_one_day(self) -> None:
        """Acceptance: if JP(t+1) == US(t) exactly, spillover_correlation must be ~1.0
        while same_day_correlation (US(t) vs JP(t), unshifted) is weaker.
        """
        us_closes = [100, 102, 104, 103, 107, 105, 110, 108, 113, 111, 116, 114]
        # JP return on day t+1 mirrors US return on day t exactly.
        us_df = _make_price_df(us_closes)
        us_returns = us_df["ret"].tolist()

        jp_closes = [100.0]
        for i in range(1, len(us_closes)):
            prev_ret = us_returns[i - 1] if i >= 1 and pd.notna(us_returns[i - 1]) else 0.0
            jp_closes.append(jp_closes[-1] * (1 + prev_ret))
        jp_df = _make_price_df(jp_closes)

        result = compute_correlation(us_df, jp_df, "US", "JP")

        assert result["spillover_correlation_us_t_vs_jp_t_plus_1"] == pytest.approx(1.0, abs=1e-6)

    def test_insufficient_data_returns_none(self) -> None:
        """Boundary: fewer than 10 overlapping observations must return None, not crash."""
        closes = [100, 101, 102]
        us_df = _make_price_df(closes)
        jp_df = _make_price_df(closes)

        result = compute_correlation(us_df, jp_df, "US", "JP")

        assert result["same_day_correlation"] is None
        assert result["spillover_correlation_us_t_vs_jp_t_plus_1"] is None


class TestComputeConditionalGapAnalysis:
    def test_large_up_day_followed_by_positive_gap(self) -> None:
        """Acceptance: a large US up-day followed by a JP open above prior JP close
        must be counted in us_large_up_days with a positive mean_jp_gap_pct.
        """
        n = 15
        dates = pd.date_range("2026-01-01", periods=n, freq="D")
        us_rets = [0.0] + [0.03 if i % 2 == 0 else 0.001 for i in range(1, n)]
        us_closes = [100.0]
        for r in us_rets[1:]:
            us_closes.append(us_closes[-1] * (1 + r))
        us_df = pd.DataFrame({"Open": us_closes, "Close": us_closes}, index=dates)
        us_df["ret"] = us_df["Close"].pct_change()

        # JP: close flat at 1000, but open gaps up +2% whenever prior day's
        # aligned US return (via shift(-1) alignment) was a "large up" day.
        jp_close = [1000.0] * n
        jp_open = [1000.0] * n
        for i in range(n - 1):
            if us_rets[i] >= 2.0 / 100:
                jp_open[i + 1] = jp_close[i] * 1.02
        jp_df = pd.DataFrame({"Open": jp_open, "Close": jp_close}, index=dates)

        result = compute_conditional_gap_analysis(us_df, jp_df, "US", "JP", threshold_pct=2.0)

        assert result["us_large_up_days"]["n"] >= 1
        assert result["us_large_up_days"]["mean_jp_gap_pct"] > 0

    def test_no_overlapping_data_returns_zero_days_not_crash(self) -> None:
        """Fallback: empty overlap after dropna must not raise, must report n=0."""
        us_df = _make_price_df([100, 101])
        jp_df = pd.DataFrame({"Open": [], "Close": []})

        result = compute_conditional_gap_analysis(us_df, jp_df, "US", "JP", threshold_pct=2.0)

        assert result["large_move_days"] == 0
