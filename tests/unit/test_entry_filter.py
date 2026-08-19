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
    get_small_sample_watchlist,
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


# ---------------------------------------------------------------------------
# stock_reduced_min_trades = 5 (raised from 3, 2026-07-23)
# ---------------------------------------------------------------------------

def _stock_reduced_config(**kw) -> EntryFilterConfig:
    defaults = dict(
        min_volume=0,
        min_adr_pct=0,
        rolling_pf_gate=0.70,
        min_trades_for_gate=5,
        disabled=False,
        stock_reduced_mode=True,
        stock_reduced_pf_gate=1.0,
        stock_reduced_min_trades=5,
    )
    defaults.update(kw)
    return EntryFilterConfig(**defaults)


def test_stock_reduced_default_min_trades_is_5():
    """Default stock_reduced_min_trades must be 5 after 2026-07-23 change."""
    cfg = EntryFilterConfig()
    assert cfg.stock_reduced_min_trades == 5, (
        "default raised 3→5 to avoid false positives from small samples (2026-07-23)"
    )


def test_stock_reduced_not_triggered_below_min_trades():
    """Symbol with < 5 trades must NOT be blocked by stock_reduced even if PF < 1.0.
    Regression: before 2026-07-23, min_trades=3 blocked symbols with only 3
    all-loss trades, causing false positives for symbols with small sample sizes.
    """
    cfg = _stock_reduced_config()
    engine = EntryFilterEngine(cfg)
    # 4 trades, all losses → PF=0.0 but n < 5 → must NOT be blocked
    trades = _closed_trades("AVGO", [-400, -300, -200, -100])
    result = engine.filter(
        decisions=[_decision("AVGO")],
        records_by_symbol={},
        closed_trades=trades,
    )
    assert len(result.passed) == 1, (
        "AVGO with 4 all-loss trades must pass when min_trades=5 (small sample)"
    )


def test_stock_reduced_blocked_at_5_trades():
    """Symbol with ≥ 5 trades and PF < 1.0 IS blocked by stock_reduced."""
    cfg = _stock_reduced_config()
    engine = EntryFilterEngine(cfg)
    trades = _closed_trades("MDB", [-400, -300, -200, -100, -500])  # 5 losses
    result = engine.filter(
        decisions=[_decision("MDB")],
        records_by_symbol={},
        closed_trades=trades,
    )
    assert len(result.passed) == 0, "MDB with 5 all-loss trades must be blocked"


def test_stock_reduced_threshold_3_blocks_small_sample():
    """With min_trades=3, 3-trade all-loss symbol IS blocked (old behaviour)."""
    cfg = _stock_reduced_config(stock_reduced_min_trades=3)
    engine = EntryFilterEngine(cfg)
    trades = _closed_trades("AVGO", [-400, -300, -200])
    result = engine.filter(
        decisions=[_decision("AVGO")],
        records_by_symbol={},
        closed_trades=trades,
    )
    assert len(result.passed) == 0, "With min_trades=3, 3 all-loss trades must block"


def test_stock_reduced_env_default_reads_5(monkeypatch):
    """ENTRY_FILTER_STOCK_REDUCED_MIN_TRADES env default is now 5."""
    monkeypatch.delenv("ENTRY_FILTER_STOCK_REDUCED_MIN_TRADES", raising=False)
    cfg = EntryFilterConfig.from_env()
    assert cfg.stock_reduced_min_trades == 5


# ===========================================================================
# get_small_sample_watchlist (2026-08-05, observability-only, does not block)
# ===========================================================================

def test_watchlist_surfaces_small_sample_net_negative_stock():
    """n=3 < min_n=5, net PnL sharply negative -> appears on watchlist."""
    trades = _closed_trades("IBM", [-4011.19, -4382.52, -119.42])
    result = get_small_sample_watchlist(trades)
    symbols = {r["symbol"] for r in result}
    assert "IBM" in symbols
    entry = next(r for r in result if r["symbol"] == "IBM")
    assert entry["n_trades"] == 3
    assert entry["net_pnl"] < 0
    assert entry["win_rate"] == 0.0


def test_watchlist_excludes_symbols_at_or_above_stock_reduced_min_trades():
    """n >= stock_reduced_min_trades (5) is already covered by the real
    stock_reduced gate; it must NOT also appear on the watchlist."""
    trades = _closed_trades("MDB", [-100, -200, -300, -400, -500])
    result = get_small_sample_watchlist(trades)
    symbols = {r["symbol"] for r in result}
    assert "MDB" not in symbols


def test_watchlist_excludes_net_positive_symbols():
    """A small-sample symbol with net positive PnL should not be flagged."""
    trades = _closed_trades("MRVL", [500, -100])
    result = get_small_sample_watchlist(trades)
    symbols = {r["symbol"] for r in result}
    assert "MRVL" not in symbols


def test_watchlist_excludes_single_trade_symbols_by_default():
    """A single losing trade (n=1) is not even weak evidence; excluded by
    default min_trades=2."""
    trades = _closed_trades("CRDO", [-1000])
    result = get_small_sample_watchlist(trades)
    symbols = {r["symbol"] for r in result}
    assert "CRDO" not in symbols


def test_watchlist_excludes_etf_symbols():
    """ETF symbols are out of scope for this stock-only watchlist."""
    trades = _closed_trades("SMH", [-1000, -2000])
    result = get_small_sample_watchlist(trades, etf_symbols={"SMH"})
    symbols = {r["symbol"] for r in result}
    assert "SMH" not in symbols


def test_watchlist_excludes_pf_gate_skip_symbols():
    """Symbols in pf_gate_skip_symbols are exempted from the watchlist too
    (consistent with the real gates' skip-list behavior)."""
    cfg = EntryFilterConfig(pf_gate_skip_symbols=["AMD"])
    trades = _closed_trades("AMD", [-1000, -2000])
    result = get_small_sample_watchlist(trades, config=cfg)
    symbols = {r["symbol"] for r in result}
    assert "AMD" not in symbols


def test_watchlist_sorted_worst_first():
    """Results are sorted by net_pnl ascending (worst loss first)."""
    trades = (
        _closed_trades("AAA", [-100, -200])
        + _closed_trades("BBB", [-5000, -3000])
        + _closed_trades("CCC", [-500, -600])
    )
    result = get_small_sample_watchlist(trades)
    symbols_in_order = [r["symbol"] for r in result]
    assert symbols_in_order == ["BBB", "CCC", "AAA"]


def test_watchlist_does_not_mutate_input_or_block_anything():
    """Sanity check: this is observability-only. Returned dicts carry a note
    string documenting they are not auto-blocked."""
    trades = _closed_trades("PLTR", [-3824.68, -2887.71])
    result = get_small_sample_watchlist(trades)
    entry = next(r for r in result if r["symbol"] == "PLTR")
    assert "not auto-blocked" in entry["note"]


# ===========================================================================
# Gate 0: purchase_restricted_symbols (2026-08-19, JP semiconductor expansion
# Phase 2 — compliance/insider deny-list). See
# docs/jp_semiconductor_ai_expansion_plan.md section 1 and
# docs/jp_semiconductor_ai_expansion_phase2_design.md section 4.
# ===========================================================================

def test_purchase_restricted_symbol_is_blocked():
    """Acceptance: a symbol on purchase_restricted_symbols must be blocked
    from BUY, with a deny_reason mentioning 'purchase_restricted'."""
    cfg = EntryFilterConfig(purchase_restricted_symbols=["9984.T"])
    engine = EntryFilterEngine(config=cfg)
    decisions = [_decision("9984.T")]

    result = engine.filter(decisions, records_by_symbol={}, closed_trades=[])

    assert result.passed == []
    assert len(result.blocked) == 1
    blocked_symbol, reason = result.blocked[0]
    assert blocked_symbol == "9984.T"
    assert "purchase_restricted" in reason


def test_purchase_restricted_gate_short_circuits_other_gates():
    """Acceptance: purchase_restricted symbols are blocked even when they
    would otherwise pass every other gate (high volume, high ADR, no PF
    history) — Gate 0 must run first and short-circuit Gates 1-4."""
    cfg = EntryFilterConfig(
        purchase_restricted_symbols=["9984.T"],
        min_volume=500_000,
        min_adr_pct=1.0,
    )
    engine = EntryFilterEngine(config=cfg)
    decisions = [_decision("9984.T")]
    # Deliberately healthy market stats — would pass Gate 1/2 on their own.
    records = {"9984.T": _bars("9984.T", volume=5_000_000, high=110, low=100, close=105)}

    result = engine.filter(decisions, records_by_symbol=records, closed_trades=[])

    assert result.passed == []
    blocked_symbol, reason = result.blocked[0]
    assert blocked_symbol == "9984.T"
    assert "purchase_restricted" in reason
    assert "9984.T" in result.stats["purchase_restricted_blocked"]


def test_purchase_restricted_symbols_default_empty_does_not_block_anything():
    """Boundary: default config (empty deny-list) must not block any symbol
    via Gate 0 — existing behavior for all currently-traded symbols must be
    unchanged by this addition."""
    cfg = EntryFilterConfig()
    assert cfg.purchase_restricted_symbols == []

    engine = EntryFilterEngine(config=cfg)
    decisions = [_decision("NVDA")]
    records = {"NVDA": _bars("NVDA", volume=5_000_000, high=110, low=100, close=105)}

    result = engine.filter(decisions, records_by_symbol=records, closed_trades=[])

    assert "NVDA" not in [s for s, _ in result.blocked]
    assert result.stats["purchase_restricted_blocked"] == []


def test_from_env_reads_purchase_restricted_symbols(monkeypatch):
    """Config loading: ENTRY_FILTER_PURCHASE_RESTRICTED_SYMBOLS is parsed as
    a comma-separated, upper-cased list, consistent with
    ENTRY_FILTER_PF_GATE_SKIP_SYMBOLS's existing parsing behavior."""
    monkeypatch.setenv("ENTRY_FILTER_PURCHASE_RESTRICTED_SYMBOLS", "9984.t, 1234.T")

    cfg = EntryFilterConfig.from_env()

    assert cfg.purchase_restricted_symbols == ["9984.T", "1234.T"]


def test_from_env_purchase_restricted_symbols_defaults_to_empty(monkeypatch):
    """Fallback: when the env var is unset, purchase_restricted_symbols must
    default to an empty list (fail-open for this specific list is safe since
    the absence of a restriction is the status quo, not a security gap)."""
    monkeypatch.delenv("ENTRY_FILTER_PURCHASE_RESTRICTED_SYMBOLS", raising=False)

    cfg = EntryFilterConfig.from_env()

    assert cfg.purchase_restricted_symbols == []


def test_non_buy_decision_for_restricted_symbol_passes_through():
    """Boundary: non-buy actions (e.g. sell) for a restricted symbol are not
    affected by Gate 0 — the deny-list only blocks new BUY submission, not
    exiting an existing (legacy) position."""
    cfg = EntryFilterConfig(purchase_restricted_symbols=["9984.T"])
    engine = EntryFilterEngine(config=cfg)
    decisions = [_decision("9984.T", action="sell")]

    result = engine.filter(decisions, records_by_symbol={}, closed_trades=[])

    assert len(result.passed) == 1
    assert result.blocked == []
