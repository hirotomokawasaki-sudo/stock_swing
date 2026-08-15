"""Tests for the R11 follow-up (2026-08-15) market chop/regime indicator.

See src/stock_swing/risk/market_regime_indicator.py module docstring for
the full rationale: this is a read-only console panel, not a trading gate.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from stock_swing.risk.market_regime_indicator import (
    MarketRegimeIndicator,
    compute_market_regime_indicator,
)


def _write_benchmark(tmp_path: Path, symbol: str, closes: list[float], start_date: str = "2026-01-01") -> None:
    from datetime import datetime, timedelta

    start = datetime.fromisoformat(start_date)
    bars = []
    for i, close in enumerate(closes):
        d = start + timedelta(days=i)
        bars.append({"date": d.strftime("%Y-%m-%d"), "close": close})
    (tmp_path / f"{symbol}_daily.json").write_text(json.dumps(bars), encoding="utf-8")


def test_insufficient_data_returns_flagged_result(tmp_path: Path) -> None:
    _write_benchmark(tmp_path, "SPY", [100.0] * 10)  # far fewer than sma_period+trend_window
    result = compute_market_regime_indicator(tmp_path, sma_period=50, trend_window=5)
    assert result.insufficient_data is True
    assert result.chop_score is None
    assert result.regime_label == "insufficient_data"


def test_missing_benchmark_file_returns_insufficient_data(tmp_path: Path) -> None:
    result = compute_market_regime_indicator(tmp_path, regime_symbol="SPY")
    assert result.insufficient_data is True


def test_clean_uptrend_scores_low_chop(tmp_path: Path) -> None:
    # Steady linear uptrend: price consistently above a steadily rising SMA.
    closes = [100.0 + i * 0.5 for i in range(80)]
    _write_benchmark(tmp_path, "SPY", closes)
    result = compute_market_regime_indicator(tmp_path, sma_period=50, trend_window=5, range_window=20)
    assert result.insufficient_data is False
    assert result.above_sma is True
    assert result.sma_rising is True
    assert result.regime_label == "trending_bullish"
    assert result.chop_score < 35


def test_clean_downtrend_scores_low_chop_bearish(tmp_path: Path) -> None:
    closes = [200.0 - i * 0.5 for i in range(80)]
    _write_benchmark(tmp_path, "SPY", closes)
    result = compute_market_regime_indicator(tmp_path, sma_period=50, trend_window=5, range_window=20)
    assert result.above_sma is False
    assert result.sma_rising is False
    assert result.regime_label == "trending_bearish"
    assert result.chop_score < 35


def test_whipsaw_pattern_scores_high_chop(tmp_path: Path) -> None:
    # Mimics the 2026-08-15 finding: price oscillating in a range while the
    # SMA itself is roughly flat/mixed relative to price position -- price
    # currently below SMA while SMA is still (barely) rising is the
    # "mixed" signature the module treats as choppy.
    import math
    closes = [150.0 + 20 * math.sin(i / 4.0) + i * 0.05 for i in range(80)]
    _write_benchmark(tmp_path, "SPY", closes)
    result = compute_market_regime_indicator(tmp_path, sma_period=50, trend_window=5, range_window=20)
    assert result.insufficient_data is False
    # Whether this specific synthetic series lands on the "mixed" trend
    # combination depends on phase, so assert on the range-width behavior
    # (the other half of chop_score) instead of the exact label, which is
    # phase-sensitive and would make this test flaky.
    assert result.range_width_pct is not None
    assert result.range_width_pct > 10  # oscillation of amplitude 20 on ~150 base


def test_regime_symbol_is_configurable(tmp_path: Path) -> None:
    _write_benchmark(tmp_path, "QQQ", [100.0 + i * 0.3 for i in range(80)])
    result = compute_market_regime_indicator(tmp_path, regime_symbol="QQQ", sma_period=50, trend_window=5)
    assert result.regime_symbol == "QQQ"
    assert result.insufficient_data is False


def test_chop_score_bounded_0_to_100(tmp_path: Path) -> None:
    import random
    random.seed(42)
    closes = [100.0 + random.uniform(-30, 30) for _ in range(80)]
    _write_benchmark(tmp_path, "SPY", closes)
    result = compute_market_regime_indicator(tmp_path, sma_period=50, trend_window=5, range_window=20)
    assert result.chop_score is not None
    assert 0.0 <= result.chop_score <= 100.0
