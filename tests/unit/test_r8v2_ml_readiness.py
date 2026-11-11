"""2026-08-14 (roadmap gap #4): tests for check_r8v2_ml_readiness.py.

Ensures R8-v2's "clean joinable outcomes >= 300" / "clean labels >= 1,000"
start conditions are checked against attributable-origin trade counts
(PnlTracker.get_attribution_quality_breakdown()'s "attributable" bucket),
not raw total_closed counts -- since a "clean label" for calibration/ML
must be traceable to an actual strategy decision, not just any closed trade.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_r8v2_ml_readiness.py"
_spec = importlib.util.spec_from_file_location("check_r8v2_ml_readiness", _SCRIPT_PATH)
_module = importlib.util.module_from_spec(_spec)
sys.modules["check_r8v2_ml_readiness"] = _module
_spec.loader.exec_module(_module)

check_readiness = _module.check_readiness


def _mock_breakdown(attributable_count: int, untracked_count: int, attributable_pf=1.3, untracked_pf=0.9):
    return {
        "attributable": {"count": attributable_count, "profit_factor": attributable_pf},
        "untracked_origin": {"count": untracked_count, "profit_factor": untracked_pf},
        "all": {"count": attributable_count + untracked_count, "profit_factor": None},
    }


class TestCheckReadiness:
    def test_not_ready_when_attributable_below_calibration_threshold(self):
        mock_tracker = MagicMock()
        mock_tracker.get_attribution_quality_breakdown.return_value = _mock_breakdown(25, 203)
        with patch.object(_module, "PnLTracker", return_value=mock_tracker):
            result = check_readiness()
        assert result["calibration_ready"] is False
        assert result["ml_training_ready"] is False
        assert result["attributable_count"] == 25

    def test_calibration_ready_when_attributable_meets_threshold(self):
        mock_tracker = MagicMock()
        mock_tracker.get_attribution_quality_breakdown.return_value = _mock_breakdown(300, 100)
        with patch.object(_module, "PnLTracker", return_value=mock_tracker):
            result = check_readiness()
        assert result["calibration_ready"] is True
        assert result["ml_training_ready"] is False

    def test_ml_training_ready_when_attributable_meets_1000(self):
        mock_tracker = MagicMock()
        mock_tracker.get_attribution_quality_breakdown.return_value = _mock_breakdown(1000, 50)
        with patch.object(_module, "PnLTracker", return_value=mock_tracker):
            result = check_readiness()
        assert result["calibration_ready"] is True
        assert result["ml_training_ready"] is True

    def test_high_total_closed_but_low_attributable_is_not_ready(self):
        """Key regression: total_closed reaching 300 via untracked-origin
        trades alone must NOT be reported as calibration-ready -- this is
        exactly the gap #4 scenario the script exists to prevent."""
        mock_tracker = MagicMock()
        mock_tracker.get_attribution_quality_breakdown.return_value = _mock_breakdown(50, 500)
        with patch.object(_module, "PnLTracker", return_value=mock_tracker):
            result = check_readiness()
        assert result["total_closed_count"] == 550  # well above 300
        assert result["calibration_ready"] is False  # but attributable=50 < 300

    def test_attributable_ratio_computed_correctly(self):
        mock_tracker = MagicMock()
        mock_tracker.get_attribution_quality_breakdown.return_value = _mock_breakdown(25, 203)
        with patch.object(_module, "PnLTracker", return_value=mock_tracker):
            result = check_readiness()
        assert result["attributable_ratio_pct"] == round(25 / 228 * 100, 1)

    def test_zero_total_closed_no_crash(self):
        mock_tracker = MagicMock()
        mock_tracker.get_attribution_quality_breakdown.return_value = _mock_breakdown(0, 0)
        with patch.object(_module, "PnLTracker", return_value=mock_tracker):
            result = check_readiness()
        assert result["attributable_ratio_pct"] == 0.0
        assert result["calibration_ready"] is False

    def test_pf_values_passed_through(self):
        mock_tracker = MagicMock()
        mock_tracker.get_attribution_quality_breakdown.return_value = _mock_breakdown(
            25, 203, attributable_pf=1.317, untracked_pf=0.882,
        )
        with patch.object(_module, "PnLTracker", return_value=mock_tracker):
            result = check_readiness()
        assert result["attributable_pf"] == 1.317
        assert result["untracked_origin_pf"] == 0.882


class TestCheckReadinessRealData:
    def test_normal_reader_counts_synthetic_attribution(self, tmp_path, monkeypatch):
        import json
        folder = tmp_path / 'data/tracking'
        folder.mkdir(parents=True)
        rows = [{'trade_id': f'fixture-{i}', 'symbol': 'IBM', 'status': 'closed',
                 'qty': 1, 'entry_price': 100, 'exit_price': 101, 'pnl': 1,
                 'strategy_id': strategy, 'entry_time': '2026-08-01T14:00:00Z',
                 'exit_time': '2026-08-02T14:00:00Z'}
                for i, strategy in enumerate(['breakout_momentum_v1',
                    'breakout_momentum_v1', 'broker_reconstructed'])]
        (folder / 'pnl_state.json').write_text(json.dumps({'last_updated': '2026-08-02T15:00:00+00:00', 'trades': rows}))
        (folder / 'trade_events.jsonl').write_text('')
        monkeypatch.setattr(_module, 'ROOT', tmp_path)
        result = check_readiness()
        assert result['attributable_count'] == 2
        assert result['untracked_origin_count'] == 1
        assert result['total_closed_count'] == 3
        assert result['attributable_ratio_pct'] == 66.7
        assert result['calibration_ready'] is False
        assert result['ml_training_ready'] is False
