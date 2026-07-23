"""R2-D: Entry filter engine for buy candidates.

Applies three quality gates before a buy order is submitted:

1. **Volume gate**: avg daily volume < MIN_VOLUME  → deny
2. **ADR gate**:    avg daily range %  < MIN_ADR_PCT → deny
3. **Rolling PF gate**: per-symbol closed PF < PF_THRESHOLD
                        (only if >= MIN_TRADES_FOR_GATE closed trades exist)

ETF symbols are **exempt** from Volume and ADR gates (handled separately).
Rolling PF gate applies to both ETFs and stocks.

Config (env overrides):
  ENTRY_FILTER_MIN_VOLUME            default 500_000  (shares/day)
  ENTRY_FILTER_MIN_ADR_PCT           default 1.0      (%)
  ENTRY_FILTER_ROLLING_PF_GATE       default 0.70
  ENTRY_FILTER_MIN_TRADES_FOR_GATE   default 5
  ENTRY_FILTER_DISABLED              default false    (set "true" to bypass all)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------

@dataclass
class EntryFilterConfig:
    """Threshold configuration for EntryFilterEngine."""

    min_volume: float = 500_000        # avg daily volume (shares)
    min_adr_pct: float = 1.0           # avg daily range %
    rolling_pf_gate: float = 0.70      # per-symbol rolling PF threshold
    min_trades_for_gate: int = 5       # min closed trades to apply PF gate
    disabled: bool = False             # bypass all filters
    # F6: stock-reduced mode — individual stocks require stricter PF gate
    stock_reduced_mode: bool = False   # set ENTRY_FILTER_STOCK_REDUCED=true
    stock_reduced_pf_gate: float = 1.0 # PF threshold for stocks in reduced mode
    stock_reduced_min_trades: int = 5  # min trades to apply stricter gate (raised 3→5: 2026-07-23)

    @classmethod
    def from_env(cls) -> "EntryFilterConfig":
        return cls(
            min_volume=float(os.environ.get("ENTRY_FILTER_MIN_VOLUME", 500_000)),
            min_adr_pct=float(os.environ.get("ENTRY_FILTER_MIN_ADR_PCT", 1.0)),
            rolling_pf_gate=float(os.environ.get("ENTRY_FILTER_ROLLING_PF_GATE", 0.70)),
            min_trades_for_gate=int(os.environ.get("ENTRY_FILTER_MIN_TRADES_FOR_GATE", 5)),
            disabled=os.environ.get("ENTRY_FILTER_DISABLED", "").lower() in ("1", "true", "yes"),
            stock_reduced_mode=os.environ.get("ENTRY_FILTER_STOCK_REDUCED", "").lower() in ("1", "true", "yes"),
            stock_reduced_pf_gate=float(os.environ.get("ENTRY_FILTER_STOCK_REDUCED_PF_GATE", 1.0)),
            stock_reduced_min_trades=int(os.environ.get("ENTRY_FILTER_STOCK_REDUCED_MIN_TRADES", 5)),
        )


# ---------------------------------------------------------------------------
# Per-symbol market stats (computed from OHLCV bars)
# ---------------------------------------------------------------------------

@dataclass
class SymbolMarketStats:
    symbol: str
    avg_volume: float | None = None    # shares/day
    avg_adr_pct: float | None = None   # %
    bar_count: int = 0


def compute_market_stats(
    records_by_symbol: dict[str, list[Any]],
) -> dict[str, SymbolMarketStats]:
    """Compute avg_volume and avg_adr_pct from OHLCV CanonicalRecords.

    Args:
        records_by_symbol: symbol → list of CanonicalRecord (daily bars)

    Returns:
        dict of symbol → SymbolMarketStats
    """
    stats: dict[str, SymbolMarketStats] = {}
    for symbol, recs in records_by_symbol.items():
        if not recs:
            stats[symbol] = SymbolMarketStats(symbol=symbol)
            continue

        volumes: list[float] = []
        adr_pcts: list[float] = []

        for rec in recs:
            payload = getattr(rec, "payload", {}) or {}
            vol = payload.get("volume")
            high = payload.get("high")
            low = payload.get("low")
            close = payload.get("close")

            if vol is not None and vol > 0:
                volumes.append(float(vol))
            if high is not None and low is not None and close is not None and float(close) > 0:
                adr_pct = (float(high) - float(low)) / float(close) * 100.0
                adr_pcts.append(adr_pct)

        avg_vol = sum(volumes) / len(volumes) if volumes else None
        avg_adr = sum(adr_pcts) / len(adr_pcts) if adr_pcts else None

        stats[symbol] = SymbolMarketStats(
            symbol=symbol,
            avg_volume=avg_vol,
            avg_adr_pct=avg_adr,
            bar_count=len(recs),
        )
    return stats


# ---------------------------------------------------------------------------
# Rolling PF helper
# ---------------------------------------------------------------------------

@dataclass
class SymbolPFStats:
    symbol: str
    closed_count: int = 0
    profit_factor: float | None = None   # None = no qualifying trades


def compute_rolling_pf(
    closed_trades: list[dict[str, Any]],
    min_trades: int = 5,
) -> dict[str, SymbolPFStats]:
    """Compute per-symbol rolling profit factor from closed trades.

    Args:
        closed_trades: list of trade dicts from pnl_state
        min_trades:    minimum closed trades required before gate activates

    Returns:
        dict of symbol → SymbolPFStats
    """
    by_symbol: dict[str, list[float]] = {}
    for t in closed_trades:
        sym = t.get("symbol") or ""
        pnl = t.get("pnl")
        if sym and pnl is not None:
            by_symbol.setdefault(sym, []).append(float(pnl))

    result: dict[str, SymbolPFStats] = {}
    for sym, pnls in by_symbol.items():
        if len(pnls) < min_trades:
            result[sym] = SymbolPFStats(symbol=sym, closed_count=len(pnls), profit_factor=None)
            continue
        wins = sum(p for p in pnls if p > 0)
        losses = abs(sum(p for p in pnls if p < 0))
        pf = wins / losses if losses > 0 else (999.0 if wins > 0 else 0.0)
        result[sym] = SymbolPFStats(symbol=sym, closed_count=len(pnls), profit_factor=round(pf, 3))

    return result


# ---------------------------------------------------------------------------
# Filter result
# ---------------------------------------------------------------------------

@dataclass
class EntryFilterResult:
    passed: list[Any] = field(default_factory=list)     # DecisionRecord
    blocked: list[tuple[str, str]] = field(default_factory=list)  # (symbol, reason)
    stats: dict[str, Any] = field(default_factory=dict) # diagnostics


# ---------------------------------------------------------------------------
# EntryFilterEngine
# ---------------------------------------------------------------------------

class EntryFilterEngine:
    """Apply volume, ADR, and rolling PF entry filters to BUY decisions.

    Usage::

        engine = EntryFilterEngine(config)
        result = engine.filter(
            decisions=actionable_buys,
            records_by_symbol=records_by_symbol,
            closed_trades=tracker.state.trades,
            etf_symbols=ETF_SYMBOLS,
        )
        actionable = result.passed
        blocked_entry = result.blocked  # [(symbol, reason), ...]
    """

    def __init__(self, config: EntryFilterConfig | None = None) -> None:
        self.config = config or EntryFilterConfig.from_env()

    def filter(
        self,
        decisions: list[Any],          # list[DecisionRecord] — only BUY pass-through
        records_by_symbol: dict[str, list[Any]],
        closed_trades: list[dict[str, Any]],
        etf_symbols: set[str] | None = None,
    ) -> EntryFilterResult:
        """Filter buy decisions through entry quality gates.

        Non-buy decisions are always passed through unchanged.
        """
        cfg = self.config
        etf_symbols = etf_symbols or set()

        if cfg.disabled:
            logger.info("entry_filter disabled — skipping all gates")
            return EntryFilterResult(passed=list(decisions), blocked=[])

        # Pre-compute stats once
        market_stats = compute_market_stats(records_by_symbol)
        only_closed = [t for t in closed_trades if t.get("status") == "closed"]
        pf_stats = compute_rolling_pf(only_closed, min_trades=cfg.min_trades_for_gate)

        passed: list[Any] = []
        blocked: list[tuple[str, str]] = []
        diag: dict[str, Any] = {
            "volume_blocked": [],
            "adr_blocked": [],
            "rolling_pf_blocked": [],
        }

        for decision in decisions:
            action = getattr(decision, "action", "")
            symbol = getattr(decision, "symbol", "")

            # Non-buy decisions: always pass
            if action != "buy":
                passed.append(decision)
                continue

            is_etf = symbol in etf_symbols
            deny_reason: str | None = None

            # --- Gate 1: Volume (stocks only) ---
            if not is_etf and deny_reason is None:
                ms = market_stats.get(symbol)
                if ms is not None and ms.avg_volume is not None:
                    if ms.avg_volume < cfg.min_volume:
                        deny_reason = (
                            f"low_volume: avg={ms.avg_volume:,.0f} < "
                            f"min={cfg.min_volume:,.0f} shares/day"
                        )
                        diag["volume_blocked"].append(symbol)
                        logger.info(
                            "entry_filter_volume_block symbol=%s avg_volume=%.0f threshold=%.0f",
                            symbol, ms.avg_volume, cfg.min_volume,
                        )

            # --- Gate 2: ADR (stocks only) ---
            if not is_etf and deny_reason is None:
                ms = market_stats.get(symbol)
                if ms is not None and ms.avg_adr_pct is not None:
                    if ms.avg_adr_pct < cfg.min_adr_pct:
                        deny_reason = (
                            f"low_adr: avg_range={ms.avg_adr_pct:.2f}% < "
                            f"min={cfg.min_adr_pct:.2f}%"
                        )
                        diag["adr_blocked"].append(symbol)
                        logger.info(
                            "entry_filter_adr_block symbol=%s avg_adr_pct=%.2f threshold=%.2f",
                            symbol, ms.avg_adr_pct, cfg.min_adr_pct,
                        )

            # --- Gate 3: Rolling PF gate (all asset classes) ---
            if deny_reason is None:
                pf = pf_stats.get(symbol)
                if (
                    pf is not None
                    and pf.profit_factor is not None
                    and pf.profit_factor < cfg.rolling_pf_gate
                ):
                    deny_reason = (
                        f"rolling_pf_gate: symbol_pf={pf.profit_factor:.3f} "
                        f"(n={pf.closed_count}) < threshold={cfg.rolling_pf_gate:.2f}"
                    )
                    diag["rolling_pf_blocked"].append(symbol)
                    logger.info(
                        "entry_filter_pf_block symbol=%s pf=%.3f n=%d threshold=%.2f",
                        symbol, pf.profit_factor, pf.closed_count, cfg.rolling_pf_gate,
                    )

            # --- Gate 4: F6 stock-reduced mode (stricter PF threshold for individual stocks) ---
            if deny_reason is None and cfg.stock_reduced_mode and not is_etf:
                pf = pf_stats.get(symbol)
                if pf is not None and pf.closed_count >= cfg.stock_reduced_min_trades:
                    effective_pf = pf.profit_factor if pf.profit_factor is not None else 0.0
                    if effective_pf < cfg.stock_reduced_pf_gate:
                        deny_reason = (
                            f"stock_reduced_mode: symbol_pf={effective_pf:.3f} "
                            f"(n={pf.closed_count}) < stock_threshold={cfg.stock_reduced_pf_gate:.2f}"
                        )
                        diag.setdefault("stock_reduced_blocked", []).append(symbol)
                        logger.info(
                            "entry_filter_stock_reduced_block symbol=%s pf=%.3f n=%d threshold=%.2f",
                            symbol, effective_pf, pf.closed_count, cfg.stock_reduced_pf_gate,
                        )

            if deny_reason:
                blocked.append((symbol, deny_reason))
            else:
                passed.append(decision)

        if blocked:
            logger.info(
                "entry_filter_summary passed=%d blocked=%d "
                "(volume=%d adr=%d pf=%d)",
                len(passed),
                len(blocked),
                len(diag["volume_blocked"]),
                len(diag["adr_blocked"]),
                len(diag["rolling_pf_blocked"]),
            )

        return EntryFilterResult(passed=passed, blocked=blocked, stats=diag)
