"""Tests for Console services."""
import pytest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "console"))

from console.services.summary_service import SummaryService
from console.services.benchmark_service import BenchmarkService
from console.services.dashboard_service import DashboardService


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


class TestDashboardService:
    """Test dashboard service helpers."""

    def test_archive_history_shape(self):
        service = DashboardService(PROJECT_ROOT)
        history = service.get_archive_history()

        assert 'generated_at' in history
        assert 'current' in history
        assert 'archives' in history
        assert 'migration_docs' in history
        assert isinstance(history['archives'], list)
        assert isinstance(history['migration_docs'], list)

        if history['archives']:
            first = history['archives'][0]
            assert 'archive_path' in first
            assert 'archive_date' in first
            assert 'trade_count' in first

    def test_current_account_cutoff_uses_tracking_state_created_at(self, monkeypatch):
        service = DashboardService(PROJECT_ROOT)
        monkeypatch.setattr(service, '_load_tracking_state_metadata', lambda: {
            'created_at': '2026-05-12T00:17:00+00:00',
            'baseline_date': '2026-05-12',
        })

        cutoff = service._current_account_cutoff()

        assert cutoff.strftime('%Y-%m-%d %H:%M') == '2026-05-12 09:17'

    def test_get_tracked_symbols_prefers_news_collection_job_payload(self, monkeypatch):
        service = DashboardService(PROJECT_ROOT)
        monkeypatch.setattr(service, 'get_cron_jobs', lambda: {
            'jobs': [
                {
                    'name': 'stock_swing_news_collection',
                    'payload': {
                        'message': 'cd ~/stock_swing && python -u -m stock_swing.cli.collect_data --sources finnhub --symbols MRVL,CIEN,DELL,RBRK'
                    },
                }
            ]
        })

        assert service._get_tracked_symbols() == ['MRVL', 'CIEN', 'DELL', 'RBRK']

    def test_alerts_use_news_ingestion_scope(self, monkeypatch):
        service = DashboardService(PROJECT_ROOT)
        monkeypatch.setattr(service, 'get_news_ingestion_status', lambda news, tracked_symbols=None: {
            'missing_symbols': ['MRVL', 'CIEN'],
            'stale_symbols': ['DELL'],
        })
        monkeypatch.setattr(service, 'check_broker_tracker_consistency', lambda: {'available': False})

        alerts = service.get_alerts(
            overview={},
            trading={},
            positions={'positions': [], 'summary': {}},
            cron_jobs={'jobs': []},
            data_status={'counts': {}, 'freshness': {}, 'integrity': {}},
            news={'diagnostics': {'tracked_symbols': ['MRVL', 'CIEN', 'DELL']}},
        )

        messages = {alert['code']: alert['message'] for alert in alerts}
        assert messages['no_news_for_tracked_symbols'].endswith('MRVL, CIEN')
        assert messages['stale_news_symbols'].endswith('DELL')

    def test_check_broker_tracker_consistency_aggregates_duplicate_tracker_positions(self):
        service = DashboardService(PROJECT_ROOT)

        class _Resp:
            def __init__(self, payload):
                self.payload = payload

        class _Broker:
            def fetch_positions(self):
                return _Resp([
                    {'symbol': 'AAPL', 'qty': '10', 'avg_entry_price': '180.0'},
                ])

        class _Tracker:
            def _load_state(self):
                return None

            def get_open_positions(self):
                return [
                    {'symbol': 'AAPL', 'qty': 10, 'entry_price': 180.0},
                    {'symbol': 'AAPL', 'qty': 10, 'entry_price': 180.0},
                ]

        service._broker = _Broker()
        service._tracker = _Tracker()

        result = service.check_broker_tracker_consistency()

        assert result['available'] is True
        assert result['summary']['total_mismatches'] == 1
        mismatch = result['mismatches'][0]
        assert mismatch['symbol'] == 'AAPL'
        assert mismatch['broker_qty'] == 10
        assert mismatch['tracker_qty'] == 20
        assert mismatch['tracker_trade_count'] == 2

    def test_alerts_include_broker_tracker_mismatch(self, monkeypatch):
        service = DashboardService(PROJECT_ROOT)
        monkeypatch.setattr(service, 'get_news_ingestion_status', lambda news, tracked_symbols=None: {
            'missing_symbols': [],
            'stale_symbols': [],
        })
        monkeypatch.setattr(service, 'check_broker_tracker_consistency', lambda: {
            'available': True,
            'mismatches': [{'symbol': 'AAPL'}],
            'tracker_only': ['TSLA'],
            'summary': {'total_mismatches': 1},
        })

        alerts = service.get_alerts(
            overview={},
            trading={},
            positions={'positions': [], 'summary': {}},
            cron_jobs={'jobs': []},
            data_status={'counts': {}, 'freshness': {}, 'integrity': {}},
            news={'diagnostics': {'tracked_symbols': []}},
        )

        by_code = {alert['code']: alert for alert in alerts}
        assert 'broker_tracker_mismatch' in by_code
        assert 'tracker_phantom_positions' in by_code
        assert 'overview P&L may be wrong' in by_code['broker_tracker_mismatch']['message']
        assert 'inflate overview P&L' in by_code['tracker_phantom_positions']['message']


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
