"""2026-08-14: Stop Loss counterfactual cost/benefit analysis tests.

Covers scripts/analyze_stop_loss_post_exit.py's counterfactual PnL
computation, added as the new primary metric per the "役割純化" (role
purification) stop_loss redesign: stop_loss is a tactical short-term loss
cap, not a long-term crash-protection mechanism. Its value must be measured
by actual cost/benefit vs. holding, not by "did price fall further after
exit" (which is a meaningless metric for high-volatility symbols).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "analyze_stop_loss_post_exit.py"
_spec = importlib.util.spec_from_file_location("analyze_stop_loss_post_exit", _SCRIPT_PATH)
_module = importlib.util.module_from_spec(_spec)
sys.modules["analyze_stop_loss_post_exit"] = _module
_spec.loader.exec_module(_module)

compute_counterfactual_pnl = _module.compute_counterfactual_pnl
compute_counterfactual_pnl_with_qty = _module.compute_counterfactual_pnl_with_qty


class TestComputeCounterfactualPnlWithQty:
    def test_holding_would_have_been_better(self):
        """Stopped out at a loss, but price later recovered above entry ->
        holding would have been better (diff < 0)."""
        result = compute_counterfactual_pnl_with_qty(
            entry_price=100.0, actual_pnl=-500.0, last_price=110.0, qty=50.0,
        )
        # counterfactual: 50 * (110-100) = +500 (would have been a winner)
        assert result["counterfactual_pnl"] == 500.0
        assert result["diff"] == -1000.0  # -500 - 500
        assert result["would_have_been_better_to_hold"] is True

    def test_stopping_out_was_correct(self):
        """Price kept falling after exit -> stopping out saved money (diff > 0)."""
        result = compute_counterfactual_pnl_with_qty(
            entry_price=100.0, actual_pnl=-300.0, last_price=70.0, qty=100.0,
        )
        # counterfactual: 100 * (70-100) = -3000 (would have been much worse)
        assert result["counterfactual_pnl"] == -3000.0
        assert result["diff"] == 2700.0  # -300 - (-3000)
        assert result["would_have_been_better_to_hold"] is False

    def test_exactly_breakeven_counterfactual(self):
        """last_price == entry_price -> counterfactual pnl is exactly 0."""
        result = compute_counterfactual_pnl_with_qty(
            entry_price=100.0, actual_pnl=-200.0, last_price=100.0, qty=20.0,
        )
        assert result["counterfactual_pnl"] == 0.0
        assert result["diff"] == -200.0
        assert result["would_have_been_better_to_hold"] is True  # -200 < 0 (holding=0 > -200)

    def test_diff_exactly_zero_not_better_to_hold(self):
        """diff == 0 (actual == counterfactual) must not report 'better to hold'
        (strict < comparison, not <=)."""
        result = compute_counterfactual_pnl_with_qty(
            entry_price=100.0, actual_pnl=-500.0, last_price=90.0, qty=50.0,
        )
        # counterfactual: 50 * (90-100) = -500, diff = -500 - (-500) = 0
        assert result["diff"] == 0.0
        assert result["would_have_been_better_to_hold"] is False

    def test_negative_qty_short_position_handled(self):
        """Negative qty (theoretically a short position) still computes
        linearly without crashing -- not a supported use case in this
        codebase (stop_loss trades are long-only) but must not raise."""
        result = compute_counterfactual_pnl_with_qty(
            entry_price=100.0, actual_pnl=-100.0, last_price=90.0, qty=-10.0,
        )
        assert result["counterfactual_pnl"] == 100.0  # -10 * (90-100) = 100


class TestComputeCounterfactualPnl:
    """The qty-less variant, which derives qty from (exit_price - entry_price)
    vs actual_pnl. Used as a fallback when the trade record lacks an explicit
    qty field."""

    def test_derives_qty_correctly_from_price_move(self):
        # actual_pnl = qty * (exit - entry); if qty=50 and price moved -10,
        # actual_pnl should be -500.
        result = compute_counterfactual_pnl(
            entry_price=100.0, exit_price=90.0, actual_pnl=-500.0, last_price=110.0,
        )
        assert result is not None
        # derived qty = -500 / (90-100) = 50
        # counterfactual = 50 * (110-100) = 500
        assert result["counterfactual_pnl"] == 500.0
        assert result["diff"] == -1000.0

    def test_returns_none_when_entry_equals_exit(self):
        """price_move == 0 -> cannot derive qty -> None (fail-safe, not a
        crash or a division-by-zero)."""
        result = compute_counterfactual_pnl(
            entry_price=100.0, exit_price=100.0, actual_pnl=0.0, last_price=90.0,
        )
        assert result is None

    def test_consistent_with_explicit_qty_variant(self):
        """When qty can be cleanly derived, both functions must agree."""
        entry, exit_p, qty = 50.0, 45.0, 200.0
        actual_pnl = qty * (exit_p - entry)  # -1000.0
        last_price = 55.0

        derived = compute_counterfactual_pnl(entry, exit_p, actual_pnl, last_price)
        explicit = compute_counterfactual_pnl_with_qty(entry, actual_pnl, last_price, qty)

        assert derived is not None
        assert abs(derived["counterfactual_pnl"] - explicit["counterfactual_pnl"]) < 1e-9
        assert abs(derived["diff"] - explicit["diff"]) < 1e-9


class TestAnalyzeIntegration:
    """Verify analyze() attaches counterfactual fields to results, using a
    monkeypatched fetch_post_exit_prices to avoid network calls."""

    def test_analyze_attaches_counterfactual_fields(self, monkeypatch):
        def _fake_fetch(symbol, exit_date_str, days=15):
            # Simple ascending price series (recovery scenario)
            return {
                "2026-01-02": 95.0,
                "2026-01-03": 98.0,
                "2026-01-04": 102.0,
                "2026-01-05": 105.0,
                "2026-01-06": 110.0,
            }

        monkeypatch.setattr(_module, "fetch_post_exit_prices", _fake_fetch)

        trades = [{
            "symbol": "TEST",
            "exit_time": "2026-01-01T00:00:00Z",
            "entry_price": 100.0,
            "exit_price": 90.0,
            "pnl": -1000.0,
            "qty": 100.0,
            "return_pct": -0.10,
        }]

        analysis = _module.analyze(trades, lookforward_days=5)
        assert len(analysis["results"]) == 1
        r = analysis["results"][0]
        assert r["counterfactual_pnl"] is not None
        # last_price = 110.0 -> counterfactual = 100 * (110-100) = 1000
        assert r["counterfactual_pnl"] == 1000.0
        assert r["counterfactual_diff"] == -2000.0  # -1000 - 1000

    def test_analyze_falls_back_to_derived_qty_when_missing(self, monkeypatch):
        def _fake_fetch(symbol, exit_date_str, days=15):
            return {"2026-01-02": 105.0}

        monkeypatch.setattr(_module, "fetch_post_exit_prices", _fake_fetch)

        trades = [{
            "symbol": "TEST2",
            "exit_time": "2026-01-01T00:00:00Z",
            "entry_price": 100.0,
            "exit_price": 90.0,
            "pnl": -500.0,  # qty derived = -500 / (90-100) = 50
            # qty field intentionally omitted
            "return_pct": -0.10,
        }]

        analysis = _module.analyze(trades, lookforward_days=1)
        r = analysis["results"][0]
        assert r["counterfactual_pnl"] is not None
        # counterfactual = 50 * (105-100) = 250
        assert r["counterfactual_pnl"] == 250.0
