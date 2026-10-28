"""Tests for BUY STOP LIST: get_permanent_block_summary() + console rendering.

Validates that:
  - get_permanent_block_summary() returns all symbols blocked by PF history
  - Independent of any run's BUY candidates (permanent / run-agnostic)
  - Correctly distinguishes stock_reduced vs rolling_pf_gate
  - ETF symbols exempt from stock_reduced
  - ConsoleRenderer shows BUY STOP LIST in DECISION FUNNEL section
"""
from __future__ import annotations

from stock_swing.risk.entry_filter import EntryFilterConfig, get_permanent_block_summary
from stock_swing.reporting.console_renderer import ConsoleRenderer
from stock_swing.reporting.console_summary import ConsoleSummary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(
    *,
    stock_reduced: bool = True,
    sr_gate: float = 1.0,
    sr_min: int = 5,
    pf_gate: float = 0.70,
    pf_min: int = 5,
) -> EntryFilterConfig:
    return EntryFilterConfig(
        stock_reduced_mode=stock_reduced,
        stock_reduced_pf_gate=sr_gate,
        stock_reduced_min_trades=sr_min,
        rolling_pf_gate=pf_gate,
        min_trades_for_gate=pf_min,
        min_volume=0,
        min_adr_pct=0,
    )


def _closed(symbol: str, pnls: list[float]) -> list[dict]:
    return [
        {
            "symbol": symbol,
            "status": "closed",
            "pnl": p,
            "holding_days": 5.0,
        }
        for p in pnls
    ]


def _summary_with_stop_list(stop_list: list[dict]) -> ConsoleSummary:
    return ConsoleSummary.build(
        run_id="test",
        equity=1_000_000.0,
        open_position_count=0,
        entry_filter_stats={"buy_stop_list": stop_list},
    )


# ---------------------------------------------------------------------------
# get_permanent_block_summary – unit tests
# ---------------------------------------------------------------------------

class TestGetPermanentBlockSummary:
    def test_stock_reduced_blocks_bad_symbol(self):
        """Symbol with ≥5 trades and PF<1.0 appears in stop list."""
        trades = _closed("MDB", [-400, -300, -200, -100, -500])  # 5 losses
        result = get_permanent_block_summary(trades, config=_cfg())
        syms = [r["symbol"] for r in result]
        assert "MDB" in syms
        mdb = next(r for r in result if r["symbol"] == "MDB")
        assert mdb["reason"] == "stock_reduced"
        assert mdb["n_trades"] == 5
        assert mdb["profit_factor"] == 0.0

    def test_symbol_with_few_trades_not_blocked(self):
        """Symbol with <5 trades must NOT appear in stop list (small sample)."""
        trades = _closed("AVGO", [-400, -300, -200])  # 3 losses, n<5
        result = get_permanent_block_summary(trades, config=_cfg())
        syms = [r["symbol"] for r in result]
        assert "AVGO" not in syms, "n=3 must not be blocked with min_trades=5"

    def test_good_symbol_not_in_stop_list(self):
        """Symbol with PF > 1.0 must NOT appear."""
        trades = _closed("PANW", [500, 400, 300, 200, -50])  # PF >> 1
        result = get_permanent_block_summary(trades, config=_cfg())
        syms = [r["symbol"] for r in result]
        assert "PANW" not in syms

    def test_etf_exempt_from_stock_reduced(self):
        """ETF symbols are exempt from stock_reduced gate.
        rolling_pf_gate may still apply (it's not ETF-specific),
        but reason must not be 'stock_reduced'.
        """
        trades = _closed("SMH", [-400, -300, -200, -100, -500])
        result = get_permanent_block_summary(
            trades, config=_cfg(), etf_symbols={"SMH"}
        )
        # SMH may appear due to rolling_pf_gate, but NOT due to stock_reduced
        smh_entries = [r for r in result if r["symbol"] == "SMH"]
        for entry in smh_entries:
            assert entry["reason"] != "stock_reduced", (
                "ETF must not be blocked by stock_reduced gate"
            )

    def test_rolling_pf_gate_applies_when_stock_reduced_off(self):
        """rolling_pf_gate blocks bad symbols even without stock_reduced."""
        trades = _closed("FTNT", [-100, -200, -300, -50, -75])  # PF=0, n=5
        result = get_permanent_block_summary(
            trades, config=_cfg(stock_reduced=False)
        )
        syms = [r["symbol"] for r in result]
        assert "FTNT" in syms
        ftnt = next(r for r in result if r["symbol"] == "FTNT")
        assert ftnt["reason"] == "rolling_pf_gate"

    def test_multiple_symbols_all_returned(self):
        trades = (
            _closed("AMD",  [-100] * 9) +      # 9 losses → PF=0, n=9
            _closed("NVDA", [500, 400, 300, 200, 100])  # all wins → not blocked
        )
        result = get_permanent_block_summary(trades, config=_cfg())
        syms = {r["symbol"] for r in result}
        assert "AMD" in syms
        assert "NVDA" not in syms

    def test_sorted_by_pf_ascending_within_group(self):
        """Results sorted PF ascending (worst first) within each reason group."""
        trades = (
            _closed("MDB",  [-100] * 5) +          # PF=0.000
            _closed("AMD",  [-100, -100, 50, -100, -100])  # PF≈0.2
        )
        result = get_permanent_block_summary(trades, config=_cfg())
        sr = [r for r in result if r["reason"] == "stock_reduced"]
        pfs = [r["profit_factor"] for r in sr]
        assert pfs == sorted(pfs), "results must be sorted PF ascending"

    def test_reason_detail_contains_threshold(self):
        """reason_detail includes PF value, threshold and n."""
        trades = _closed("CRWD", [-100] * 5 + [50])  # PF < 1.0, n=6
        result = get_permanent_block_summary(trades, config=_cfg())
        crwd = next((r for r in result if r["symbol"] == "CRWD"), None)
        assert crwd is not None
        assert "PF=" in crwd["reason_detail"]
        assert "n=6" in crwd["reason_detail"]

    def test_empty_closed_trades_returns_empty(self):
        result = get_permanent_block_summary([], config=_cfg())
        assert result == []


# ---------------------------------------------------------------------------
# ConsoleRenderer – BUY STOP LIST display
# ---------------------------------------------------------------------------

class TestBuyStopListRendering:
    def _render(self, stop_list: list[dict]) -> str:
        s = _summary_with_stop_list(stop_list)
        return ConsoleRenderer().render(s)

    def test_buy_stop_list_shown_when_present(self):
        stop_list = [
            {"symbol": "MDB", "n_trades": 6, "profit_factor": 0.0,
             "reason": "stock_reduced", "reason_detail": "PF=0.000 < 1.00 (n=6, min_n=5)"},
        ]
        out = self._render(stop_list)
        assert "BUY STOP LIST" in out
        assert "MDB" in out
        assert "0.000" in out

    def test_buy_stop_list_absent_when_empty(self):
        out = self._render([])
        assert "BUY STOP LIST" not in out

    def test_reason_group_header_shown(self):
        """Group header [stock_reduced (...)] must appear."""
        stop_list = [
            {"symbol": "AMD", "n_trades": 9, "profit_factor": 0.549,
             "reason": "stock_reduced", "reason_detail": "PF=0.549 < 1.00 (n=9, min_n=5)"},
        ]
        out = self._render(stop_list)
        assert "stock_reduced" in out

    def test_multiple_symbols_all_rendered(self):
        stop_list = [
            {"symbol": sym, "n_trades": 5, "profit_factor": 0.1 * i,
             "reason": "stock_reduced", "reason_detail": f"PF={0.1*i:.3f}"}
            for i, sym in enumerate(["MDB", "RBRK", "AMD"])
        ]
        out = self._render(stop_list)
        for sym in ["MDB", "RBRK", "AMD"]:
            assert sym in out

    def test_rolling_pf_gate_reason_shown(self):
        stop_list = [
            {"symbol": "KLAC", "n_trades": 6, "profit_factor": 0.028,
             "reason": "rolling_pf_gate",
             "reason_detail": "PF=0.028 < 0.70 (n=6, min_n=5)"},
        ]
        out = self._render(stop_list)
        assert "rolling_pf_gate" in out
        assert "KLAC" in out

    def test_buy_stop_list_inside_decision_funnel(self):
        """BUY STOP LIST must appear after DECISION FUNNEL in the output."""
        stop_list = [
            {"symbol": "MDB", "n_trades": 6, "profit_factor": 0.0,
             "reason": "stock_reduced", "reason_detail": "PF=0.000 < 1.00 (n=6, min_n=5)"},
        ]
        out = self._render(stop_list)
        funnel_pos = out.find("DECISION FUNNEL")
        stop_pos = out.find("BUY STOP LIST")
        assert funnel_pos >= 0, "DECISION FUNNEL section must be present"
        assert stop_pos >= 0, "BUY STOP LIST must be present"
        assert funnel_pos < stop_pos, "BUY STOP LIST must come after DECISION FUNNEL header"
