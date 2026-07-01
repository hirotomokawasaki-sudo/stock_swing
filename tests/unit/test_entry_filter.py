"""R2-D: Tests for EntryFilterEngine (volume / ADR / rolling PF gate)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from stock_swing.risk.entry_filter import (
    EntryFilterConfig,
    EntryFilterEngine,
    SymbolMarketStats,
    compute_market_stats,
    compute_rolling_pf,
)


# ---------------------------------------------------------------------------
# Minimal DecisionRecord stub
# ---------------------------------------------------------------------------

@dataclass
class _Decision:
    symbol: str
    action: str
    deny_reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Minimal CanonicalRecord stub
# ---------------------------------------------------------------------------

@dataclass
class _Rec:
    symbol: str
    payload: dict[str, Any]

    # Satisfy minimal CanonicalRecord interface
    event_time: datetime = field(
        default_factory=lambda: datetime(2026, 6, 1, tzinfo=timezone.utc)
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ETF_SYMS = {"SMH", "SOXX", "QQQ"}

_CFG = EntryFilterConfig(
    min_volume=500_000,
    min_adr_pct=1.0,
    rolling_pf_gate=0.70,
    min_trades_for_gate=5,
    disabled=False,
)


def _bars(symbol: str, volume: float, high: float, low: float, close: float, n: int = 20) -> list[_Rec]:
    return [_Rec(symbol=symbol, payload={"volume": volume, "high": high, "low": low, "close": close})] * n


def _decision(symbol: str, action: str = "buy") -> _Decision:
    return _Decision(symbol=symbol, action=action)


def _closed_trades(symbol: str, pnls: list[float]) -> list[dict]:
    return [{"symbol": symbol, "pnl": p, "status": "closed"} for p in pnls]


# ===========================================================================
# compute_market_stats
# ===========================================================================

def test_market_stats_volume():
    recs = {"NVDA": _bars("NVDA", volume=1_000_000, high=110, low=100, close=105)}
    stats = compute_market_stats(recs)
    assert stats["NVDA"].avg_volume == pytest.approx(1_000_000)


def test_market_stats_adr_pct():
    # ADR% = (high-low)/close * 100 = (110-100)/105 * 100 ≈ 9.52%
    recs = {"NVDA": _bars("NVDA", volume=1_000_000, high=110, low=100, close=105)}
    stats = compute_market_stats(recs)
    assert stats["NVDA"].avg_adr_pct == pytest.approx((110 - 100) / 105 * 100)


def test_market_stats_empty():
    stats = compute_market_stats({"XYZ": []})
    assert stats["XYZ"].avg_volume is None
    assert stats["XYZ"].avg_adr_pct is None


# ===========================================================================
# compute_rolling_pf
# ===========================================================================

def test_rolling_pf_below_threshold():
    trades = _closed_trades("AMD", [100, -200, -300, -100, -50])
    pf = compute_rolling_pf(trades, min_trades=5)
    assert pf["AMD"].profit_factor is not None
    assert pf["AMD"].profit_factor < 0.70


def test_rolling_pf_above_threshold():
    trades = _closed_trades("AMAT", [500, 300, 200, -100, -50])
    pf = compute_rolling_pf(trades, min_trades=5)
    assert pf["AMAT"].profit_factor is not None
    assert pf["AMAT"].profit_factor > 1.0


def test_rolling_pf_not_enough_trades():
    trades = _closed_trades("CRDO", [100, -50])  # only 2 trades
    pf = compute_rolling_pf(trades, min_trades=5)
    assert pf["CRDO"].profit_factor is None  # gate not triggered


def test_rolling_pf_all_wins():
    trades = _closed_trades("NBIS", [100, 200, 300, 400, 500])
    pf = compute_rolling_pf(trades, min_trades=5)
    assert pf["NBIS"].profit_factor == 999.0  # no losses → inf


# ===========================================================================
# EntryFilterEngine — volume gate
# ===========================================================================

def test_volume_gate_blocks_low_volume_stock():
    engine = EntryFilterEngine(_CFG)
    rbs = {"INTC": _bars("INTC", volume=100_000, high=35, low=33, close=34)}
    result = engine.filter(
        decisions=[_decision("INTC")],
        records_by_symbol=rbs,
        closed_trades=[],
        etf_symbols=ETF_SYMS,
    )
    assert len(result.passed) == 0
    assert len(result.blocked) == 1
    sym, reason = result.blocked[0]
    assert sym == "INTC"
    assert "low_volume" in reason


def test_volume_gate_passes_high_volume():
    engine = EntryFilterEngine(_CFG)
    rbs = {"NVDA": _bars("NVDA", volume=10_000_000, high=130, low=122, close=126)}
    result = engine.filter(
        decisions=[_decision("NVDA")],
        records_by_symbol=rbs,
        closed_trades=[],
        etf_symbols=ETF_SYMS,
    )
    assert len(result.passed) == 1
    assert len(result.blocked) == 0


def test_volume_gate_exempts_etf():
    engine = EntryFilterEngine(_CFG)
    # ETF with very low volume — should still pass
    rbs = {"SMH": _bars("SMH", volume=50_000, high=250, low=245, close=248)}
    result = engine.filter(
        decisions=[_decision("SMH")],
        records_by_symbol=rbs,
        closed_trades=[],
        etf_symbols=ETF_SYMS,
    )
    assert len(result.passed) == 1
    assert len(result.blocked) == 0


# ===========================================================================
# EntryFilterEngine — ADR gate
# ===========================================================================

def test_adr_gate_blocks_flat_stock():
    # ADR% = (101-100)/100 * 100 = 1.0% exactly — should be blocked (< 1.0 is block, == 1.0 passes)
    # Use 0.5% ADR
    engine = EntryFilterEngine(_CFG)
    rbs = {"MSFT": _bars("MSFT", volume=5_000_000, high=100.5, low=100.0, close=100.25)}
    # ADR% = (100.5-100.0)/100.25 * 100 ≈ 0.499% < 1.0 → block
    result = engine.filter(
        decisions=[_decision("MSFT")],
        records_by_symbol=rbs,
        closed_trades=[],
        etf_symbols=ETF_SYMS,
    )
    assert len(result.blocked) == 1
    _, reason = result.blocked[0]
    assert "low_adr" in reason


def test_adr_gate_passes_volatile_stock():
    engine = EntryFilterEngine(_CFG)
    # ADR% = (120-110)/115 * 100 ≈ 8.7%
    rbs = {"AMD": _bars("AMD", volume=5_000_000, high=120, low=110, close=115)}
    result = engine.filter(
        decisions=[_decision("AMD")],
        records_by_symbol=rbs,
        closed_trades=[],
        etf_symbols=ETF_SYMS,
    )
    assert len(result.passed) == 1


def test_adr_gate_exempts_etf():
    engine = EntryFilterEngine(_CFG)
    rbs = {"SOXX": _bars("SOXX", volume=5_000_000, high=200.1, low=200.0, close=200.05)}
    result = engine.filter(
        decisions=[_decision("SOXX")],
        records_by_symbol=rbs,
        closed_trades=[],
        etf_symbols=ETF_SYMS,
    )
    assert len(result.passed) == 1


# ===========================================================================
# EntryFilterEngine — rolling PF gate
# ===========================================================================

def test_pf_gate_blocks_bad_symbol():
    engine = EntryFilterEngine(_CFG)
    rbs = {"INTC": _bars("INTC", volume=5_000_000, high=35, low=33, close=34)}
    # 5 trades, heavy losses → PF < 0.70
    trades = _closed_trades("INTC", [50, -200, -300, -100, -150])
    result = engine.filter(
        decisions=[_decision("INTC")],
        records_by_symbol=rbs,
        closed_trades=trades,
        etf_symbols=ETF_SYMS,
    )
    assert len(result.blocked) == 1
    _, reason = result.blocked[0]
    assert "rolling_pf_gate" in reason


def test_pf_gate_not_triggered_few_trades():
    engine = EntryFilterEngine(_CFG)
    rbs = {"CRDO": _bars("CRDO", volume=5_000_000, high=35, low=33, close=34)}
    # Only 2 trades → gate not triggered even with bad PF
    trades = _closed_trades("CRDO", [10, -1000])
    result = engine.filter(
        decisions=[_decision("CRDO")],
        records_by_symbol=rbs,
        closed_trades=trades,
        etf_symbols=ETF_SYMS,
    )
    assert len(result.passed) == 1


def test_pf_gate_applies_to_etf():
    engine = EntryFilterEngine(_CFG)
    rbs = {"SMH": _bars("SMH", volume=500_000, high=260, low=255, close=258)}
    # ETF exempt from volume/ADR but PF gate still applies
    trades = _closed_trades("SMH", [50, -500, -400, -300, -200])
    result = engine.filter(
        decisions=[_decision("SMH")],
        records_by_symbol=rbs,
        closed_trades=trades,
        etf_symbols=ETF_SYMS,
    )
    assert len(result.blocked) == 1
    _, reason = result.blocked[0]
    assert "rolling_pf_gate" in reason


# ===========================================================================
# Sell decisions always pass through
# ===========================================================================

def test_sell_always_passes():
    engine = EntryFilterEngine(_CFG)
    rbs = {"INTC": _bars("INTC", volume=1_000, high=35.1, low=35.0, close=35.05)}
    trades = _closed_trades("INTC", [10, -500, -400, -300, -200])
    result = engine.filter(
        decisions=[_decision("INTC", action="sell")],
        records_by_symbol=rbs,
        closed_trades=trades,
        etf_symbols=ETF_SYMS,
    )
    assert len(result.passed) == 1
    assert len(result.blocked) == 0


# ===========================================================================
# Disabled mode
# ===========================================================================

def test_disabled_bypasses_all():
    cfg = EntryFilterConfig(
        min_volume=999_999_999,
        min_adr_pct=99.0,
        rolling_pf_gate=99.0,
        min_trades_for_gate=1,
        disabled=True,
    )
    engine = EntryFilterEngine(cfg)
    rbs = {"INTC": _bars("INTC", volume=1, high=35.01, low=35.0, close=35.0)}
    trades = _closed_trades("INTC", [-100, -200, -300, -400, -500])
    result = engine.filter(
        decisions=[_decision("INTC")],
        records_by_symbol=rbs,
        closed_trades=trades,
        etf_symbols=ETF_SYMS,
    )
    assert len(result.passed) == 1
    assert len(result.blocked) == 0


# ===========================================================================
# Multiple decisions — mixed outcomes
# ===========================================================================

def test_mixed_decisions():
    engine = EntryFilterEngine(_CFG)
    rbs = {
        # NVDA: passes all gates
        "NVDA": _bars("NVDA", volume=10_000_000, high=130, low=120, close=125),
        # INTC: fails volume
        "INTC": _bars("INTC", volume=100_000, high=35.5, low=34.5, close=35.0),
        # AMD: fails rolling PF
        "AMD": _bars("AMD", volume=5_000_000, high=120, low=110, close=115),
    }
    trades = _closed_trades("AMD", [100, -500, -400, -300, -200])
    result = engine.filter(
        decisions=[_decision("NVDA"), _decision("INTC"), _decision("AMD")],
        records_by_symbol=rbs,
        closed_trades=trades,
        etf_symbols=ETF_SYMS,
    )
    assert len(result.passed) == 1
    assert result.passed[0].symbol == "NVDA"
    assert len(result.blocked) == 2
    blocked_syms = {sym for sym, _ in result.blocked}
    assert "INTC" in blocked_syms
    assert "AMD" in blocked_syms
