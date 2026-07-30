from datetime import UTC, datetime, timezone

from stock_swing.feature_engine.base_feature import FeatureResult
from stock_swing.risk.open_shock_cooldown import apply_open_shock_cooldown
from stock_swing.strategy_engine.base_strategy import CandidateSignal


def _price_feature(symbol: str, previous_close: float) -> FeatureResult:
    return FeatureResult(
        feature_name="price_momentum",
        symbol=symbol,
        computed_at=datetime.now(timezone.utc),
        values={"latest_close": previous_close},
    )


def _exit_signal(
    symbol: str,
    reasoning: str,
    return_pct: float,
) -> CandidateSignal:
    return CandidateSignal(
        strategy_id="simple_exit_v2",
        symbol=symbol,
        action="sell",
        signal_strength=0.95,
        generated_at=datetime.now(timezone.utc),
        time_horizon="immediate",
        confidence=0.90,
        reasoning=reasoning,
        feature_refs=["position_tracking"],
        metadata={
            "return_pct": return_pct,
            "exit_trigger": reasoning.split(":")[0].strip(),
        },
    )


def test_open_shock_cooldown_inactive_outside_monday_window():
    features = [_price_feature("SPY", 100.0), _price_feature("QQQ", 100.0)]
    signal = _exit_signal("AAPL", "Trailing stop triggered: test", -0.03)

    prices = {"SPY": 97.0, "QQQ": 95.0, "AAPL": 90.0}
    result = apply_open_shock_cooldown(
        [signal],
        features,
        lambda symbol: prices.get(symbol, 0.0),
        now_utc=datetime(2026, 6, 9, 14, 0, tzinfo=UTC),
    )

    assert result.metrics.in_window is False
    assert result.metrics.active is False
    assert result.filtered_signals[0].action == "sell"


def test_open_shock_cooldown_holds_trailing_and_breakeven_when_market_shock_active():
    features = [
        _price_feature("SPY", 100.0),
        _price_feature("QQQ", 100.0),
        _price_feature("AAPL", 100.0),
        _price_feature("MSFT", 100.0),
        _price_feature("NVDA", 100.0),
    ]
    signals = [
        _exit_signal("AAPL", "Trailing stop triggered: pullback", -0.04),
        _exit_signal("MSFT", "Breakeven stop triggered: back to flat", -0.01),
    ]
    prices = {
        "SPY": 98.0,
        "QQQ": 97.5,
        "AAPL": 95.0,
        "MSFT": 96.0,
        "NVDA": 94.0,
    }

    result = apply_open_shock_cooldown(
        signals,
        features,
        lambda symbol: prices.get(symbol, 0.0),
        now_utc=datetime(2026, 6, 8, 13, 45, tzinfo=UTC),
    )

    assert result.metrics.in_window is True
    assert result.metrics.active is True
    assert result.metrics.signals_hit >= 2
    assert result.held_count == 2
    assert [signal.action for signal in result.filtered_signals] == ["hold", "hold"]
    assert result.filtered_signals[0].metadata["cooldown_blocked"] is True


def test_open_shock_cooldown_keeps_sell_for_catastrophic_loss():
    features = [
        _price_feature("SPY", 100.0),
        _price_feature("QQQ", 100.0),
        _price_feature("AAPL", 100.0),
        _price_feature("MSFT", 100.0),
    ]
    signal = _exit_signal("AAPL", "Stop loss triggered: loss", -0.13)
    prices = {
        "SPY": 98.5,
        "QQQ": 97.5,
        "AAPL": 88.0,
        "MSFT": 97.0,
    }

    result = apply_open_shock_cooldown(
        [signal],
        features,
        lambda symbol: prices.get(symbol, 0.0),
        now_utc=datetime(2026, 6, 8, 13, 40, tzinfo=UTC),
    )

    assert result.metrics.active is True
    assert result.held_count == 0
    assert result.forced_sell_count == 1
    assert result.filtered_signals[0].action == "sell"


def test_open_shock_cooldown_keeps_sell_for_single_name_crash_gap():
    features = [
        _price_feature("SPY", 100.0),
        _price_feature("QQQ", 100.0),
        _price_feature("AAPL", 100.0),
        _price_feature("MSFT", 100.0),
    ]
    signal = _exit_signal("AAPL", "Stop loss triggered: loss", -0.08)
    prices = {
        "SPY": 98.5,
        "QQQ": 97.5,
        "AAPL": 84.0,
        "MSFT": 97.0,
    }

    result = apply_open_shock_cooldown(
        [signal],
        features,
        lambda symbol: prices.get(symbol, 0.0),
        now_utc=datetime(2026, 6, 8, 13, 40, tzinfo=UTC),
    )

    assert result.metrics.active is True
    assert result.forced_sell_count == 1
    assert result.filtered_signals[0].action == "sell"


def test_open_shock_cooldown_holds_moderate_stop_loss_under_strong_market_shock():
    features = [
        _price_feature("SPY", 100.0),
        _price_feature("QQQ", 100.0),
        _price_feature("AAPL", 100.0),
        _price_feature("MSFT", 100.0),
        _price_feature("NVDA", 100.0),
    ]
    signal = _exit_signal("AAPL", "Stop loss triggered: loss", -0.07)
    prices = {
        "SPY": 98.0,
        "QQQ": 97.5,
        "AAPL": 93.0,
        "MSFT": 96.0,
        "NVDA": 95.0,
    }

    result = apply_open_shock_cooldown(
        [signal],
        features,
        lambda symbol: prices.get(symbol, 0.0),
        now_utc=datetime(2026, 6, 8, 13, 40, tzinfo=UTC),
    )

    assert result.metrics.active is True
    assert result.held_count == 1
    assert result.filtered_signals[0].action == "hold"
