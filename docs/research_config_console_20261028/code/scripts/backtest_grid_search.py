#!/usr/bin/env python3
"""
Parameter grid search for intraday momentum + VWAP strategy.

Tests multiple combinations of:
- VWAP threshold: 0.3%, 0.5%, 0.7%, 1.0%
- Momentum threshold: 0.3%, 0.5%, 0.7%, 1.0%
- Lookback bars: 15, 20, 25

Usage:
    python scripts/backtest_grid_search.py
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from dataclasses import dataclass
from typing import List, Dict
import itertools

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env
env_path = Path.home() / "stock_swing" / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if line.strip() and not line.strip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip()

from src.stock_swing.sources.massive_client import MassiveClient
from src.stock_swing.core.types import CanonicalRecord
from src.stock_swing.feature_engine.intraday_momentum_feature import IntradayMomentumFeature


@dataclass
class Trade:
    """Simple trade record."""
    symbol: str
    entry_date: datetime
    entry_price: float
    exit_date: datetime
    exit_price: float
    pnl: float
    return_pct: float
    exit_reason: str


def load_massive_data(symbols: List[str], days: int) -> Dict[str, List]:
    """Load Massive data for symbols."""
    client = MassiveClient()
    end = datetime.now()
    start = end - timedelta(days=days)
    
    data = {}
    
    print(f"\n⏳ Loading data for {len(symbols)} symbols ({days} days)...")
    
    for symbol in symbols:
        bars_daily = client.fetch_daily_bars(symbol, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        bars_5min = client.fetch_minute_bars(symbol, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), multiplier=5)
        data[f"{symbol}_daily"] = bars_daily
        data[f"{symbol}_5min"] = bars_5min
        print(f"  {symbol}: {len(bars_5min)} 5-minute bars")
    
    return data


def bars_to_canonical(symbol: str, bars: List, bar_type: str) -> List[CanonicalRecord]:
    """Convert bars to CanonicalRecord."""
    records = []
    for i, bar in enumerate(bars):
        record = CanonicalRecord(
            record_id=f"massive_{symbol}_{bar.timestamp.timestamp()}_{i}",
            schema_version="1.0",
            source="massive",
            source_type="price",
            symbol=symbol,
            event_type=bar_type,
            event_time=bar.timestamp.replace(tzinfo=timezone.utc),
            as_of=bar.timestamp.date().isoformat(),
            ingested_at=datetime.now(timezone.utc),
            timezone="UTC",
            payload_version="1.0",
            quality_flags=[],
            payload={
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "vw": bar.vwap if hasattr(bar, 'vwap') and bar.vwap else None,
                "n": bar.transactions if hasattr(bar, 'transactions') and bar.transactions else None,
            }
        )
        records.append(record)
    return records


def generate_signals(
    data: Dict,
    symbols: List[str],
    vwap_threshold: float,
    momentum_threshold: float,
    lookback_bars: int
) -> Dict:
    """Generate signals from intraday momentum + VWAP."""
    feature = IntradayMomentumFeature(
        lookback_bars=lookback_bars,
        smoothing_window=5,
        vwap_threshold=vwap_threshold
    )
    
    signals = defaultdict(dict)
    
    for symbol in symbols:
        bars = data[f"{symbol}_5min"]
        if not bars:
            continue
        
        bars_by_date = defaultdict(list)
        for bar in bars:
            bars_by_date[bar.timestamp.date()].append(bar)
        
        for date, day_bars in bars_by_date.items():
            if len(day_bars) < lookback_bars:
                continue
            
            window_bars = day_bars[-lookback_bars:]
            records = bars_to_canonical(symbol, window_bars, "bar_5min")
            
            results = feature.compute(records)
            if results:
                result = results[0]
                smoothed_mom = result.values.get('smoothed_momentum', 0)
                vwap_signal = result.values.get('vwap_signal', 'neutral')
                
                if smoothed_mom > momentum_threshold and vwap_signal != 'below_vwap':
                    signals[symbol][date] = {
                        'signal': 'buy',
                        'smoothed_momentum': smoothed_mom,
                        'vwap_signal': vwap_signal,
                        'confidence': min(smoothed_mom * 10, 1.0),
                        'price': result.values.get('latest_close'),
                        'stop_price': result.values.get('stop_price'),
                    }
    
    return signals


def simulate_trades(signals: Dict, data: Dict, symbols: List[str]) -> List[Trade]:
    """Simulate trades based on signals."""
    trades = []
    
    for symbol in symbols:
        daily_bars = data[f"{symbol}_daily"]
        if not daily_bars:
            continue
        
        price_by_date = {bar.timestamp.date(): bar for bar in daily_bars}
        
        for signal_date, signal in signals[symbol].items():
            if signal['signal'] != 'buy':
                continue
            
            entry_bar = price_by_date.get(signal_date)
            if not entry_bar:
                continue
            
            entry_price = entry_bar.close
            entry_date = entry_bar.timestamp
            
            stop_loss_pct = 0.07
            take_profit_pct = 0.15
            max_hold_days = 5
            
            exit_price = None
            exit_date = None
            exit_reason = None
            
            for days_held in range(1, max_hold_days + 1):
                check_date = signal_date + timedelta(days=days_held)
                check_bar = price_by_date.get(check_date)
                
                if not check_bar:
                    continue
                
                if check_bar.low <= entry_price * (1 - stop_loss_pct):
                    exit_price = entry_price * (1 - stop_loss_pct)
                    exit_date = check_bar.timestamp
                    exit_reason = 'stop_loss'
                    break
                
                if check_bar.high >= entry_price * (1 + take_profit_pct):
                    exit_price = entry_price * (1 + take_profit_pct)
                    exit_date = check_bar.timestamp
                    exit_reason = 'take_profit'
                    break
                
                if days_held == max_hold_days:
                    exit_price = check_bar.close
                    exit_date = check_bar.timestamp
                    exit_reason = 'max_hold'
                    break
            
            if exit_price and exit_date:
                pnl = exit_price - entry_price
                return_pct = (exit_price / entry_price - 1) * 100
                
                trade = Trade(
                    symbol=symbol,
                    entry_date=entry_date,
                    entry_price=entry_price,
                    exit_date=exit_date,
                    exit_price=exit_price,
                    pnl=pnl,
                    return_pct=return_pct,
                    exit_reason=exit_reason
                )
                trades.append(trade)
    
    return trades


def analyze_results(trades: List[Trade]) -> Dict:
    """Analyze backtest results."""
    if not trades:
        return {
            'total_trades': 0,
            'win_rate': 0.0,
            'avg_return': 0.0,
            'total_return': 0.0,
            'sharpe': 0.0,
        }
    
    winning_trades = [t for t in trades if t.pnl > 0]
    win_rate = len(winning_trades) / len(trades) * 100
    avg_return = sum(t.return_pct for t in trades) / len(trades)
    total_return = sum(t.return_pct for t in trades)
    
    # Sharpe approximation
    returns = [t.return_pct for t in trades]
    if len(returns) > 1:
        std_return = (sum((r - avg_return) ** 2 for r in returns) / (len(returns) - 1)) ** 0.5
        sharpe = avg_return / std_return if std_return > 0 else 0.0
    else:
        sharpe = 0.0
    
    return {
        'total_trades': len(trades),
        'win_rate': win_rate,
        'avg_return': avg_return,
        'total_return': total_return,
        'sharpe': sharpe,
    }


def main():
    print("="*80)
    print("PARAMETER GRID SEARCH")
    print("="*80)
    
    symbols = ["NVDA", "AMD", "AAPL", "MRVL", "PLTR"]
    days = 60
    
    # Load data once
    data = load_massive_data(symbols, days)
    
    # Grid search parameters
    vwap_thresholds = [0.003, 0.005, 0.007, 0.010]
    momentum_thresholds = [0.003, 0.005, 0.007, 0.010]
    lookback_bars_options = [15, 20, 25]
    
    print(f"\n🔍 Testing {len(vwap_thresholds) * len(momentum_thresholds) * len(lookback_bars_options)} parameter combinations...")
    print()
    
    all_results = []
    
    for vwap_thresh, mom_thresh, lookback in itertools.product(
        vwap_thresholds, momentum_thresholds, lookback_bars_options
    ):
        print(f"Testing: VWAP={vwap_thresh*100:.1f}%, Mom={mom_thresh*100:.1f}%, Lookback={lookback}...", end=" ")
        
        signals = generate_signals(data, symbols, vwap_thresh, mom_thresh, lookback)
        total_signals = sum(len(v) for v in signals.values())
        
        trades = simulate_trades(signals, data, symbols)
        results = analyze_results(trades)
        
        results['vwap_threshold'] = vwap_thresh
        results['momentum_threshold'] = mom_thresh
        results['lookback_bars'] = lookback
        results['total_signals'] = total_signals
        
        all_results.append(results)
        print(f"✅ {results['total_trades']} trades, {results['win_rate']:.1f}% WR, {results['total_return']:.1f}% TR")
    
    # Sort by different criteria
    by_total_return = sorted(all_results, key=lambda r: r['total_return'], reverse=True)
    by_win_rate = sorted(all_results, key=lambda r: r['win_rate'], reverse=True)
    by_sharpe = sorted(all_results, key=lambda r: r['sharpe'], reverse=True)
    
    # Display top results
    print("\n" + "="*80)
    print("TOP 10 BY TOTAL RETURN")
    print("="*80)
    print(f"{'VWAP%':<8} {'Mom%':<8} {'Lookback':<10} {'Trades':<8} {'WinRate%':<10} {'AvgRet%':<10} {'TotalRet%':<12}")
    print("-"*80)
    
    for res in by_total_return[:10]:
        print(f"{res['vwap_threshold']*100:<8.1f} {res['momentum_threshold']*100:<8.1f} "
              f"{res['lookback_bars']:<10} {res['total_trades']:<8} "
              f"{res['win_rate']:<10.1f} {res['avg_return']:<10.2f} {res['total_return']:<12.1f}")
    
    print("\n" + "="*80)
    print("TOP 10 BY WIN RATE")
    print("="*80)
    print(f"{'VWAP%':<8} {'Mom%':<8} {'Lookback':<10} {'Trades':<8} {'WinRate%':<10} {'AvgRet%':<10} {'TotalRet%':<12}")
    print("-"*80)
    
    for res in by_win_rate[:10]:
        print(f"{res['vwap_threshold']*100:<8.1f} {res['momentum_threshold']*100:<8.1f} "
              f"{res['lookback_bars']:<10} {res['total_trades']:<8} "
              f"{res['win_rate']:<10.1f} {res['avg_return']:<10.2f} {res['total_return']:<12.1f}")
    
    print("\n" + "="*80)
    print("TOP 10 BY SHARPE RATIO")
    print("="*80)
    print(f"{'VWAP%':<8} {'Mom%':<8} {'Lookback':<10} {'Trades':<8} {'Sharpe':<10} {'AvgRet%':<10} {'TotalRet%':<12}")
    print("-"*80)
    
    for res in by_sharpe[:10]:
        print(f"{res['vwap_threshold']*100:<8.1f} {res['momentum_threshold']*100:<8.1f} "
              f"{res['lookback_bars']:<10} {res['total_trades']:<8} "
              f"{res['sharpe']:<10.2f} {res['avg_return']:<10.2f} {res['total_return']:<12.1f}")
    
    # Optimal configuration
    best = by_total_return[0]
    
    print("\n" + "="*80)
    print("OPTIMAL CONFIGURATION (by Total Return)")
    print("="*80)
    print(f"VWAP Threshold:      {best['vwap_threshold']*100:.1f}%")
    print(f"Momentum Threshold:  {best['momentum_threshold']*100:.1f}%")
    print(f"Lookback Bars:       {best['lookback_bars']}")
    print(f"Total Trades:        {best['total_trades']}")
    print(f"Win Rate:            {best['win_rate']:.1f}%")
    print(f"Avg Return:          {best['avg_return']:.2f}%")
    print(f"Total Return:        {best['total_return']:.1f}%")
    print(f"Sharpe Ratio:        {best['sharpe']:.2f}")
    
    print("\n" + "="*80)
    print("Grid search complete!")
    print("="*80)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
