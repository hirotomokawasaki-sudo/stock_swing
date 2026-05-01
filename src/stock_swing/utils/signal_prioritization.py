"""Signal prioritization utilities for sector diversification.

This module provides utilities to prioritize trading signals based on
sector exposure to promote portfolio diversification.
"""

from __future__ import annotations

from stock_swing.risk.position_sizing import SYMBOL_SECTORS
from stock_swing.strategy_engine.base_strategy import CandidateSignal


def calculate_sector_exposure(
    current_positions: dict[str, dict],
) -> dict[str, float]:
    """Calculate current sector exposure by notional value.
    
    Args:
        current_positions: Dict of symbol -> position data
            {symbol: {qty, current_price, avg_entry_price, ...}}
    
    Returns:
        Dict of sector -> total notional value
    """
    sector_exposure = {}
    
    for symbol, pos_data in current_positions.items():
        sector = SYMBOL_SECTORS.get(symbol.upper())
        if not sector:
            continue
        
        qty = abs(float(pos_data.get("qty", 0)))
        price = float(pos_data.get("current_price", pos_data.get("avg_entry_price", 0)))
        notional = qty * price
        
        sector_exposure[sector] = sector_exposure.get(sector, 0.0) + notional
    
    return sector_exposure


def prioritize_buy_signals(
    signals: list[CandidateSignal],
    current_positions: dict[str, dict] | None = None,
) -> list[CandidateSignal]:
    """Prioritize buy signals to favor sector diversification.
    
    Signals from less-exposed sectors are ranked higher.
    Within same sector, higher signal strength wins.
    
    Args:
        signals: List of candidate signals (buy signals only).
        current_positions: Current positions for sector exposure calculation.
    
    Returns:
        Prioritized list of signals (highest priority first).
    """
    if not signals:
        return []
    
    # Filter to buy signals only
    buy_signals = [s for s in signals if s.action == "buy"]
    if not buy_signals:
        return signals  # Return original if no buy signals
    
    # Calculate current sector exposure
    sector_exposure = {}
    if current_positions:
        sector_exposure = calculate_sector_exposure(current_positions)
    
    # Get total exposure for normalization
    total_exposure = sum(sector_exposure.values()) or 1.0
    
    # Score each signal (lower score = higher priority)
    def score_signal(signal: CandidateSignal) -> tuple[float, float]:
        symbol = signal.symbol.upper()
        sector = SYMBOL_SECTORS.get(symbol)
        
        # Sector exposure score (0.0 = no exposure, 1.0 = max exposure)
        if sector:
            sector_pct = sector_exposure.get(sector, 0.0) / total_exposure
        else:
            sector_pct = 0.5  # Unknown sector = medium priority
        
        # Signal strength (negate for descending order within same sector)
        strength = -signal.signal_strength
        
        return (sector_pct, strength)
    
    # Sort: low sector exposure first, then high signal strength
    prioritized_buys = sorted(buy_signals, key=score_signal)
    
    # Combine with non-buy signals (preserve order)
    non_buy_signals = [s for s in signals if s.action != "buy"]
    
    return prioritized_buys + non_buy_signals


def prioritize_buy_signals_v2(
    signals: list[CandidateSignal],
    current_positions: dict[str, dict] | None = None,
    equity: float = 100000.0,
    max_sector_exposure_pct: float = 0.80,
) -> list[CandidateSignal]:
    """Prioritize buy signals with dynamic sector allocation (V2).
    
    Improvements over V1:
    - Sorts by signal quality (signal_strength * confidence) within sector
    - Enforces sector cap dynamically
    - Prioritizes high-quality signals first
    
    Args:
        signals: List of candidate signals.
        current_positions: Current positions for sector exposure calculation.
        equity: Account equity for sector cap calculation.
        max_sector_exposure_pct: Maximum exposure per sector (e.g., 0.80 = 80%).
    
    Returns:
        Prioritized list of signals respecting sector caps.
    """
    if not signals:
        return []
    
    # Filter to buy signals only
    buy_signals = [s for s in signals if s.action == "buy"]
    non_buy_signals = [s for s in signals if s.action != "buy"]
    
    if not buy_signals:
        return signals
    
    # Calculate current sector exposure
    sector_exposure = {}
    if current_positions:
        sector_exposure = calculate_sector_exposure(current_positions)
    
    # Group signals by sector and sort by quality
    sector_signals: dict[str, list[CandidateSignal]] = {}
    
    for signal in buy_signals:
        symbol = signal.symbol.upper()
        sector = SYMBOL_SECTORS.get(symbol, "unknown")
        
        if sector not in sector_signals:
            sector_signals[sector] = []
        sector_signals[sector].append(signal)
    
    # Sort signals within each sector by quality (signal_strength * confidence)
    for sector in sector_signals:
        sector_signals[sector].sort(
            key=lambda s: s.signal_strength * s.confidence,
            reverse=True,
        )
    
    # Allocate signals respecting sector caps
    max_sector_value = equity * max_sector_exposure_pct
    prioritized_buys = []
    
    # Round-robin allocation across sectors to promote diversification
    sectors_list = list(sector_signals.keys())
    sector_indices = {sector: 0 for sector in sectors_list}
    
    # Keep allocating until all signals are processed or sectors are full
    while any(sector_indices[s] < len(sector_signals[s]) for s in sectors_list):
        allocated_this_round = False
        
        for sector in sectors_list:
            idx = sector_indices[sector]
            if idx >= len(sector_signals[sector]):
                continue  # This sector is exhausted
            
            signal = sector_signals[sector][idx]
            current_sector_exposure = sector_exposure.get(sector, 0.0)
            
            # Estimate signal notional (use metadata if available)
            estimated_notional = 1000.0  # Default
            if isinstance(signal.metadata, dict):
                estimated_notional = signal.metadata.get("estimated_notional", 1000.0)
            
            # Check if adding this signal would exceed sector cap
            if current_sector_exposure + estimated_notional <= max_sector_value:
                prioritized_buys.append(signal)
                sector_exposure[sector] = current_sector_exposure + estimated_notional
                allocated_this_round = True
            
            sector_indices[sector] += 1
        
        # If no signals were allocated this round, all sectors are capped
        if not allocated_this_round:
            break
    
    # Combine with non-buy signals (preserve order)
    return prioritized_buys + non_buy_signals
