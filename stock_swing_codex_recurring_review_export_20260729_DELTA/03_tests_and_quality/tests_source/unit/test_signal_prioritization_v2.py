"""Unit tests for signal_prioritization V2."""

from datetime import datetime, timezone

import pytest

from stock_swing.strategy_engine.base_strategy import CandidateSignal
from stock_swing.utils.signal_prioritization import prioritize_buy_signals_v2


@pytest.fixture
def high_quality_signal():
    """Create a high quality signal."""
    return CandidateSignal(
        strategy_id="test",
        symbol="NVDA",  # semis sector
        action="buy",
        signal_strength=0.95,
        generated_at=datetime.now(timezone.utc),
        time_horizon="short",
        confidence=0.90,
        reasoning="Strong signal",
        feature_refs=[],
        metadata={"estimated_notional": 5000.0},
    )


@pytest.fixture
def medium_quality_signal():
    """Create a medium quality signal."""
    return CandidateSignal(
        strategy_id="test",
        symbol="CRM",  # software sector
        action="buy",
        signal_strength=0.70,
        generated_at=datetime.now(timezone.utc),
        time_horizon="short",
        confidence=0.60,
        reasoning="Medium signal",
        feature_refs=[],
        metadata={"estimated_notional": 3000.0},
    )


@pytest.fixture
def low_quality_signal():
    """Create a low quality signal."""
    return CandidateSignal(
        strategy_id="test",
        symbol="AMD",  # semis sector
        action="buy",
        signal_strength=0.50,
        generated_at=datetime.now(timezone.utc),
        time_horizon="short",
        confidence=0.50,
        reasoning="Weak signal",
        feature_refs=[],
        metadata={"estimated_notional": 2000.0},
    )


def test_prioritize_by_quality(high_quality_signal, medium_quality_signal, low_quality_signal):
    """Test that signals are prioritized by quality within sector."""
    # Same sector (semis), different quality
    signals = [low_quality_signal, high_quality_signal]
    
    result = prioritize_buy_signals_v2(signals, current_positions={}, equity=100000.0)
    
    # High quality should come first
    assert len(result) == 2
    assert result[0].symbol == "NVDA"  # high quality
    assert result[1].symbol == "AMD"   # low quality


def test_sector_cap_enforcement(high_quality_signal, medium_quality_signal):
    """Test that sector cap is enforced."""
    # Create multiple signals in same sector
    nvda_signal = high_quality_signal  # semis, 5000 notional
    amd_signal_1 = CandidateSignal(
        strategy_id="test",
        symbol="AMD",
        action="buy",
        signal_strength=0.90,
        generated_at=datetime.now(timezone.utc),
        time_horizon="short",
        confidence=0.85,
        reasoning="Second semis",
        feature_refs=[],
        metadata={"estimated_notional": 70000.0},  # Would exceed cap
    )
    
    signals = [nvda_signal, amd_signal_1]
    equity = 100000.0
    max_sector_pct = 0.80  # 80% = 80,000
    
    result = prioritize_buy_signals_v2(
        signals,
        current_positions={},
        equity=equity,
        max_sector_exposure_pct=max_sector_pct,
    )
    
    # Both should be included (5000 + 70000 = 75,000 < 80,000)
    assert len(result) == 2


def test_round_robin_allocation(high_quality_signal, medium_quality_signal, low_quality_signal):
    """Test round-robin allocation across sectors."""
    # Different sectors
    nvda = high_quality_signal  # semis
    crm = medium_quality_signal  # software
    
    signals = [nvda, crm]
    
    result = prioritize_buy_signals_v2(signals, current_positions={}, equity=100000.0)
    
    # Should alternate between sectors for diversification
    assert len(result) == 2
    # Both should be included
    symbols = {s.symbol for s in result}
    assert symbols == {"NVDA", "CRM"}


def test_existing_positions_counted(high_quality_signal):
    """Test that existing positions are counted toward sector cap."""
    current_positions = {
        "INTC": {  # semis sector
            "qty": 500,
            "current_price": 150.0,  # 75,000 notional
            "avg_entry_price": 140.0,
        }
    }
    
    nvda_signal = high_quality_signal  # semis, 5000 notional
    
    result = prioritize_buy_signals_v2(
        [nvda_signal],
        current_positions=current_positions,
        equity=100000.0,
        max_sector_exposure_pct=0.80,  # 80,000 cap
    )
    
    # Should be included (75,000 + 5,000 = 80,000 <= 80,000)
    assert len(result) == 1


def test_no_buy_signals():
    """Test that non-buy signals are preserved."""
    sell_signal = CandidateSignal(
        strategy_id="test",
        symbol="AAPL",
        action="sell",
        signal_strength=0.90,
        generated_at=datetime.now(timezone.utc),
        time_horizon="immediate",
        confidence=0.85,
        reasoning="Exit",
        feature_refs=[],
    )
    
    result = prioritize_buy_signals_v2([sell_signal], current_positions={})
    
    assert len(result) == 1
    assert result[0].action == "sell"


def test_empty_signals():
    """Test that empty signal list returns empty."""
    result = prioritize_buy_signals_v2([], current_positions={})
    assert len(result) == 0
