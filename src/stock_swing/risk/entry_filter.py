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
    # Per-symbol PF gate override: symbols in this list skip the rolling_pf_gate check.
    # Set via ENTRY_FILTER_PF_GATE_SKIP_SYMBOLS (comma-separated, e.g. "AMD,MDB").
    pf_gate_skip_symbols: list = field(default_factory=list)
    # 2026-08-19 (JP semiconductor expansion Phase 2): compliance/insider deny-list.
    # Symbols here are blocked from BUY submission ONLY (Gate 0, evaluated before
    # all other gates). Does NOT affect data collection, feature computation,
    # backtesting, or correlation research (see docs/jp_semiconductor_ai_expansion_plan.md
    # section 1 — "purchase is prohibited, but verification/analysis is OK").
    # Set via ENTRY_FILTER_PURCHASE_RESTRICTED_SYMBOLS (comma-separated).
    purchase_restricted_symbols: list = field(default_factory=list)

    @classmethod
    def from_env(cls) -> "EntryFilterConfig":
        raw_skip = os.environ.get("ENTRY_FILTER_PF_GATE_SKIP_SYMBOLS", "")
        skip_symbols = [
            s.strip().upper() for s in raw_skip.split(",") if s.strip()
        ]
        raw_restricted = os.environ.get("ENTRY_FILTER_PURCHASE_RESTRICTED_SYMBOLS", "")
        restricted_symbols = [
            s.strip().upper() for s in raw_restricted.split(",") if s.strip()
        ]
        return cls(
            min_volume=float(os.environ.get("ENTRY_FILTER_MIN_VOLUME", 500_000)),
            min_adr_pct=float(os.environ.get("ENTRY_FILTER_MIN_ADR_PCT", 1.0)),
            rolling_pf_gate=float(os.environ.get("ENTRY_FILTER_ROLLING_PF_GATE", 0.70)),
            min_trades_for_gate=int(os.environ.get("ENTRY_FILTER_MIN_TRADES_FOR_GATE", 5)),
            disabled=os.environ.get("ENTRY_FILTER_DISABLED", "").lower() in ("1", "true", "yes"),
            stock_reduced_mode=os.environ.get("ENTRY_FILTER_STOCK_REDUCED", "").lower() in ("1", "true", "yes"),
            stock_reduced_pf_gate=float(os.environ.get("ENTRY_FILTER_STOCK_REDUCED_PF_GATE", 1.0)),
            stock_reduced_min_trades=int(os.environ.get("ENTRY_FILTER_STOCK_REDUCED_MIN_TRADES", 5)),
            pf_gate_skip_symbols=skip_symbols,
            purchase_restricted_symbols=restricted_symbols,
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
    win_rate: float | None = None        # None = no closed trades at all


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
        n = len(pnls)
        wr = sum(1 for p in pnls if p > 0) / n if n > 0 else None
        if n < min_trades:
            result[sym] = SymbolPFStats(
                symbol=sym, closed_count=n, profit_factor=None, win_rate=wr
            )
            continue
        wins = sum(p for p in pnls if p > 0)
        losses = abs(sum(p for p in pnls if p < 0))
        pf = wins / losses if losses > 0 else (999.0 if wins > 0 else 0.0)
        result[sym] = SymbolPFStats(
            symbol=sym, closed_count=n, profit_factor=round(pf, 3), win_rate=wr
        )

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
            "purchase_restricted_blocked": [],
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

            # --- Gate 0: Purchase restriction (highest priority, e.g. insider) ---
            # 2026-08-19 (JP semiconductor expansion Phase 2): symbols on the
            # compliance deny-list are blocked from BUY regardless of any other
            # gate outcome. This is evaluated first and short-circuits Gates 1-4.
            # See docs/jp_semiconductor_ai_expansion_plan.md section 1.
            if symbol in cfg.purchase_restricted_symbols:
                deny_reason = f"purchase_restricted: {symbol} is on the compliance/insider deny-list"
                diag["purchase_restricted_blocked"].append(symbol)
                logger.info(
                    "entry_filter_purchase_restricted_block symbol=%s",
                    symbol,
                )

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
            # Symbols in pf_gate_skip_symbols bypass this check entirely.
            if deny_reason is None and symbol not in cfg.pf_gate_skip_symbols:
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
            elif deny_reason is None and symbol in cfg.pf_gate_skip_symbols:
                logger.info(
                    "entry_filter_pf_gate_skipped symbol=%s (pf_gate_skip_symbols override)",
                    symbol,
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
                "(purchase_restricted=%d volume=%d adr=%d pf=%d)",
                len(passed),
                len(blocked),
                len(diag["purchase_restricted_blocked"]),
                len(diag["volume_blocked"]),
                len(diag["adr_blocked"]),
                len(diag["rolling_pf_blocked"]),
            )

        return EntryFilterResult(passed=passed, blocked=blocked, stats=diag)


# ---------------------------------------------------------------------------
# Permanent block summary — independent of any run's BUY candidates
# ---------------------------------------------------------------------------

def get_permanent_block_summary(
    closed_trades: list[dict],
    config: EntryFilterConfig | None = None,
    etf_symbols: set[str] | None = None,
) -> list[dict]:
    """Compute which symbols are currently blocked by entry filters from PF history.

    Unlike EntryFilterEngine.filter(), this function does NOT need a list of
    BUY decisions.  It scans all closed trades, computes per-symbol PF, and
    returns every symbol that would be blocked if it appeared as a BUY candidate.

    Args:
        closed_trades: All closed trades from pnl_state.
        config:        EntryFilterConfig to use (defaults to from_env()).
        etf_symbols:   Set of ETF symbols (exempt from stock_reduced gate).

    Returns:
        List of dicts sorted by PF ascending::

            [
              {
                "symbol": "MDB",
                "n_trades": 6,
                "profit_factor": 0.0,
                "reason": "stock_reduced",
                "reason_detail": "PF=0.000 < 1.0 (n=6, min_n=5)",
              },
              ...
            ]
    """
    cfg = config or EntryFilterConfig.from_env()
    etf_syms = etf_symbols or set()

    only_closed = [t for t in closed_trades if t.get("status") == "closed"]

    # Compute PF with the lower min_trades (stock_reduced) so we capture all candidates
    effective_min = min(cfg.min_trades_for_gate, cfg.stock_reduced_min_trades)
    pf_stats = compute_rolling_pf(only_closed, min_trades=effective_min)

    result: list[dict] = []
    for sym, stats in pf_stats.items():
        if stats.profit_factor is None:
            continue  # not enough trades even for effective_min
        is_etf = sym in etf_syms
        pf = stats.profit_factor
        n = stats.closed_count
        reason = None
        reason_detail = None

        # Symbols in pf_gate_skip_symbols are never listed as blocked.
        if sym in cfg.pf_gate_skip_symbols:
            continue

        # rolling_pf_gate (applies to all symbols with enough trades)
        if n >= cfg.min_trades_for_gate and pf < cfg.rolling_pf_gate:
            reason = "rolling_pf_gate"
            reason_detail = (
                f"PF={pf:.3f} < {cfg.rolling_pf_gate:.2f} "
                f"(n={n}, min_n={cfg.min_trades_for_gate})"
            )

        # stock_reduced stricter gate (non-ETF only)
        if (
            cfg.stock_reduced_mode
            and not is_etf
            and n >= cfg.stock_reduced_min_trades
            and pf < cfg.stock_reduced_pf_gate
        ):
            if reason is None or pf < cfg.rolling_pf_gate:
                # stock_reduced is the binding constraint (or the only one)
                reason = "stock_reduced"
                reason_detail = (
                    f"PF={pf:.3f} < {cfg.stock_reduced_pf_gate:.2f} "
                    f"(n={n}, min_n={cfg.stock_reduced_min_trades})"
                )

        if reason:
            result.append({
                "symbol": sym,
                "n_trades": n,
                "profit_factor": round(pf, 3),
                "reason": reason,
                "reason_detail": reason_detail,
            })

    # Sort: worst PF first
    result.sort(key=lambda r: (r["reason"], r["profit_factor"]))
    return result


# ---------------------------------------------------------------------------
# Small-sample watchlist (observability only, 2026-08-05) — NOT an auto-block
# ---------------------------------------------------------------------------

def get_small_sample_watchlist(
    closed_trades: list[dict],
    config: EntryFilterConfig | None = None,
    etf_symbols: set[str] | None = None,
    min_trades: int = 2,
) -> list[dict]:
    """Surface non-ETF symbols with n < stock_reduced_min_trades whose net PnL
    is already sharply negative, so they are visible on the console even
    though the automatic stock_reduced gate cannot statistically justify
    blocking them yet (n=5 is the current gate threshold; see EntryFilterConfig).

    Motivation (2026-08-05 review, "현状の戦略で他に検証・検討が必要なこと"):
    a scan of closed trades found several stocks with catastrophic PnL on only
    2-4 trades (e.g. IBM n=3 pnl=-$8,513 WR=0%, ORCL n=3 pnl=-$8,306 WR=33%,
    PLTR n=2 pnl=-$6,712 WR=0%, CDNS n=2 pnl=-$5,940 WR=0%) that the
    stock_reduced gate (min_n=5) has not yet flagged and likely never will at
    this trade cadence. This function does NOT block anything -- it is
    read-only observability so an operator can decide whether to manually
    add a symbol to a deny-list, watch it, or wait for more data.

    Args:
        closed_trades: All closed trades from pnl_state.
        config:        EntryFilterConfig to use (defaults to from_env()).
        etf_symbols:   Set of ETF symbols (excluded -- this watchlist is for
                      individual stocks only, matching stock_reduced_mode's scope).
        min_trades:    Minimum closed trades required to appear on the
                      watchlist at all (default 2 -- a single trade is not
                      even weak evidence).

    Returns:
        List of dicts sorted by net_pnl ascending (worst first), for symbols
        with 2 <= n < stock_reduced_min_trades AND net_pnl < 0::

            [
              {
                "symbol": "IBM",
                "n_trades": 3,
                "net_pnl": -8513.13,
                "win_rate": 0.0,
                "note": "n=3 < min_n=5 for stock_reduced gate; not auto-blocked",
              },
              ...
            ]
    """
    cfg = config or EntryFilterConfig.from_env()
    etf_syms = etf_symbols or set()

    only_closed = [t for t in closed_trades if t.get("status") == "closed"]

    by_symbol: dict[str, list[float]] = {}
    for t in only_closed:
        sym = t.get("symbol") or ""
        pnl = t.get("pnl")
        if sym and pnl is not None and sym not in etf_syms:
            by_symbol.setdefault(sym, []).append(float(pnl))

    result: list[dict] = []
    for sym, pnls in by_symbol.items():
        n = len(pnls)
        if n < min_trades or n >= cfg.stock_reduced_min_trades:
            continue  # either too few to say anything, or already covered by the real gate
        if sym in cfg.pf_gate_skip_symbols:
            continue
        net_pnl = sum(pnls)
        if net_pnl >= 0:
            continue  # only surface symbols that are already net-negative
        wins = sum(1 for p in pnls if p > 0)
        result.append({
            "symbol": sym,
            "n_trades": n,
            "net_pnl": round(net_pnl, 2),
            "win_rate": round(wins / n, 3),
            "note": (
                f"n={n} < min_n={cfg.stock_reduced_min_trades} for stock_reduced gate; "
                f"not auto-blocked"
            ),
        })

    result.sort(key=lambda r: r["net_pnl"])
    return result
