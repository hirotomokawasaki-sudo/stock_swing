#!/usr/bin/env python3
"""
Backtest with relaxed thresholds for intraday momentum + VWAP.

Relaxed parameters:
- VWAP threshold: 0.5% → 1.0%
- Smoothed momentum threshold: 1.0% → 0.5%

Usage:
    python scripts/backtest_relaxed_threshold.py
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from dataclasses import dataclass
from typing import List, Dict

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
    strategy: str


def load_massive_data(symbols: List[str], days: int) -> Dict[str, List]:
    """Load Massive data for symbols."""
    client = MassiveClient()
    end = datetime.now()
    start = end - timedelta(days=days)
    
    data = {}
    
    print(f"\n⏳ Loading data for {len(symbols)} symbols ({days} days)...")
    
    # Load daily bars
    for symbol in symbols:
        bars = client.fetch_daily_bars(
            symbol,
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d")
        )
        data[f"{symbol}_daily"] = bars
    
    # Load 5-minute bars (full period)
    for symbol in symbols:
        bars = client.fetch_minute_bars(
            symbol,
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
            multiplier=5
        )
        data[f"{symbol}_5min"] = bars
        print(f"  {symbol}: {len(bars)} 5-minute bars")
    
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


def generate_signals(data: Dict, symbols: List[str], vwap_threshold: float, momentum_threshold: float) -> Dict:
    """Generate signals from intraday momentum + VWAP."""
    feature = IntradayMomentumFeature(
        lookback_bars=20,
        smoothing_window=5,
        vwap_threshold=vwap_threshold
    )
    
    signals = defaultdict(dict)
    
    for symbol in symbols:
        bars = data[f"{symbol}_5min"]
        if not bars:
            continue
        
        # Group by date
        bars_by_date = defaultdict(list)
        for bar in bars:
            bars_by_date[bar.timestamp.date()].append(bar)
        
        # For each date, compute momentum from intraday bars
        for date, day_bars in bars_by_date.items():
            if len(day_bars) < 20:
                continue
            
            # Use last 20 bars of the day
            window_bars = day_bars[-20:]
            records = bars_to_canonical(symbol, window_bars, "bar_5min")
            
            results = feature.compute(records)
            if results:
                result = results[0]
                
                # Relaxed signal criteria
                smoothed_mom = result.values.get('smoothed_momentum', 0)
                vwap_signal = result.values.get('vwap_signal', 'neutral')
                
                # New: momentum_threshold is configurable
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


def simulate_trades(signals: Dict, data: Dict, symbols: List[str], strategy: str) -> List[Trade]:
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
                    exit_reason=exit_reason,
                    strategy=strategy
                )
                trades.append(trade)
    
    return trades


def analyze_results(trades: List[Trade]) -> Dict:
    """Analyze backtest results."""
    if not trades:
        return {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'win_rate': 0.0,
            'avg_return': 0.0,
            'avg_win': 0.0,
            'avg_loss': 0.0,
            'total_return': 0.0,
            'max_drawdown': 0.0,
        }
    
    winning_trades = [t for t in trades if t.pnl > 0]
    losing_trades = [t for t in trades if t.pnl <= 0]
    
    win_rate = len(winning_trades) / len(trades) * 100
    avg_return = sum(t.return_pct for t in trades) / len(trades)
    avg_win = sum(t.return_pct for t in winning_trades) / len(winning_trades) if winning_trades else 0.0
    avg_loss = sum(t.return_pct for t in losing_trades) / len(losing_trades) if losing_trades else 0.0
    total_return = sum(t.return_pct for t in trades)
    
    # Max drawdown
    cumulative = 0
    peak = 0
    max_dd = 0
    for trade in sorted(trades, key=lambda t: t.entry_date):
        cumulative += trade.return_pct
        if cumulative > peak:
            peak = cumulative
        drawdown = peak - cumulative
        if drawdown > max_dd:
            max_dd = drawdown
    
    return {
        'total_trades': len(trades),
        'winning_trades': len(winning_trades),
        'losing_trades': len(losing_trades),
        'win_rate': win_rate,
        'avg_return': avg_return,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'total_return': total_return,
        'max_drawdown': max_dd,
    }


def main():
    print("="*80)
    print("BACKTEST: Relaxed Threshold Version")
    print("="*80)
    
    symbols = ["NVDA", "AMD", "AAPL", "MRVL", "PLTR"]
    days = 60
    
    # Load data
    data = load_massive_data(symbols, days)
    
    # Test different threshold combinations
    threshold_configs = [
        ("Original (Strict)", 0.005, 0.010),
        ("Relaxed VWAP", 0.010, 0.010),
        ("Relaxed Momentum", 0.005, 0.005),
        ("Both Relaxed", 0.010, 0.005),
    ]
    
    all_results = []
    
    for config_name, vwap_thresh, mom_thresh in threshold_configs:
        print("\n" + "="*80)
        print(f"CONFIG: {config_name}")
        print(f"  VWAP threshold: {vwap_thresh*100:.1f}%")
        print(f"  Momentum threshold: {mom_thresh*100:.1f}%")
        print("="*80)
        
        print("⏳ Generating signals...")
        signals = generate_signals(data, symbols, vwap_thresh, mom_thresh)
        total_signals = sum(len(v) for v in signals.values())
        print(f"✅ Generated {total_signals} buy signals")
        
        print("⏳ Simulating trades...")
        trades = simulate_trades(signals, data, symbols, config_name)
        print(f"✅ Executed {len(trades)} trades")
        
        results = analyze_results(trades)
        results['config'] = config_name
        results['vwap_threshold'] = vwap_thresh
        results['momentum_threshold'] = mom_thresh
        results['trades'] = trades
        all_results.append(results)
        
        print(f"\nResults:")
        print(f"  Win Rate: {results['win_rate']:.1f}%")
        print(f"  Avg Return: {results['avg_return']:.2f}%")
        print(f"  Total Return: {results['total_return']:.2f}%")
    
    # Summary comparison
    print("\n" + "="*80)
    print("SUMMARY COMPARISON")
    print("="*80)
    print(f"\n{'Config':<20} {'Trades':<10} {'Win Rate':<12} {'Avg Return':<12} {'Total Return':<15}")
    print("-"*80)
    
    for res in all_results:
        print(f"{res['config']:<20} {res['total_trades']:<10} "
              f"{res['win_rate']:<12.1f} {res['avg_return']:<12.2f} {res['total_return']:<15.2f}")
    
    # Best config
    best_by_win_rate = max(all_results, key=lambda r: r['win_rate'])
    best_by_total_return = max(all_results, key=lambda r: r['total_return'])
    
    print("\n" + "="*80)
    print("BEST CONFIGURATIONS")
    print("="*80)
    print(f"Best by Win Rate: {best_by_win_rate['config']} ({best_by_win_rate['win_rate']:.1f}%)")
    print(f"Best by Total Return: {best_by_total_return['config']} ({best_by_total_return['total_return']:.2f}%)")
    
    # Sample trades from best config
    print("\n" + "="*80)
    print(f"SAMPLE TRADES: {best_by_total_return['config']}")
    print("="*80)
    
    for trade in best_by_total_return['trades'][:10]:
        print(f"{trade.symbol:6} {trade.entry_date.date()} → {trade.exit_date.date()} | "
              f"${trade.entry_price:.2f} → ${trade.exit_price:.2f} | "
              f"{trade.return_pct:+6.2f}% | {trade.exit_reason}")
    
    print("\n" + "="*80)
    print("Backtest complete!")
    print("="*80)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
