"""R13-C (2026-08-23): Unit tests for scripts/r11_backtest_engine_v3.py's
conservative OHLC-path exit re-simulation (roadmap item 3) and slippage
modeling (roadmap item 5).

These build on tests/unit/test_r11_backtest_engine_v2.py's synthetic-cache
pattern (small deterministic price series, not real cached data) so a
future edit cannot silently make exits optimistic again or make slippage
a no-op without a test failing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from r11_backtest_engine_v3 import run_backtest_v3  # noqa: E402


@pytest.fixture
def intraday_dip_cache(tmp_path, monkeypatch):
    """A symbol whose CLOSE never breaches the stop_loss threshold, but
    whose intraday LOW does on one specific day, then recovers by close.
    Under conservative_ohlc=True this must trigger a stop_loss exit that
    day; under conservative_ohlc=False (close-only, v1/v2-equivalent) it
    must NOT.

    Simple exit v2 defaults used by load_exit_strategy() when config file
    has no override: stop_loss_pct default is read from
    config/strategy/simple_exit_v2.yaml (production config, -0.07 base for
    the "standard" conviction tier absent volatility adjustment). This
    fixture's breakout entry lands with signal_strength typically in the
    "standard" tier (uses base stop_loss_pct/trailing_activation_pct), so a
    day where low <= entry_price * (1 - 0.07-ish) should trigger under
    conservative OHLC.
    """
    import r11_backtest_engine_v3 as engine_v3
    import r11_backtest_engine as engine_v1
    import r11_backtest_engine_v2 as engine_v2

    cache_dir = tmp_path / "r11_price_cache"
    cache_dir.mkdir()

    # Enough flat days both before AND after the breakout that by the time
    # the dip day arrives, hold_days already exceeds every tiered_min_hold
    # tier (max is 7 trading days) -- this deliberately avoids the min-hold
    # suppression window entirely, so the test isolates ONLY the
    # conservative-OHLC-vs-close-only behavior difference, not an
    # interaction with SimpleExitV2Strategy's separate min-hold-days logic
    # (that logic is real production behavior, correctly reused here, but
    # is out of scope for what this test is checking).
    dates = [f"2025-01-{d:02d}" for d in range(1, 32)] + [f"2025-02-{d:02d}" for d in range(1, 11)]
    bars = {}
    price = 100.0
    for i, d in enumerate(dates):
        if i < 19:
            bars[d] = {"open": price, "high": price * 1.01, "low": price * 0.99, "close": price, "volume": 1_000_000}
        elif i == 19:
            new_close = price * 1.20  # breakout day
            bars[d] = {"open": price, "high": new_close * 1.01, "low": price * 0.99, "close": new_close, "volume": 2_000_000}
            price = new_close
        elif i == 20:
            # fill day: t+1 open, flat
            bars[d] = {"open": price, "high": price * 1.01, "low": price * 0.99, "close": price, "volume": 1_000_000}
        elif 21 <= i < 30:
            # hold flat for 9 more trading days (hold_days will be ~10 by
            # the dip day, well past the 7-day max tiered_min_hold tier)
            bars[d] = {"open": price, "high": price * 1.01, "low": price * 0.99, "close": price, "volume": 1_000_000}
        elif i == 30:
            # DIP DAY: intraday low crashes well past even the HIGH
            # conviction tier's -9% stop, but recovers to close roughly
            # flat (-1%, does not breach any tier's stop at close).
            dip_low = price * 0.80  # -20% intraday low
            bars[d] = {"open": price, "high": price * 1.02, "low": dip_low, "close": price * 0.99, "volume": 3_000_000}
        else:
            bars[d] = {"open": price, "high": price * 1.01, "low": price * 0.99, "close": price, "volume": 1_000_000}

    with open(cache_dir / "DIPSTOCK.json", "w") as f:
        json.dump(bars, f)

    monkeypatch.setattr(engine_v3, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(engine_v1, "CACHE_DIR", cache_dir)

    intro_dates_path = cache_dir / "_symbol_universe_intro_dates.json"
    with open(intro_dates_path, "w") as f:
        json.dump({"DIPSTOCK": "2024-01-01"}, f)
    monkeypatch.setattr(engine_v2, "INTRO_DATES_PATH", intro_dates_path)

    return {"cache_dir": cache_dir, "dates": dates, "bars": bars}


class TestConservativeOhlcExitTriggersOnIntradayLow:
    def test_conservative_mode_exits_on_dip_day_via_low(self, intraday_dip_cache):
        result = run_backtest_v3(
            symbols=["DIPSTOCK"],
            notional=10_000.0,
            enforce_point_in_time_universe=False,
            conservative_ohlc=True,
            slippage_bps=0.0,
        )
        trades = result["trades"]
        assert trades, "expected at least one closed trade"
        # The stop-triggered trade must exit on or before the dip day, via
        # stop_loss or trailing_stop/breakeven -- NOT ride through to a
        # much later date, since the intraday low breached every
        # reasonable conviction tier's stop threshold well past min_hold.
        dip_day = "2025-01-31"
        stop_triggered = [
            t for t in trades
            if t["exit_reason"] in ("stop_loss", "trailing_stop", "breakeven_stop")
            and t["exit_date"] <= dip_day
        ]
        assert stop_triggered, (
            f"expected a stop/trailing/breakeven exit on or before the dip day "
            f"({dip_day}) under conservative_ohlc=True; got trades={trades}"
        )

    def test_close_only_mode_does_not_exit_on_dip_day(self, intraday_dip_cache):
        result = run_backtest_v3(
            symbols=["DIPSTOCK"],
            notional=10_000.0,
            enforce_point_in_time_universe=False,
            conservative_ohlc=False,
            slippage_bps=0.0,
        )
        trades = result["trades"]
        dip_day = "2025-01-31"
        exits_on_dip_day = [t for t in trades if t["exit_date"] == dip_day]
        # Close-only mode only sees the day's CLOSE (~99% of entry, a mild
        # gain/flat position, no threshold breach) -- it must NOT register
        # an exit on the dip day itself.
        assert exits_on_dip_day == [], (
            "close-only (v1/v2-equivalent) mode should not react to the "
            "intraday low; it only ever sees the day's close"
        )


class TestSlippageAppliedUnfavorablyOnBothLegs:
    def test_higher_slippage_reduces_or_equals_net_pnl(self, intraday_dip_cache):
        no_slippage = run_backtest_v3(
            symbols=["DIPSTOCK"], notional=10_000.0,
            enforce_point_in_time_universe=False, conservative_ohlc=True, slippage_bps=0.0,
        )["trades"]
        with_slippage = run_backtest_v3(
            symbols=["DIPSTOCK"], notional=10_000.0,
            enforce_point_in_time_universe=False, conservative_ohlc=True, slippage_bps=25.0,
        )["trades"]
        assert no_slippage and with_slippage
        net_no_slip = sum(t["pnl"] for t in no_slippage)
        net_with_slip = sum(t["pnl"] for t in with_slippage)
        assert net_with_slip < net_no_slip, (
            "25bp one-way slippage on both entry and exit legs must strictly "
            "reduce net PnL relative to the frictionless baseline"
        )

    def test_slippage_widens_entry_and_narrows_exit_price(self, intraday_dip_cache):
        no_slippage = run_backtest_v3(
            symbols=["DIPSTOCK"], notional=10_000.0,
            enforce_point_in_time_universe=False, conservative_ohlc=True, slippage_bps=0.0,
        )["trades"]
        with_slippage = run_backtest_v3(
            symbols=["DIPSTOCK"], notional=10_000.0,
            enforce_point_in_time_universe=False, conservative_ohlc=True, slippage_bps=100.0,  # 1% one-way, exaggerated for clarity
        )["trades"]
        assert len(no_slippage) == len(with_slippage)
        for t_base, t_slip in zip(no_slippage, with_slippage):
            # entry_price should be HIGHER with slippage (paying more to buy)
            assert t_slip["entry_price"] > t_base["entry_price"]
            # exit_price should be LOWER with slippage (receiving less to sell)
            assert t_slip["exit_price"] < t_base["exit_price"]


class TestExitPriorityOrderPreservedUnderConservativeMode:
    def test_trailing_stop_checked_before_stop_loss(self, tmp_path, monkeypatch):
        """A position deep in profit (trailing active) that also has a low
        breaching a hypothetical stop_loss level on the SAME day must exit
        via trailing_stop, not stop_loss -- matching SimpleExitV2Strategy's
        real generate() priority order (trailing_stop checked first).
        """
        import r11_backtest_engine_v3 as engine_v3
        import r11_backtest_engine as engine_v1
        import r11_backtest_engine_v2 as engine_v2

        cache_dir = tmp_path / "r11_price_cache"
        cache_dir.mkdir()
        dates = [f"2025-02-{d:02d}" for d in range(1, 21)]
        bars = {}
        price = 100.0
        for i, d in enumerate(dates):
            if i < 19:
                bars[d] = {"open": price, "high": price * 1.01, "low": price * 0.99, "close": price, "volume": 1_000_000}
            else:
                new_close = price * 1.30  # big breakout to guarantee entry + later big run-up
                bars[d] = {"open": price, "high": new_close * 1.01, "low": price * 0.99, "close": new_close, "volume": 2_000_000}
                price = new_close
        with open(cache_dir / "RUNNER.json", "w") as f:
            json.dump(bars, f)

        # Extend with a strong further rally (trailing activates), then a
        # day with a wide low/high range that would breach BOTH a stop_loss
        # level (relative to entry) AND a trailing-stop level (relative to
        # peak) -- trailing must win per production priority order.
        extra_dates = [f"2025-03-{d:02d}" for d in range(1, 11)]
        all_dates = dates + extra_dates
        for i, d in enumerate(extra_dates):
            if i < 5:
                price *= 1.10  # keep rallying, establishes a high peak
                bars[d] = {"open": price / 1.10, "high": price * 1.01, "low": price * 0.98, "close": price, "volume": 1_000_000}
            elif i == 5:
                # crash day: low breaches both stop_loss-from-entry and
                # trailing-stop-from-peak
                peak_before = price
                bars[d] = {
                    "open": price, "high": price * 1.0,
                    "low": peak_before * 0.5,  # deep low, breaches everything
                    "close": peak_before * 0.95, "volume": 3_000_000,
                }
            else:
                bars[d] = {"open": price, "high": price * 1.01, "low": price * 0.99, "close": price, "volume": 500_000}

        with open(cache_dir / "RUNNER.json", "w") as f:
            json.dump(bars, f)

        monkeypatch.setattr(engine_v3, "CACHE_DIR", cache_dir)
        monkeypatch.setattr(engine_v1, "CACHE_DIR", cache_dir)
        intro_dates_path = cache_dir / "_symbol_universe_intro_dates.json"
        with open(intro_dates_path, "w") as f:
            json.dump({"RUNNER": "2024-01-01"}, f)
        monkeypatch.setattr(engine_v2, "INTRO_DATES_PATH", intro_dates_path)

        result = run_backtest_v3(
            symbols=["RUNNER"], notional=10_000.0,
            enforce_point_in_time_universe=False, conservative_ohlc=True, slippage_bps=0.0,
        )
        trades = result["trades"]
        assert trades, "expected at least one trade"
        # Whichever trade closes during/after the crash day should be
        # trailing_stop (position was deep in profit with an activated
        # trailing rule), not stop_loss.
        crash_trades = [t for t in trades if t["pnl"] > 0]
        assert crash_trades, f"expected a profitable exit from the rally; got {trades}"
        assert any(t["exit_reason"] == "trailing_stop" for t in crash_trades), (
            f"expected trailing_stop to take priority over stop_loss for a "
            f"deep-in-profit position; got exit_reasons={[t['exit_reason'] for t in trades]}"
        )
