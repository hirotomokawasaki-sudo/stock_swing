"""Benchmark comparison service for performance attribution."""

from pathlib import Path
from typing import Dict, List, Any
import json
from datetime import datetime

class BenchmarkService:
    """Service for comparing portfolio performance against market benchmarks."""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.benchmark_dir = project_root / "data" / "benchmarks"
    
    def load_benchmark_data(self, symbol: str = "SPY") -> List[Dict[str, Any]]:
        """Load benchmark data from file."""
        benchmark_file = self.benchmark_dir / f"{symbol}_daily.json"
        if not benchmark_file.exists():
            return []
        
        try:
            return json.loads(benchmark_file.read_text())
        except:
            return []
    
    def calculate_alpha(
        self,
        portfolio_snapshots: List[Dict[str, Any]],
        benchmark: str = "SPY"
    ) -> Dict[str, Any]:
        """Calculate alpha (excess return over benchmark)."""
        
        # Load benchmark data
        benchmark_data = self.load_benchmark_data(benchmark)
        if not benchmark_data:
            return {"available": False, "error": "No benchmark data"}
        
        # Build benchmark price map
        benchmark_map = {d['date']: d['close'] for d in benchmark_data}
        
        # Match portfolio and benchmark dates
        matched_data = []
        for snap in portfolio_snapshots:
            date = snap.get('date')
            equity = snap.get('equity')
            
            if date in benchmark_map and equity is not None:
                matched_data.append({
                    'date': date,
                    'portfolio_equity': equity,
                    'benchmark_price': benchmark_map[date]
                })
        
        if len(matched_data) < 2:
            return {"available": False, "error": "Not enough matching data points"}
        
        # Calculate returns
        first_point = matched_data[0]
        last_point = matched_data[-1]
        
        portfolio_return = ((last_point['portfolio_equity'] - first_point['portfolio_equity']) 
                           / first_point['portfolio_equity']) * 100
        
        benchmark_return = ((last_point['benchmark_price'] - first_point['benchmark_price'])
                           / first_point['benchmark_price']) * 100
        
        alpha = portfolio_return - benchmark_return
        
        return {
            "available": True,
            "period": {
                "start": first_point['date'],
                "end": last_point['date'],
                "days": len(matched_data)
            },
            "portfolio": {
                "return_pct": portfolio_return,
                "start_equity": first_point['portfolio_equity'],
                "end_equity": last_point['portfolio_equity'],
            },
            "benchmark": {
                "symbol": benchmark,
                "return_pct": benchmark_return,
                "start_price": first_point['benchmark_price'],
                "end_price": last_point['benchmark_price'],
            },
            "alpha": alpha,
            "interpretation": self._interpret_alpha(alpha)
        }
    
    def calculate_beta(
        self,
        portfolio_snapshots: List[Dict[str, Any]],
        benchmark: str = "SPY"
    ) -> Dict[str, Any]:
        """Calculate beta (portfolio volatility vs benchmark)."""
        
        # Load benchmark data
        benchmark_data = self.load_benchmark_data(benchmark)
        if not benchmark_data:
            return {"available": False, "error": "No benchmark data"}
        
        # Build benchmark price map
        benchmark_map = {d['date']: d['close'] for d in benchmark_data}
        
        # Match portfolio and benchmark dates
        portfolio_returns = []
        benchmark_returns = []
        
        prev_snap = None
        prev_bench = None
        
        for snap in sorted(portfolio_snapshots, key=lambda s: s.get('date', '')):
            date = snap.get('date')
            equity = snap.get('equity')
            
            if date in benchmark_map and equity is not None:
                bench_price = benchmark_map[date]
                
                if prev_snap is not None and prev_bench is not None:
                    # Calculate daily returns
                    p_return = (equity - prev_snap) / prev_snap
                    b_return = (bench_price - prev_bench) / prev_bench
                    
                    portfolio_returns.append(p_return)
                    benchmark_returns.append(b_return)
                
                prev_snap = equity
                prev_bench = bench_price
        
        if len(portfolio_returns) < 5:
            return {"available": False, "error": "Not enough data points for beta calculation"}
        
        # Calculate beta using covariance / variance
        import statistics
        
        # Calculate covariance
        mean_p = statistics.mean(portfolio_returns)
        mean_b = statistics.mean(benchmark_returns)
        
        covariance = sum((p - mean_p) * (b - mean_b) 
                        for p, b in zip(portfolio_returns, benchmark_returns)) / len(portfolio_returns)
        
        # Calculate benchmark variance
        variance_b = statistics.variance(benchmark_returns)
        
        beta = covariance / variance_b if variance_b > 0 else 1.0
        
        # Calculate R-squared (correlation)
        variance_p = statistics.variance(portfolio_returns)
        correlation = covariance / (variance_p ** 0.5 * variance_b ** 0.5) if variance_p > 0 and variance_b > 0 else 0
        r_squared = correlation ** 2
        
        return {
            "available": True,
            "beta": beta,
            "r_squared": r_squared,
            "interpretation": self._interpret_beta(beta),
            "correlation": correlation,
            "data_points": len(portfolio_returns)
        }
    
    def calculate_sharpe_ratio(
        self,
        portfolio_snapshots: List[Dict[str, Any]],
        risk_free_rate: float = 2.0  # Annual risk-free rate in %
    ) -> Dict[str, Any]:
        """Calculate Sharpe ratio (risk-adjusted return)."""
        
        if len(portfolio_snapshots) < 2:
            return {"available": False, "error": "Not enough data"}
        
        # Calculate daily returns
        returns = []
        prev_equity = None
        
        for snap in sorted(portfolio_snapshots, key=lambda s: s.get('date', '')):
            equity = snap.get('equity')
            if equity is not None:
                if prev_equity is not None:
                    daily_return = (equity - prev_equity) / prev_equity
                    returns.append(daily_return)
                prev_equity = equity
        
        if len(returns) < 2:
            return {"available": False, "error": "Not enough return data"}
        
        # Calculate statistics
        import statistics
        mean_return = statistics.mean(returns)
        std_return = statistics.stdev(returns)
        
        # Annualize (assuming ~252 trading days)
        annual_return = mean_return * 252 * 100  # Convert to %
        annual_volatility = std_return * (252 ** 0.5) * 100  # Convert to %
        
        # Calculate Sharpe ratio
        sharpe = (annual_return - risk_free_rate) / annual_volatility if annual_volatility > 0 else 0
        
        return {
            "available": True,
            "sharpe_ratio": sharpe,
            "annual_return_pct": annual_return,
            "annual_volatility_pct": annual_volatility,
            "risk_free_rate_pct": risk_free_rate,
            "interpretation": self._interpret_sharpe(sharpe),
            "data_points": len(returns)
        }
    
    def get_performance_attribution(
        self,
        portfolio_snapshots: List[Dict[str, Any]],
        benchmark: str = "SPY"
    ) -> Dict[str, Any]:
        """Get comprehensive performance attribution metrics."""
        
        alpha_data = self.calculate_alpha(portfolio_snapshots, benchmark)
        beta_data = self.calculate_beta(portfolio_snapshots, benchmark)
        sharpe_data = self.calculate_sharpe_ratio(portfolio_snapshots)
        
        return {
            "alpha": alpha_data,
            "beta": beta_data,
            "sharpe": sharpe_data,
            "summary": self._generate_summary(alpha_data, beta_data, sharpe_data)
        }
    
    def _interpret_alpha(self, alpha: float) -> str:
        """Interpret alpha value."""
        if alpha > 5:
            return "Excellent - significantly outperforming market"
        elif alpha > 2:
            return "Good - outperforming market"
        elif alpha > -2:
            return "Neutral - tracking market"
        elif alpha > -5:
            return "Poor - underperforming market"
        else:
            return "Very Poor - significantly underperforming"
    
    def _interpret_beta(self, beta: float) -> str:
        """Interpret beta value."""
        if beta > 1.5:
            return "High volatility - moves 1.5x+ vs market (high risk/reward)"
        elif beta > 1.1:
            return "Moderate-high volatility - slightly more volatile than market"
        elif beta > 0.9:
            return "Market-like volatility - similar risk to market"
        elif beta > 0.5:
            return "Low volatility - less risky than market"
        else:
            return "Very low volatility - defensive portfolio"
    
    def _interpret_sharpe(self, sharpe: float) -> str:
        """Interpret Sharpe ratio."""
        if sharpe > 2.0:
            return "Excellent - very good risk-adjusted returns"
        elif sharpe > 1.0:
            return "Good - acceptable risk-adjusted returns"
        elif sharpe > 0:
            return "Fair - marginal risk-adjusted returns"
        else:
            return "Poor - losing money or excessive risk"
    
    def _generate_summary(
        self,
        alpha_data: Dict[str, Any],
        beta_data: Dict[str, Any],
        sharpe_data: Dict[str, Any]
    ) -> str:
        """Generate human-readable summary."""
        
        if not alpha_data.get('available'):
            return "Insufficient data for performance attribution"
        
        alpha = alpha_data.get('alpha', 0)
        beta = beta_data.get('beta', 1.0) if beta_data.get('available') else None
        sharpe = sharpe_data.get('sharpe_ratio', 0) if sharpe_data.get('available') else None
        
        summary = []
        
        # Alpha interpretation
        if alpha > 2:
            summary.append(f"✅ Outperforming market by {alpha:.1f}%")
        elif alpha > -2:
            summary.append(f"➡️ Tracking market (alpha: {alpha:+.1f}%)")
        else:
            summary.append(f"⚠️ Underperforming market by {abs(alpha):.1f}%")
        
        # Beta interpretation
        if beta is not None:
            if beta > 1.2:
                summary.append(f"⚡ High volatility (beta: {beta:.2f}) - higher risk/reward")
            elif beta < 0.8:
                summary.append(f"🛡️ Low volatility (beta: {beta:.2f}) - lower risk")
            else:
                summary.append(f"📊 Market-like risk (beta: {beta:.2f})")
        
        # Sharpe interpretation
        if sharpe is not None:
            if sharpe > 2.0:
                summary.append(f"⭐ Excellent risk-adjusted returns (Sharpe: {sharpe:.2f})")
            elif sharpe > 1.0:
                summary.append(f"✅ Good risk-adjusted returns (Sharpe: {sharpe:.2f})")
            else:
                summary.append(f"⚠️ Poor risk-adjusted returns (Sharpe: {sharpe:.2f})")
        
        return " | ".join(summary)
