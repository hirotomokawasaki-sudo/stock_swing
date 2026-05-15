"""Tests for stale price data detection and handling."""

from datetime import datetime, timedelta, timezone
from stock_swing.core.types import CanonicalRecord
from stock_swing.feature_engine.price_momentum_feature import PriceMomentumFeature
from stock_swing.strategy_engine.simple_exit_v2_strategy import SimpleExitV2Strategy


def test_price_momentum_detects_stale_data():
    """PriceMomentumFeature should flag data older than 7 days."""
    now = datetime.now(timezone.utc)
    
    # Create stale bars (10 days old, need at least 2 bars)
    stale_time = now - timedelta(days=10)
    stale_records = [
        CanonicalRecord(
            record_id="stale-1",
            schema_version="v1",
            source="broker",
            source_type="price",
            event_type="bar_daily",
            symbol="TTEQ",
            event_time=stale_time - timedelta(days=1),
            as_of=(stale_time - timedelta(days=1)).isoformat(),
            ingested_at=now,
            timezone="UTC",
            payload_version="v1",
            payload={"close": 35.50, "high": 36.00, "low": 35.00}
        ),
        CanonicalRecord(
            record_id="stale-2",
            schema_version="v1",
            source="broker",
            source_type="price",
            event_type="bar_daily",
            symbol="TTEQ",
            event_time=stale_time,
            as_of=stale_time.isoformat(),
            ingested_at=now,
            timezone="UTC",
            payload_version="v1",
            payload={"close": 36.36, "high": 36.50, "low": 36.00}
        )
    ]
    
    feature = PriceMomentumFeature(period_days=5)
    results = feature.compute(stale_records)
    
    assert len(results) == 1
    result = results[0]
    assert result.symbol == "TTEQ"
    assert "stale_data" in result.quality_flags
    assert result.values["data_age_days"] > 7


def test_price_momentum_accepts_fresh_data():
    """PriceMomentumFeature should not flag recent data."""
    now = datetime.now(timezone.utc)
    
    # Create fresh bars (2 days old, need at least 2 bars)
    fresh_time = now - timedelta(days=2)
    fresh_records = [
        CanonicalRecord(
            record_id="fresh-1",
            schema_version="v1",
            source="broker",
            source_type="price",
            event_type="bar_daily",
            symbol="AMZN",
            event_time=fresh_time - timedelta(days=1),
            as_of=(fresh_time - timedelta(days=1)).isoformat(),
            ingested_at=now,
            timezone="UTC",
            payload_version="v1",
            payload={"close": 265.00, "high": 268.00, "low": 263.00}
        ),
        CanonicalRecord(
            record_id="fresh-2",
            schema_version="v1",
            source="broker",
            source_type="price",
            event_type="bar_daily",
            symbol="AMZN",
            event_time=fresh_time,
            as_of=fresh_time.isoformat(),
            ingested_at=now,
            timezone="UTC",
            payload_version="v1",
            payload={"close": 268.00, "high": 270.00, "low": 265.00}
        )
    ]
    
    feature = PriceMomentumFeature(period_days=5)
    results = feature.compute(fresh_records)
    
    assert len(results) == 1
    result = results[0]
    assert result.symbol == "AMZN"
    assert "stale_data" not in result.quality_flags
    assert result.values["data_age_days"] <= 7


def test_simple_exit_v2_skips_stale_features():
    """SimpleExitV2 should skip stale feature prices and use position prices."""
    now = datetime.now(timezone.utc)
    
    # Create stale feature
    stale_time = now - timedelta(days=10)
    stale_feature = {
        "feature_name": "price_momentum",
        "symbol": "TTEQ",
        "computed_at": now,
        "values": {
            "latest_close": 36.36,  # Stale price
            "data_age_days": 10,
            "momentum": 0.05,
            "trend": "bullish"
        },
        "quality_flags": ["stale_data"],
        "metadata": {}
    }
    
    # Mock FeatureResult
    from stock_swing.feature_engine.base_feature import FeatureResult
    stale_feature_result = FeatureResult(**stale_feature)
    
    # Current position with fresh price
    current_positions = {
        "TTEQ": {
            "qty": 1500,
            "avg_entry_price": 41.00,
            "current_price": 40.50,  # Fresh from broker
            "created_at": (now - timedelta(hours=2)).isoformat()
        }
    }
    
    strategy = SimpleExitV2Strategy(
        stop_loss_pct=-0.07,
        trailing_activation_pct=0.05,
        trailing_stop_pct=0.03,
        max_hold_days=9
    )
    
    signals = strategy.generate(
        features=[stale_feature_result],
        current_positions=current_positions
    )
    
    # Should not trigger stop loss with fresh price ($40.50 vs $41.00 = -1.2%)
    # but would trigger with stale price ($36.36 vs $41.00 = -11.3%)
    assert len(signals) == 0, "Should not generate exit signal with fresh position price"


def test_simple_exit_v2_uses_position_price_priority():
    """SimpleExitV2 should prioritize position current_price over feature prices."""
    now = datetime.now(timezone.utc)
    
    # Create fresh feature with different price
    fresh_feature = {
        "feature_name": "price_momentum",
        "symbol": "AMZN",
        "computed_at": now,
        "values": {
            "latest_close": 250.00,  # Feature price
            "data_age_days": 1,
            "momentum": 0.03,
            "trend": "neutral"
        },
        "quality_flags": [],
        "metadata": {}
    }
    
    from stock_swing.feature_engine.base_feature import FeatureResult
    fresh_feature_result = FeatureResult(**fresh_feature)
    
    # Current position with different fresh price
    current_positions = {
        "AMZN": {
            "qty": 300,
            "avg_entry_price": 268.00,
            "current_price": 263.00,  # Position price (should be used)
            "created_at": (now - timedelta(hours=1)).isoformat()
        }
    }
    
    strategy = SimpleExitV2Strategy(
        stop_loss_pct=-0.07,
        trailing_activation_pct=0.05,
        trailing_stop_pct=0.03,
        max_hold_days=9
    )
    
    signals = strategy.generate(
        features=[fresh_feature_result],
        current_positions=current_positions
    )
    
    # With position price ($263 vs $268 = -1.9%): no exit
    # With feature price ($250 vs $268 = -6.7%): no exit (just under -7%)
    assert len(signals) == 0
    
    # Now test with stop loss trigger
    current_positions["AMZN"]["current_price"] = 248.00  # -7.5% loss
    signals = strategy.generate(
        features=[fresh_feature_result],
        current_positions=current_positions
    )
    
    assert len(signals) == 1
    signal = signals[0]
    assert signal.action == "sell"
    assert signal.metadata["price_source"] == "position"
    assert signal.metadata["current_price"] == 248.00  # Used position price
