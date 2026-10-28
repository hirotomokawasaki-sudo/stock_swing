#!/usr/bin/env python3
"""
Backtest comparison: Daily momentum vs Intraday momentum with VWAP.

This script compares two strategies:
1. Baseline: Daily momentum (PriceMomentumFeature)
2. Enhanced: 5-minute momentum + VWAP filter (IntradayMomentumFeature)

Usage:
    python scripts/backtest_momentum_comparison.py
"""

import sys
import os
import json
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
from src.stock_swing.feature_engine.price_momentum_feature import PriceMomentumFeature
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


@dataclass
class BacktestResult:
    """Backtest results summary."""
    strategy: str
    trades: List[Trade]
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_return: float
    avg_win: float
    avg_loss: float
    total_return: float
    max_drawdown: float


def load_massive_data(symbols: List[str], days: int) -> Dict[str, List]:
    """Load Massive data for symbols."""
    client = MassiveClient()
    end = datetime.now()
    start = end - timedelta(days=days)
    
    data = {}
    
    # Load daily bars
    print(f"\n⏳ Loading daily bars ({days} days)...")
    for symbol in symbols:
        bars = client.fetch_daily_bars(
            symbol,
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d")
        )
        data[f"{symbol}_daily"] = bars
        print(f"  {symbol}: {len(bars)} daily bars")
    
    # Load 5-minute bars (last 10 days only for speed)
    print(f"\n⏳ Loading 5-minute bars (last 10 days)...")
    start_5min = end - timedelta(days=10)
    for symbol in symbols:
        bars = client.fetch_minute_bars(
            symbol,
            start_5min.strftime("%Y-%m-%d"),
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


def generate_signals_daily(data: Dict, symbols: List[str]) -> Dict:
    """Generate signals from daily momentum."""
    feature = PriceMomentumFeature(period_days=5)
    
    # Group bars by date for each symbol
    signals = defaultdict(dict)
    
    for symbol in symbols:
        bars = data[f"{symbol}_daily"]
        if not bars:
            continue
        
        # For each date, compute momentum from previous bars
        for i in range(5, len(bars)):
            window_bars = bars[i-5:i+1]
            records = bars_to_canonical(symbol, window_bars, "bar_daily")
            
            results = feature.compute(records)
            if results:
                result = results[0]
                date = bars[i].timestamp.date()
                
                # Signal: momentum > 0.02 and trend == bullish
                if result.values.get('momentum', 0) > 0.02 and result.values.get('trend') == 'bullish':
                    signals[symbol][date] = {
                        'signal': 'buy',
                        'momentum': result.values['momentum'],
                        'confidence': min(result.values['momentum'] * 10, 1.0),  # Scale to 0-1
                        'price': result.values.get('latest_close'),
                        'stop_price': result.values.get('stop_price'),
                    }
    
    return signals


def generate_signals_intraday(data: Dict, symbols: List[str]) -> Dict:
    """Generate signals from intraday momentum + VWAP."""
    feature = IntradayMomentumFeature(lookback_bars=20, smoothing_window=5, vwap_threshold=0.005)
    
    # Group bars by date for each symbol
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
                
                # Signal: smoothed_momentum > 0.01 AND vwap_signal != below_vwap
                smoothed_mom = result.values.get('smoothed_momentum', 0)
                vwap_signal = result.values.get('vwap_signal', 'neutral')
                
                if smoothed_mom > 0.01 and vwap_signal != 'below_vwap':
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
        
        # Create price lookup
        price_by_date = {bar.timestamp.date(): bar for bar in daily_bars}
        
        # Simulate trades
        for signal_date, signal in signals[symbol].items():
            if signal['signal'] != 'buy':
                continue
            
            # Entry
            entry_bar = price_by_date.get(signal_date)
            if not entry_bar:
                continue
            
            entry_price = entry_bar.close
            entry_date = entry_bar.timestamp
            
            # Find exit (max 5 days, stop loss -7%, take profit +15%)
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
                
                # Check stop loss
                if check_bar.low <= entry_price * (1 - stop_loss_pct):
                    exit_price = entry_price * (1 - stop_loss_pct)
                    exit_date = check_bar.timestamp
                    exit_reason = 'stop_loss'
                    break
                
                # Check take profit
                if check_bar.high >= entry_price * (1 + take_profit_pct):
                    exit_price = entry_price * (1 + take_profit_pct)
                    exit_date = check_bar.timestamp
                    exit_reason = 'take_profit'
                    break
                
                # Max hold
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


def analyze_results(trades: List[Trade], strategy: str) -> BacktestResult:
    """Analyze backtest results."""
    if not trades:
        return BacktestResult(
            strategy=strategy,
            trades=[],
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            avg_return=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            total_return=0.0,
            max_drawdown=0.0
        )
    
    winning_trades = [t for t in trades if t.pnl > 0]
    losing_trades = [t for t in trades if t.pnl <= 0]
    
    win_rate = len(winning_trades) / len(trades) * 100
    avg_return = sum(t.return_pct for t in trades) / len(trades)
    avg_win = sum(t.return_pct for t in winning_trades) / len(winning_trades) if winning_trades else 0.0
    avg_loss = sum(t.return_pct for t in losing_trades) / len(losing_trades) if losing_trades else 0.0
    total_return = sum(t.return_pct for t in trades)
    
    # Simple max drawdown calculation
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
    
    return BacktestResult(
        strategy=strategy,
        trades=trades,
        total_trades=len(trades),
        winning_trades=len(winning_trades),
        losing_trades=len(losing_trades),
        win_rate=win_rate,
        avg_return=avg_return,
        avg_win=avg_win,
        avg_loss=avg_loss,
        total_return=total_return,
        max_drawdown=max_dd
    )


def main():
    print("="*80)
    print("BACKTEST COMPARISON: Daily vs Intraday Momentum")
    print("="*80)
    
    symbols = ["NVDA", "AMD", "AAPL", "MRVL", "PLTR"]
    days = 60
    
    # Load data
    print(f"\n📊 Loading data for {len(symbols)} symbols...")
    data = load_massive_data(symbols, days)
    
    # Generate signals
    print("\n" + "="*80)
    print("STRATEGY 1: Daily Momentum (Baseline)")
    print("="*80)
    print("⏳ Generating signals from daily bars...")
    signals_daily = generate_signals_daily(data, symbols)
    
    total_signals_daily = sum(len(v) for v in signals_daily.values())
    print(f"✅ Generated {total_signals_daily} buy signals")
    
    print("\n" + "="*80)
    print("STRATEGY 2: Intraday Momentum + VWAP (Enhanced)")
    print("="*80)
    print("⏳ Generating signals from 5-minute bars...")
    signals_intraday = generate_signals_intraday(data, symbols)
    
    total_signals_intraday = sum(len(v) for v in signals_intraday.values())
    print(f"✅ Generated {total_signals_intraday} buy signals")
    
    # Simulate trades
    print("\n" + "="*80)
    print("SIMULATING TRADES")
    print("="*80)
    
    print("\n⏳ Simulating Strategy 1 (Daily)...")
    trades_daily = simulate_trades(signals_daily, data, symbols, "Daily Momentum")
    print(f"✅ Executed {len(trades_daily)} trades")
    
    print("\n⏳ Simulating Strategy 2 (Intraday + VWAP)...")
    trades_intraday = simulate_trades(signals_intraday, data, symbols, "Intraday + VWAP")
    print(f"✅ Executed {len(trades_intraday)} trades")
    
    # Analyze results
    print("\n" + "="*80)
    print("RESULTS")
    print("="*80)
    
    result_daily = analyze_results(trades_daily, "Daily Momentum")
    result_intraday = analyze_results(trades_intraday, "Intraday + VWAP")
    
    # Display comparison
    print("\n" + "-"*80)
    print(f"{'Metric':<25} {'Daily (Baseline)':<20} {'Intraday + VWAP':<20} {'Δ':<15}")
    print("-"*80)
    
    metrics = [
        ("Total Trades", result_daily.total_trades, result_intraday.total_trades),
        ("Winning Trades", result_daily.winning_trades, result_intraday.winning_trades),
        ("Losing Trades", result_daily.losing_trades, result_intraday.losing_trades),
        ("Win Rate (%)", result_daily.win_rate, result_intraday.win_rate),
        ("Avg Return (%)", result_daily.avg_return, result_intraday.avg_return),
        ("Avg Win (%)", result_daily.avg_win, result_intraday.avg_win),
        ("Avg Loss (%)", result_daily.avg_loss, result_intraday.avg_loss),
        ("Total Return (%)", result_daily.total_return, result_intraday.total_return),
        ("Max Drawdown (%)", result_daily.max_drawdown, result_intraday.max_drawdown),
    ]
    
    for metric, val_daily, val_intraday in metrics:
        if val_daily == 0:
            delta_str = "N/A"
        else:
            delta = val_intraday - val_daily
            delta_pct = (delta / val_daily * 100) if val_daily != 0 else 0
            delta_str = f"{delta:+.2f} ({delta_pct:+.1f}%)"
        
        print(f"{metric:<25} {val_daily:<20.2f} {val_intraday:<20.2f} {delta_str:<15}")
    
    print("-"*80)
    
    # Sample trades
    print("\n" + "="*80)
    print("SAMPLE TRADES (First 5 per strategy)")
    print("="*80)
    
    print("\nDaily Momentum:")
    for trade in trades_daily[:5]:
        print(f"  {trade.symbol:6} {trade.entry_date.date()} → {trade.exit_date.date()} | "
              f"${trade.entry_price:.2f} → ${trade.exit_price:.2f} | "
              f"{trade.return_pct:+6.2f}% | {trade.exit_reason}")
    
    print("\nIntraday + VWAP:")
    for trade in trades_intraday[:5]:
        print(f"  {trade.symbol:6} {trade.entry_date.date()} → {trade.exit_date.date()} | "
              f"${trade.entry_price:.2f} → ${trade.exit_price:.2f} | "
              f"{trade.return_pct:+6.2f}% | {trade.exit_reason}")
    
    # Conclusion
    print("\n" + "="*80)
    print("CONCLUSION")
    print("="*80)
    
    if result_intraday.win_rate > result_daily.win_rate:
        wr_improvement = result_intraday.win_rate - result_daily.win_rate
        print(f"✅ Intraday + VWAP strategy shows +{wr_improvement:.1f}% win rate improvement")
    else:
        wr_decline = result_daily.win_rate - result_intraday.win_rate
        print(f"⚠️  Intraday + VWAP strategy shows -{wr_decline:.1f}% win rate decline")
    
    if result_intraday.avg_return > result_daily.avg_return:
        ar_improvement = result_intraday.avg_return - result_daily.avg_return
        print(f"✅ Intraday + VWAP strategy shows +{ar_improvement:.2f}% avg return improvement")
    else:
        ar_decline = result_daily.avg_return - result_intraday.avg_return
        print(f"⚠️  Intraday + VWAP strategy shows -{ar_decline:.2f}% avg return decline")
    
    print("\n" + "="*80)
    print("Backtest complete!")
    print("="*80)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
