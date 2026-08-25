"""Tests for dip_buy_meanreversion_strategy.py (R14, 2026-08-25).

SHADOW-MODE-ONLY strategy: generate() must never be wired to real orders in
this file's scope (that's enforced by paper_demo.py wiring, not testable
here), but must correctly mirror BreakoutMomentumStrategy's condition and
must never raise on missing/malformed feature data. log_shadow() must never
raise and must only write JSONL when a path is given.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from stock_swing.feature_engine.base_feature import FeatureResult
from stock_swing.strategy_engine.dip_buy_meanreversion_strategy import (
    DipBuyMeanReversionStrategy,
    DipBuySignalConfig,
    log_shadow,
)


def _momentum_feature(
    symbol: str,
    momentum: float,
    trend: str,
    quality_flags: list[str] | None = None,
    bars_used: int = 20,
) -> FeatureResult:
    return FeatureResult(
        feature_name="price_momentum",
        symbol=symbol,
        computed_at=datetime.now(timezone.utc),
        values={
            "momentum": momentum,
            "trend": trend,
            "bars_used": bars_used,
            "latest_close": 100.0,
            "atr": 2.0,
        },
        metadata={},
        quality_flags=quality_flags or [],
    )


# ── generate(): mirror-image entry condition ─────────────────────────────── #

def test_fires_on_bearish_drop_beyond_threshold():
    strat = DipBuyMeanReversionStrategy()
    features = [_momentum_feature("NVDA", momentum=-0.08, trend="bearish")]
    signals = strat.generate(features)
    assert len(signals) == 1
    assert signals[0].symbol == "NVDA"
    assert signals[0].action == "buy"
    assert signals[0].strategy_id == "dip_buy_meanreversion_v1_shadow"


def test_does_not_fire_below_drop_threshold():
    strat = DipBuyMeanReversionStrategy()
    features = [_momentum_feature("NVDA", momentum=-0.03, trend="bearish")]
    signals = strat.generate(features)
    assert signals == []


def test_does_not_fire_on_bullish_trend_even_if_momentum_negative_check():
    """Sanity: bullish trend with a small positive momentum never fires."""
    strat = DipBuyMeanReversionStrategy()
    features = [_momentum_feature("NVDA", momentum=0.06, trend="bullish")]
    signals = strat.generate(features)
    assert signals == []


def test_does_not_fire_on_neutral_trend():
    strat = DipBuyMeanReversionStrategy()
    features = [_momentum_feature("NVDA", momentum=-0.06, trend="neutral")]
    signals = strat.generate(features)
    assert signals == []


def test_boundary_exactly_at_threshold_fires():
    strat = DipBuyMeanReversionStrategy(DipBuySignalConfig(min_momentum_drop=0.05))
    features = [_momentum_feature("NVDA", momentum=-0.05, trend="bearish")]
    signals = strat.generate(features)
    assert len(signals) == 1


def test_signal_strength_scales_with_drop_magnitude():
    strat = DipBuyMeanReversionStrategy()
    small_drop = strat.generate([_momentum_feature("A", momentum=-0.05, trend="bearish")])
    big_drop = strat.generate([_momentum_feature("B", momentum=-0.20, trend="bearish")])
    assert small_drop[0].signal_strength < big_drop[0].signal_strength
    assert big_drop[0].signal_strength <= 1.0


def test_signal_strength_floored_at_min_signal_strength():
    strat = DipBuyMeanReversionStrategy(
        DipBuySignalConfig(min_momentum_drop=0.05, min_signal_strength=0.40)
    )
    signals = strat.generate([_momentum_feature("A", momentum=-0.05, trend="bearish")])
    assert signals[0].signal_strength >= 0.40


def test_skips_symbols_with_blocking_quality_flags():
    strat = DipBuyMeanReversionStrategy()
    features = [
        _momentum_feature("A", momentum=-0.10, trend="bearish", quality_flags=["stale_data"]),
        _momentum_feature("B", momentum=-0.10, trend="bearish", quality_flags=["insufficient_bars"]),
        _momentum_feature("C", momentum=-0.10, trend="bearish"),
    ]
    signals = strat.generate(features)
    assert [s.symbol for s in signals] == ["C"]


def test_ignores_non_momentum_features():
    strat = DipBuyMeanReversionStrategy()
    other = FeatureResult(
        feature_name="macro_regime", symbol=None, computed_at=datetime.now(timezone.utc),
        values={"regime": "expansion"}, metadata={}, quality_flags=[],
    )
    signals = strat.generate([other])
    assert signals == []


def test_empty_features_returns_empty_list():
    strat = DipBuyMeanReversionStrategy()
    assert strat.generate([]) == []


def test_disabled_config_returns_no_signals():
    strat = DipBuyMeanReversionStrategy(DipBuySignalConfig(disabled=True))
    features = [_momentum_feature("NVDA", momentum=-0.20, trend="bearish")]
    assert strat.generate(features) == []


def test_metadata_includes_momentum_and_trend():
    strat = DipBuyMeanReversionStrategy()
    signals = strat.generate([_momentum_feature("NVDA", momentum=-0.10, trend="bearish")])
    assert signals[0].metadata["momentum"] == -0.10
    assert signals[0].metadata["trend"] == "bearish"


def test_reasoning_tags_shadow_only():
    strat = DipBuyMeanReversionStrategy()
    signals = strat.generate([_momentum_feature("NVDA", momentum=-0.10, trend="bearish")])
    assert "SHADOW-ONLY" in signals[0].reasoning
    assert "R14" in signals[0].reasoning


# ── config from env ──────────────────────────────────────────────────────── #

def test_config_from_env_defaults(monkeypatch):
    monkeypatch.delenv("DIP_BUY_MIN_MOMENTUM_DROP", raising=False)
    monkeypatch.delenv("DIP_BUY_MIN_SIGNAL_STRENGTH", raising=False)
    monkeypatch.delenv("DIP_BUY_SHADOW_DISABLED", raising=False)
    cfg = DipBuySignalConfig.from_env()
    assert cfg.min_momentum_drop == 0.05
    assert cfg.min_signal_strength == 0.40
    assert cfg.disabled is False


def test_config_from_env_overrides(monkeypatch):
    monkeypatch.setenv("DIP_BUY_MIN_MOMENTUM_DROP", "0.08")
    monkeypatch.setenv("DIP_BUY_MIN_SIGNAL_STRENGTH", "0.5")
    monkeypatch.setenv("DIP_BUY_SHADOW_DISABLED", "true")
    cfg = DipBuySignalConfig.from_env()
    assert cfg.min_momentum_drop == 0.08
    assert cfg.min_signal_strength == 0.5
    assert cfg.disabled is True


# ── log_shadow(): never raises, writes JSONL only when path given ──────── #

def test_log_shadow_writes_jsonl(tmp_path):
    strat = DipBuyMeanReversionStrategy()
    signal = strat.generate([_momentum_feature("NVDA", momentum=-0.10, trend="bearish")])[0]
    log_path = tmp_path / "dip_buy_meanreversion_shadow_log.jsonl"
    log_shadow(signal, shadow_log_path=log_path)

    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["symbol"] == "NVDA"
    assert record["mode"] == "shadow"
    assert record["strategy_id"] == "dip_buy_meanreversion_v1_shadow"


def test_log_shadow_without_path_does_not_raise():
    strat = DipBuyMeanReversionStrategy()
    signal = strat.generate([_momentum_feature("NVDA", momentum=-0.10, trend="bearish")])[0]
    log_shadow(signal, shadow_log_path=None)  # must not raise


def test_log_shadow_appends_multiple_records(tmp_path):
    strat = DipBuyMeanReversionStrategy()
    log_path = tmp_path / "dip_buy_meanreversion_shadow_log.jsonl"
    for sym in ("A", "B", "C"):
        signal = strat.generate([_momentum_feature(sym, momentum=-0.10, trend="bearish")])[0]
        log_shadow(signal, shadow_log_path=log_path)
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
