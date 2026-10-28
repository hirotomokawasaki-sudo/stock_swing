"""R13-C (2026-08-24) roadmap item 4: unit tests for scripts/
r11_backtest_engine_v4.py's gross exposure / sector cap / correlation
cluster cap enforcement.

These build on test_r11_backtest_engine_v3.py's synthetic-cache pattern
(small deterministic price series, not real cached data) so a future edit
cannot silently make the caps a no-op without a test failing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from r11_backtest_engine_v4 import run_backtest_v4  # noqa: E402


def _flat_then_breakout_bars(n_flat: int = 19, breakout_mult: float = 1.20) -> dict[str, dict]:
    """Same flat-then-breakout price pattern used by v2/v3's synthetic
    fixtures: flat for n_flat days, then a clean breakout that should trip
    BreakoutMomentumStrategy's default thresholds, then flat continuation.

    Deliberately kept to 25 total trading days (n_flat=19 + 1 breakout day +
    5 continuation days), matching v2's own synthetic fixture length --
    long enough for the t+1 fill and one full holding period to resolve,
    but SHORT of SimpleExitV2Strategy's max_hold_days=20 time-based exit
    threshold, so exactly one round-trip trade is produced per symbol (a
    second, later breakout/re-entry would otherwise occur once a
    time_based exit fires and the still-elevated price re-triggers the
    momentum signal -- out of scope for these capacity-cap-focused tests).
    """
    dates = [f"2025-01-{d:02d}" for d in range(1, 26)]
    bars = {}
    price = 100.0
    for i, d in enumerate(dates):
        if i < n_flat:
            bars[d] = {"open": price, "high": price * 1.01, "low": price * 0.99, "close": price, "volume": 1_000_000}
        elif i == n_flat:
            new_close = price * breakout_mult
            bars[d] = {"open": price, "high": new_close * 1.01, "low": price * 0.99, "close": new_close, "volume": 2_000_000}
            price = new_close
        else:
            bars[d] = {"open": price, "high": price * 1.01, "low": price * 0.99, "close": price, "volume": 1_000_000}
    return bars


@pytest.fixture
def two_semis_cache(tmp_path, monkeypatch):
    """Two symbols in the SAME real sector/cluster (per
    src/stock_swing/risk/position_sizing.py's SYMBOL_SECTORS and
    src/stock_swing/risk/correlation_cluster.py's CLUSTERS), both
    breaking out on the SAME day so they compete for the same capped
    capacity bucket. NVDA and AMD are both real 'semis' sector members
    and both real 'semis_us'/'semis_combined' cluster members -- reusing
    the actual production mappings (not a synthetic fixture-only mapping)
    is deliberate so this test exercises the real imported constants.
    """
    import r11_backtest_engine_v4 as engine_v4
    import r11_backtest_engine as engine_v1

    cache_dir = tmp_path / "r11_price_cache"
    cache_dir.mkdir()

    bars = _flat_then_breakout_bars()
    for sym in ("NVDA", "AMD"):
        with open(cache_dir / f"{sym}.json", "w") as f:
            json.dump(bars, f)

    monkeypatch.setattr(engine_v4, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(engine_v1, "CACHE_DIR", cache_dir)

    intro_dates_path = cache_dir / "_symbol_universe_intro_dates.json"
    with open(intro_dates_path, "w") as f:
        json.dump({"NVDA": "2024-01-01", "AMD": "2024-01-01"}, f)

    import r11_backtest_engine_v2 as engine_v2
    monkeypatch.setattr(engine_v2, "INTRO_DATES_PATH", intro_dates_path)

    return {"cache_dir": cache_dir}


class TestGrossExposureCapDropsExcessEntries:
    def test_second_entry_dropped_when_gross_cap_too_tight_for_both(self, two_semis_cache):
        """notional=$10,000/trade, equity_base=$15,000, gross_exposure_cap_pct=100%
        -> cap = $15,000, which fits ONE $10,000 position but not a second.
        With caps disabled, both should enter; with caps enabled, only one.
        """
        capped = run_backtest_v4(
            symbols=["NVDA", "AMD"], notional=10_000.0, equity_base=15_000.0,
            enforce_point_in_time_universe=False, conservative_ohlc=False, slippage_bps=0.0,
            gross_exposure_cap_pct=1.0, sector_cap_pct=1.0,
            cluster_caps={"semis_us": 10.0, "semis_combined": 10.0},  # loosened: isolate gross-cap path
            enforce_caps=True,
        )
        uncapped = run_backtest_v4(
            symbols=["NVDA", "AMD"], notional=10_000.0, equity_base=15_000.0,
            enforce_point_in_time_universe=False, conservative_ohlc=False, slippage_bps=0.0,
            enforce_caps=False,
        )
        assert len(uncapped["trades"]) == 2, "sanity: without caps both symbols should enter"
        assert len(capped["trades"]) == 1, "gross exposure cap must drop the second entry"
        assert capped["capacity_dropped_count"] >= 1
        assert any(r.startswith("gross_exposure_cap") for r in capped["capacity_dropped_by_reason"])

    def test_caps_disabled_is_a_true_noop_matching_v3_behavior(self, two_semis_cache):
        """enforce_caps=False must produce IDENTICAL trades to a tight cap
        that would otherwise bind -- proving --no-caps genuinely disables
        capacity gating rather than just relaxing it.
        """
        result = run_backtest_v4(
            symbols=["NVDA", "AMD"], notional=10_000.0, equity_base=1.0,  # would force cap=$0 if enforced
            enforce_point_in_time_universe=False, conservative_ohlc=False, slippage_bps=0.0,
            gross_exposure_cap_pct=0.75, enforce_caps=False,
        )
        assert len(result["trades"]) == 2
        assert result["capacity_dropped_count"] == 0


class TestSectorCapDropsExcessEntries:
    def test_sector_cap_blocks_second_semis_entry_when_gross_cap_is_loose(self, two_semis_cache):
        """Set gross_exposure_cap_pct generously loose so it never binds,
        but sector_cap_pct tight enough that only one 'semis' position fits
        -- isolates the sector-cap code path specifically.
        """
        result = run_backtest_v4(
            symbols=["NVDA", "AMD"], notional=10_000.0, equity_base=15_000.0,
            enforce_point_in_time_universe=False, conservative_ohlc=False, slippage_bps=0.0,
            gross_exposure_cap_pct=10.0,  # effectively unlimited
            sector_cap_pct=1.0,           # cap = $15,000, fits one $10k position only
            cluster_caps={"semis_us": 10.0, "semis_combined": 10.0},  # loosened: isolate sector-cap path
            enforce_caps=True,
        )
        assert len(result["trades"]) == 1
        assert any(r.startswith("sector_cap:semis") for r in result["capacity_dropped_by_reason"])


class TestClusterCapDropsExcessEntries:
    def test_cluster_cap_blocks_second_entry_in_same_cluster(self, two_semis_cache):
        """Both NVDA and AMD are real members of the 'semis_us' cluster
        (src/stock_swing/risk/correlation_cluster.py). Set gross and sector
        caps loose, but override cluster_caps so 'semis_us' is tight enough
        to fit only one position.
        """
        result = run_backtest_v4(
            symbols=["NVDA", "AMD"], notional=10_000.0, equity_base=15_000.0,
            enforce_point_in_time_universe=False, conservative_ohlc=False, slippage_bps=0.0,
            gross_exposure_cap_pct=10.0,
            sector_cap_pct=10.0,
            cluster_caps={"semis_us": 1.0, "semis_combined": 10.0},
            enforce_caps=True,
        )
        assert len(result["trades"]) == 1
        assert any(r.startswith("cluster_cap:semis_us") for r in result["capacity_dropped_by_reason"])


class TestSignalStrengthPriorityOrdering:
    def test_stronger_signal_fills_first_when_capacity_is_scarce(self, tmp_path, monkeypatch):
        """When two symbols signal on the SAME day but only one fits under
        the gross cap, the symbol with the HIGHER signal_strength must be
        the one that gets filled (see module docstring's priority-order
        design decision).
        """
        import r11_backtest_engine_v4 as engine_v4
        import r11_backtest_engine as engine_v1
        import r11_backtest_engine_v2 as engine_v2

        cache_dir = tmp_path / "r11_price_cache"
        cache_dir.mkdir()

        # WEAK: a smaller breakout (lower signal_strength).
        weak_bars = _flat_then_breakout_bars(breakout_mult=1.09)
        # STRONG: a much larger breakout (higher signal_strength), same day.
        strong_bars = _flat_then_breakout_bars(breakout_mult=1.35)

        with open(cache_dir / "WEAKSIG.json", "w") as f:
            json.dump(weak_bars, f)
        with open(cache_dir / "STRONGSIG.json", "w") as f:
            json.dump(strong_bars, f)

        monkeypatch.setattr(engine_v4, "CACHE_DIR", cache_dir)
        monkeypatch.setattr(engine_v1, "CACHE_DIR", cache_dir)
        intro_dates_path = cache_dir / "_symbol_universe_intro_dates.json"
        with open(intro_dates_path, "w") as f:
            json.dump({"WEAKSIG": "2024-01-01", "STRONGSIG": "2024-01-01"}, f)
        monkeypatch.setattr(engine_v2, "INTRO_DATES_PATH", intro_dates_path)

        result = run_backtest_v4(
            symbols=["WEAKSIG", "STRONGSIG"], notional=10_000.0, equity_base=15_000.0,
            enforce_point_in_time_universe=False, conservative_ohlc=False, slippage_bps=0.0,
            gross_exposure_cap_pct=1.0,  # cap=$15,000, fits only ONE $10k position
            sector_cap_pct=10.0,
            enforce_caps=True,
        )
        filled_symbols = {t["symbol"] for t in result["trades"]}
        assert filled_symbols == {"STRONGSIG"}, (
            f"expected the higher-signal_strength symbol to win scarce capacity; "
            f"got filled_symbols={filled_symbols}"
        )


class TestCapacityDropAccounting:
    def test_capacity_dropped_count_matches_reason_breakdown_sum(self, two_semis_cache):
        result = run_backtest_v4(
            symbols=["NVDA", "AMD"], notional=10_000.0, equity_base=15_000.0,
            enforce_point_in_time_universe=False, conservative_ohlc=False, slippage_bps=0.0,
            gross_exposure_cap_pct=1.0, sector_cap_pct=1.0,
            cluster_caps={"semis_us": 10.0, "semis_combined": 10.0},
            enforce_caps=True,
        )
        assert result["capacity_dropped_count"] == sum(result["capacity_dropped_by_reason"].values())

    def test_zero_capacity_drops_when_nothing_binds(self, two_semis_cache):
        result = run_backtest_v4(
            symbols=["NVDA", "AMD"], notional=10_000.0, equity_base=1_000_000.0,
            enforce_point_in_time_universe=False, conservative_ohlc=False, slippage_bps=0.0,
            enforce_caps=True,
        )
        assert result["capacity_dropped_count"] == 0
        assert result["capacity_dropped_by_reason"] == {}
