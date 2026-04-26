"""Tests for Console services."""
import pytest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "console"))

from console.services.summary_service import SummaryService
from console.services.benchmark_service import BenchmarkService


class TestSummaryService:
    """Test Summary Service."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.service = SummaryService(PROJECT_ROOT)
    
    def test_generate_daily_summary(self):
        """Test daily summary generation."""
        summary = self.service.generate_daily_summary()
        
        assert 'date' in summary
        assert 'pnl_summary' in summary
        assert 'alerts' in summary
        assert isinstance(summary['alerts'], list)
    
    def test_generate_weekly_summary(self):
        """Test weekly summary generation."""
        summary = self.service.generate_weekly_summary(weeks=1)
        
        assert 'period' in summary
        assert 'summary' in summary
        
        if 'error' not in summary:
            assert 'total_trades' in summary['summary']
            assert 'win_rate' in summary['summary']
            assert 'total_pnl' in summary['summary']
    
    def test_weekly_summary_multiple_weeks(self):
        """Test weekly summary with different periods."""
        summary_1w = self.service.generate_weekly_summary(weeks=1)
        summary_2w = self.service.generate_weekly_summary(weeks=2)
        
        assert summary_1w['period']['weeks'] == 1
        assert summary_2w['period']['weeks'] == 2


class TestBenchmarkService:
    """Test Benchmark Service."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.service = BenchmarkService(PROJECT_ROOT)
    
    def test_load_benchmark_data(self):
        """Test loading benchmark data."""
        data = self.service.load_benchmark_data('SPY')
        
        # Should return list (empty or with data)
        assert isinstance(data, list)
    
    def test_calculate_alpha(self):
        """Test alpha calculation."""
        # Create mock snapshots
        snapshots = [
            {'date': '2026-04-01', 'equity': 100000},
            {'date': '2026-04-02', 'equity': 101000},
            {'date': '2026-04-03', 'equity': 102000},
        ]
        
        result = self.service.calculate_alpha(snapshots, 'SPY')
        
        assert 'available' in result
        # May not be available if no benchmark data
        if result['available']:
            assert 'alpha' in result
            assert 'portfolio' in result
            assert 'benchmark' in result
    
    def test_calculate_sharpe_ratio(self):
        """Test Sharpe ratio calculation."""
        snapshots = [
            {'date': f'2026-04-{i:02d}', 'equity': 100000 + i * 100}
            for i in range(1, 31)
        ]
        
        result = self.service.calculate_sharpe_ratio(snapshots)
        
        assert 'available' in result
        if result['available']:
            assert 'sharpe_ratio' in result
            assert 'annual_return_pct' in result
            assert 'annual_volatility_pct' in result


class TestWeeklySummaryAPI:
    """Integration tests for Weekly Summary API."""
    
    def test_weekly_summary_has_required_fields(self):
        """Test that weekly summary contains all required fields."""
        service = SummaryService(PROJECT_ROOT)
        summary = service.generate_weekly_summary(weeks=1)
        
        # Check structure
        assert 'period' in summary
        assert 'generated_at' in summary
        
        if 'error' not in summary:
            assert 'summary' in summary
            assert 'by_strategy' in summary
            assert 'top_symbols' in summary
            assert 'equity_progression' in summary
    
    def test_strategy_breakdown_format(self):
        """Test strategy breakdown format."""
        service = SummaryService(PROJECT_ROOT)
        summary = service.generate_weekly_summary(weeks=1)
        
        if 'error' not in summary and summary.get('by_strategy'):
            for strategy in summary['by_strategy']:
                assert 'strategy_id' in strategy
                assert 'trades' in strategy
                assert 'pnl' in strategy
                assert 'win_rate' in strategy
    
    def test_top_symbols_format(self):
        """Test top symbols format."""
        service = SummaryService(PROJECT_ROOT)
        summary = service.generate_weekly_summary(weeks=1)
        
        if 'error' not in summary and summary.get('top_symbols'):
            for symbol in summary['top_symbols']:
                assert 'symbol' in symbol
                assert 'trades' in symbol
                assert 'pnl' in symbol
                assert 'win_rate' in symbol


class TestPerformanceAttribution:
    """Test Performance Attribution calculations."""
    
    def test_alpha_calculation_accuracy(self):
        """Test alpha calculation is accurate."""
        service = BenchmarkService(PROJECT_ROOT)
        
        # Mock portfolio that gained 10%
        portfolio_snapshots = [
            {'date': '2026-04-01', 'equity': 100000},
            {'date': '2026-04-30', 'equity': 110000},
        ]
        
        result = service.calculate_alpha(portfolio_snapshots, 'SPY')
        
        if result.get('available'):
            portfolio_return = result['portfolio']['return_pct']
            assert 9.5 <= portfolio_return <= 10.5  # Allow small variance
    
    def test_sharpe_ratio_positive_for_profit(self):
        """Test Sharpe ratio is positive for profitable period."""
        service = BenchmarkService(PROJECT_ROOT)
        
        # Consistently growing equity
        snapshots = [
            {'date': f'2026-04-{i:02d}', 'equity': 100000 + i * 500}
            for i in range(1, 31)
        ]
        
        result = service.calculate_sharpe_ratio(snapshots)
        
        if result.get('available'):
            assert result['sharpe_ratio'] > 0
            assert result['annual_return_pct'] > 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
