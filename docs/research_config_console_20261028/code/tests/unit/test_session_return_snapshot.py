"""Regression coverage for the 2026-10-14 stale sector-return incident."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from stock_swing.feature_engine.base_feature import FeatureResult
from stock_swing.risk.session_return_snapshot import build_session_return_observations
from stock_swing.risk.shock_aware_staged_exit import (
    ShockAwareStagedExitConfig,
    build_shock_aware_staged_exit_plan,
)
from stock_swing.strategy_engine.sector_shock_hold import (
    SectorShockAnalyzer,
    SectorShockHoldConfig,
)


RUN_AT = datetime(2026, 10, 14, 19, 55, tzinfo=timezone.utc)  # 15:55 ET


def _feature(
    symbol: str,
    *,
    latest_time: str,
    latest_close: float,
    return_1d: float,
) -> FeatureResult:
    return FeatureResult(
        feature_name="price_momentum",
        symbol=symbol,
        computed_at=RUN_AT,
        values={"latest_close": latest_close, "return_1d": return_1d},
        metadata={"latest_time": latest_time},
    )


def _benchmark_files(tmp_path, rows: str = ""):
    prices = tmp_path / "benchmark_prices.csv"
    returns = tmp_path / "benchmark_returns.csv"
    prices.write_text("date,symbol,open,high,low,close,volume\n" + rows, encoding="utf-8")
    returns.write_text(
        "date,symbol,close,daily_return,return_3d\n"
        "2026-10-13,QQQ,743.57,-0.001,0.002\n",
        encoding="utf-8",
    )
    return prices, returns


def test_1014_live_quote_uses_previous_completed_close(tmp_path):
    """Incident 2026-10-14: intraday AMAT return must use the live quote."""
    prices, returns = _benchmark_files(
        tmp_path,
        "2026-10-13,QQQ,739.52,744.2,738.83,743.57,1\n",
    )
    feature = _feature(
        "AMAT",
        latest_time="2026-10-13T20:00:00+00:00",
        latest_close=471.03,
        return_1d=0.01,
    )
    quotes = {"AMAT": 453.18, "QQQ": 728.95}

    observations = build_session_return_observations(
        features=[feature],
        symbols={"AMAT", "QQQ"},
        get_mid_price=quotes.__getitem__,
        now_utc=RUN_AT,
        benchmark_prices_path=prices,
        benchmark_returns_path=returns,
    )

    assert observations["AMAT"].is_valid
    assert observations["AMAT"].return_pct == pytest.approx(453.18 / 471.03 - 1)
    assert observations["QQQ"].return_pct == pytest.approx(728.95 / 743.57 - 1)
    assert observations["AMAT"].expected_session_date == "2026-10-13"


def test_stale_feature_never_becomes_current_session_return(tmp_path):
    prices, returns = _benchmark_files(tmp_path)
    feature = _feature(
        "AMAT",
        latest_time="2026-10-12T20:00:00+00:00",
        latest_close=480.0,
        return_1d=-0.01,
    )
    observations = build_session_return_observations(
        features=[feature],
        symbols={"AMAT"},
        get_mid_price=lambda _symbol: 453.18,
        now_utc=RUN_AT,
        benchmark_prices_path=prices,
        benchmark_returns_path=returns,
    )
    assert not observations["AMAT"].is_valid
    assert observations["AMAT"].reason == "missing_exact_date_daily_reference"


def test_in_progress_daily_bar_derives_previous_close(tmp_path):
    prices, returns = _benchmark_files(tmp_path)
    feature = _feature(
        "AMAT",
        latest_time="2026-10-14T13:30:00+00:00",
        latest_close=453.18,
        return_1d=453.18 / 471.03 - 1,
    )
    observations = build_session_return_observations(
        features=[feature],
        symbols={"AMAT"},
        get_mid_price=lambda _symbol: 453.18,
        now_utc=RUN_AT,
        benchmark_prices_path=prices,
        benchmark_returns_path=returns,
    )
    assert observations["AMAT"].previous_close == pytest.approx(471.03)
    assert observations["AMAT"].return_pct == pytest.approx(453.18 / 471.03 - 1)


def test_after_close_uses_exact_completed_daily_return(tmp_path):
    prices, returns = _benchmark_files(tmp_path)
    feature = _feature(
        "AMAT",
        latest_time="2026-10-14T20:00:00+00:00",
        latest_close=453.18,
        return_1d=-0.0379,
    )
    observations = build_session_return_observations(
        features=[feature],
        symbols={"AMAT"},
        get_mid_price=lambda _symbol: (_ for _ in ()).throw(AssertionError("no quote")),
        now_utc=datetime(2026, 10, 14, 20, 5, tzinfo=timezone.utc),
        benchmark_prices_path=prices,
        benchmark_returns_path=returns,
    )
    assert observations["AMAT"].is_valid
    assert observations["AMAT"].return_pct == pytest.approx(-0.0379)


def test_missing_or_corrupt_reference_files_fail_closed(tmp_path):
    prices = tmp_path / "missing_prices.csv"
    returns = tmp_path / "bad_returns.csv"
    returns.write_bytes(b"\xff\xfe")
    observations = build_session_return_observations(
        features=[],
        symbols={"QQQ"},
        get_mid_price=lambda _symbol: 700.0,
        now_utc=RUN_AT,
        benchmark_prices_path=prices,
        benchmark_returns_path=returns,
    )
    assert not observations["QQQ"].is_valid
    assert observations["QQQ"].return_pct is None


def test_missing_live_quote_fails_closed(tmp_path):
    prices, returns = _benchmark_files(
        tmp_path,
        "2026-10-13,QQQ,739.52,744.2,738.83,743.57,1\n",
    )
    observations = build_session_return_observations(
        features=[],
        symbols={"QQQ"},
        get_mid_price=lambda _symbol: 0.0,
        now_utc=RUN_AT,
        benchmark_prices_path=prices,
        benchmark_returns_path=returns,
    )
    assert not observations["QQQ"].is_valid
    assert observations["QQQ"].reason == "missing_live_quote"


def test_1014_asof_open_replay_is_soft_stop_without_full_day_lookahead(tmp_path):
    prices, returns = _benchmark_files(
        tmp_path,
        "2026-10-13,AMAT,0,0,0,464.24,1\n"
        "2026-10-13,SMH,0,0,0,588.12,1\n"
        "2026-10-13,SOXX,0,0,0,543.90,1\n"
        "2026-10-13,QQQ,0,0,0,743.57,1\n"
        "2026-10-13,SPY,0,0,0,778.01,1\n",
    )
    quotes = {
        "AMAT": 453.18,
        "SMH": 575.93,
        "SOXX": 530.98,
        "QQQ": 737.92,
        "SPY": 775.00,
    }
    observations = build_session_return_observations(
        features=[],
        symbols=quotes,
        get_mid_price=quotes.__getitem__,
        now_utc=datetime(2026, 10, 14, 13, 25, tzinfo=timezone.utc),
        benchmark_prices_path=prices,
        benchmark_returns_path=returns,
    )
    classification = SectorShockAnalyzer(SectorShockHoldConfig()).classify(
        symbol="AMAT",
        current_return_pct=-0.1282,
        symbol_1d_return_pct=observations["AMAT"].return_pct,
        sector_1d_return_pcts={
            symbol: observations[symbol].return_pct
            for symbol in ("SMH", "SOXX", "QQQ", "SPY")
        },
        days_held=6,
    )
    plan = build_shock_aware_staged_exit_plan(
        symbol="AMAT",
        exit_trigger="Stop loss triggered",
        baseline_qty=144,
        classification=classification,
        current_return_pct=-0.1282,
        config=ShockAwareStagedExitConfig(),
    )
    assert classification.classification == "soft_stop"
    assert plan.would_stage
    assert plan.treatment_exit_qty == 48
