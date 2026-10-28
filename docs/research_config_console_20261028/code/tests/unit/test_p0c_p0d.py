"""Tests for P0-C (sizing price source) and P0-D (stale position exit guard)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

from stock_swing.core.runtime import RuntimeMode
from stock_swing.execution.paper_executor import PaperExecutor


class _BrokerWithFreshBar:
    def fetch_account(self):
        return SimpleNamespace(payload={"equity": "100000", "buying_power": "50000"})

    def fetch_positions(self):
        return SimpleNamespace(payload=[])

    def fetch_bars(self, symbol, **kwargs):
        return SimpleNamespace(
            payload={"bars": [{"c": 245.09, "t": datetime.now(timezone.utc).isoformat()}]}
        )

    def submit_order(self, **kwargs):
        return {"id": "order-123"}


class _BrokerWithStaleBar:
    def fetch_account(self):
        return SimpleNamespace(payload={"equity": "100000", "buying_power": "50000"})

    def fetch_positions(self):
        return SimpleNamespace(payload=[])

    def fetch_bars(self, symbol, **kwargs):
        stale_ts = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        return SimpleNamespace(payload={"bars": [{"c": 2010.21, "t": stale_ts}]})

    def submit_order(self, **kwargs):
        return {"id": "order-456"}


def _make_decision(symbol: str, latest_close: float, limit_price: float = 0.0):
    return SimpleNamespace(
        decision_id=str(uuid.uuid4()),
        schema_version="v1",
        generated_at=datetime.now(timezone.utc),
        mode="paper",
        strategy_id="test",
        strategy_version_id="test-v1",
        symbol=symbol,
        action="buy",
        confidence=0.75,
        signal_strength=0.80,
        risk_state="pass",
        deny_reasons=[],
        requires_operator_approval=False,
        time_horizon="short",
        evidence={"latest_close": latest_close, "market_regime": "neutral"},
        proposed_order=SimpleNamespace(
            side="buy",
            symbol=symbol,
            order_type="market",
            qty=10,
            time_in_force="day",
            limit_price=limit_price if limit_price > 0 else None,
        ),
        sizing=None,
    )


def test_p0c_decision_latest_close_takes_priority_over_fresh_bar():
    executor = PaperExecutor(RuntimeMode.PAPER, _BrokerWithFreshBar())
    decision = _make_decision("AAPL", latest_close=245.09)
    qty, details = executor._calculate_position_size(decision, market_regime="neutral")
    assert qty > 0
    assert details.get("price_source") == "decision_latest_close"


def test_p0c_stale_bar_falls_back_to_decision_latest_close():
    executor = PaperExecutor(RuntimeMode.PAPER, _BrokerWithStaleBar())
    decision = _make_decision("KLAC", latest_close=245.09)
    qty, details = executor._calculate_position_size(decision, market_regime="neutral")
    assert qty > 0
    assert details.get("price_source") == "decision_latest_close"
    assert abs(details.get("current_price", 0) - 245.09) < 0.01


def test_p0d_stale_position_price_does_not_trigger_exit():
    from stock_swing.feature_engine.base_feature import FeatureResult
    from stock_swing.strategy_engine.simple_exit_v2_strategy import SimpleExitV2Strategy

    strategy = SimpleExitV2Strategy(
        stop_loss_pct=-0.07,
        breakeven_activation_pct=0.03,
        trailing_activation_pct=0.08,
        trailing_stop_pct=0.04,
        max_hold_days=20,
    )
    features = [
        FeatureResult(
            feature_name="price_momentum",
            symbol="KLAC",
            computed_at=datetime.now(timezone.utc),
            quality_flags=[],
            values={"latest_close": 245.09, "momentum": 0.01, "trend": "up", "bars_used": 20},
        )
    ]
    positions = {
        "KLAC": {
            "qty": "10",
            "avg_entry_price": "245.09",
            "current_price": "2010.21",
            "unrealized_plpc": "7.21",
        }
    }
    signals = strategy.generate(features, positions)
    sell_signals = [s for s in signals if s.action == "sell"]
    assert len(sell_signals) == 0


def test_p0d_fresh_position_price_can_trigger_exit():
    from stock_swing.feature_engine.base_feature import FeatureResult
    from stock_swing.strategy_engine.simple_exit_v2_strategy import SimpleExitV2Strategy

    strategy = SimpleExitV2Strategy(stop_loss_pct=-0.07)
    features = [
        FeatureResult(
            feature_name="price_momentum",
            symbol="AAPL",
            computed_at=datetime.now(timezone.utc),
            quality_flags=[],
            values={"latest_close": 130.0, "momentum": -0.10},
        )
    ]
    positions = {
        "AAPL": {
            "qty": "10",
            "avg_entry_price": "150.0",
            "current_price": "130.0",
        }
    }
    signals = strategy.generate(features, positions)
    sell_signals = [s for s in signals if s.action == "sell"]
    assert len(sell_signals) == 1
