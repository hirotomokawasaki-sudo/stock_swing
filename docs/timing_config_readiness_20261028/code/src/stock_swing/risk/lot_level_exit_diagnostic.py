"""Lot-level exit evaluation shadow diagnostic (2026-09-01).

Background
----------
``SimpleExitV2Strategy.generate()`` evaluates exit conditions once per
*symbol*, using a broker-reported qty-weighted average entry price and a
single symbol-level ``peak_price``. When a symbol has multiple open lots
(partial entries at different times/prices -- common since
``same_symbol_cooldown`` only blocks re-entry within a configurable window,
not permanently), an *older* lot that individually has a large unrealized
gain can be diluted into a blended average that never crosses the
trailing/breakeven activation thresholds, even though the symbol-level
``peak_price`` (dollar terms, aggregated as the max across lots -- see
``PnLTracker.get_open_position_context_by_symbol()``) still reflects the
older lot's true high.

Real incident this diagnostic was built to catch (2026-08-31, NOW,
identified 2026-09-01): a 15-share lot opened 2026-08-12 at $125.00 reached
peak_price=$148.44 (individually +18.75% peak return). The same day
(2026-08-31), a new 385-share lot was opened at $148.84. The blended
qty-weighted average entry price ($147.946) is dominated by the much larger
new lot, so the *aggregate* peak_return_pct collapses to +0.60% -- far below
the 8% trailing-stop activation threshold that the old lot alone had long
since cleared. If price pulls back from here, the old lot's trailing-stop
protection (which would normally trigger once price falls >=4% off its own
$148.44 peak) is invisible to ``generate()`` because the symbol-level view
never activates.

This is a *shadow-only, observability-only* diagnostic: it re-evaluates
exit conditions independently for each open lot using ``pnl_tracker``'s
per-trade-record ``peak_price`` / ``entry_price`` / ``entry_signal_strength``
/ ``entry_time`` (already tracked per lot; see
``PnLTracker.update_open_trade_peaks``) by calling the *same* threshold-
resolution and trailing/breakeven/stop-loss helper methods already exposed
on ``SimpleExitV2Strategy`` (no duplicated threshold logic, no change to
``simple_exit_v2_strategy.py``). It logs cases where the lot-level verdict
disagrees with the symbol-level verdict ``generate()`` actually used. It
never fires, blocks, tightens, or splits an exit -- see
``docs/console_improvement_tasks.md`` for the shadow -> paper_ab -> active
promotion pattern used by every other diagnostic in this codebase
(``sector_shock_hold.py``, ``news_shock_hold.py``, ``volatility_gate.py``,
``distance_from_high.py``).

Usage (called once per paper_demo run, after exit_signals are generated)
------------------------------------------------------------------------
::

    from stock_swing.risk.lot_level_exit_diagnostic import (
        LotLevelExitDiagnosticConfig,
        evaluate_lot_level_discrepancies,
        log_shadow,
    )

    config = LotLevelExitDiagnosticConfig.from_env()
    if config.is_enabled():
        discrepancies = evaluate_lot_level_discrepancies(
            open_trades=pnl_tracker.get_open_positions(),
            current_positions_full=current_positions_full,
            exit_strategy=exit_strat,             # same SimpleExitV2Strategy instance
            aggregate_exit_signals=exit_signals,  # what generate() actually returned
            atr_pct_map=atr_pct_map,
            universe_avg_atr_pct=universe_avg_atr_pct,
            config=config,
        )
        for result in discrepancies:
            log_shadow(result, shadow_log_path=Path("data/lot_level_exit_shadow_log.jsonl"))
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from stock_swing.strategy_engine.base_strategy import CandidateSignal
    from stock_swing.strategy_engine.simple_exit_v2_strategy import SimpleExitV2Strategy


DEFAULT_MIN_LOTS = 2


@dataclass
class LotLevelExitDiagnosticConfig:
    """Threshold configuration for the lot-level exit shadow diagnostic.

    Env overrides:
        LOT_LEVEL_EXIT_DIAGNOSTIC_DISABLED   set "true" to skip evaluation
        LOT_LEVEL_EXIT_DIAGNOSTIC_MIN_LOTS   minimum open lots for a symbol
                                              before it is evaluated
                                              (default 2 -- a single lot
                                              cannot be "diluted")
    """

    disabled: bool = False
    min_lots: int = DEFAULT_MIN_LOTS

    @classmethod
    def from_env(cls) -> "LotLevelExitDiagnosticConfig":
        return cls(
            disabled=os.environ.get("LOT_LEVEL_EXIT_DIAGNOSTIC_DISABLED", "").lower()
            in ("1", "true", "yes"),
            min_lots=int(
                os.environ.get("LOT_LEVEL_EXIT_DIAGNOSTIC_MIN_LOTS", DEFAULT_MIN_LOTS)
            ),
        )

    def is_enabled(self) -> bool:
        return not self.disabled


@dataclass
class LotExitVerdict:
    """Independent exit evaluation for a single open lot."""

    trade_id: str
    symbol: str
    qty: int
    entry_price: float
    peak_price: float
    entry_signal_strength: float | None
    hold_days: float | None
    return_pct: float
    peak_return_pct: float
    eff_stop_loss_pct: float
    eff_trailing_activation_pct: float
    would_exit: bool
    exit_trigger: str | None  # "trailing_stop" | "breakeven_stop" | "stop_loss" | "time_based" | None


@dataclass
class LotLevelDiscrepancy:
    """A symbol where the lot-level verdicts disagree with the aggregate
    (symbol-level) verdict that ``SimpleExitV2Strategy.generate()`` actually
    produced this run.
    """

    symbol: str
    aggregate_would_exit: bool
    aggregate_exit_trigger: str | None
    lot_verdicts: list[LotExitVerdict]
    discrepancy_type: str  # "aggregate_missed_lot_exit" | "aggregate_exit_lot_disagreement"
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def _evaluate_single_lot(
    symbol: str,
    lot: dict[str, Any],
    current_price: float,
    exit_strategy: "SimpleExitV2Strategy",
    atr_pct_map: dict[str, float] | None,
    universe_avg_atr_pct: float | None,
    now: datetime,
) -> LotExitVerdict:
    """Re-derive generate()'s per-position priority chain (trailing >
    breakeven > stop_loss > time_based) for a single lot, using the exact
    same threshold-resolution helper methods SimpleExitV2Strategy.generate()
    itself calls, so this diagnostic can never silently drift from the real
    exit logic it is comparing against.
    """
    entry_price = float(lot.get("entry_price") or 0)
    qty = int(float(lot.get("qty") or 0))
    entry_signal_strength = lot.get("entry_signal_strength")

    stored_peak = lot.get("peak_price")
    peak_price = float(stored_peak) if stored_peak is not None else entry_price
    # Safety floor: peak can never be reported below entry or the current price
    # (mirrors generate()'s "update peak if current price is higher" step).
    peak_price = max(peak_price, current_price, entry_price)

    return_pct = (current_price - entry_price) / entry_price if entry_price > 0 else 0.0
    peak_return_pct = (peak_price - entry_price) / entry_price if entry_price > 0 else 0.0

    hold_days: float | None = None
    entry_time_str = lot.get("entry_time")
    if entry_time_str:
        try:
            entry_dt = datetime.fromisoformat(str(entry_time_str).replace("Z", "+00:00"))
            hold_days = (now - entry_dt).days
        except (ValueError, TypeError):
            hold_days = None

    volatility_multiplier = 1.0
    if exit_strategy.volatility_adjusted_stop_enabled:
        volatility_multiplier = exit_strategy.compute_volatility_multiplier(
            symbol_atr_pct=(atr_pct_map or {}).get(symbol),
            universe_avg_atr_pct=universe_avg_atr_pct,
            min_multiplier=exit_strategy.volatility_multiplier_min,
            max_multiplier=exit_strategy.volatility_multiplier_max,
        )
    eff_stop_loss_pct, eff_trailing_activation_pct = exit_strategy._resolve_thresholds(
        entry_signal_strength, hold_days=hold_days, volatility_multiplier=volatility_multiplier,
    )

    trailing_active, _active_activation, active_trailing_stop_pct, _staged_level = (
        exit_strategy._resolve_trailing_rule(peak_return_pct, eff_trailing_activation_pct)
    )

    would_exit = False
    exit_trigger: str | None = None

    # 1. Trailing stop (highest priority once activated) -- mirrors generate().
    if trailing_active:
        trailing_stop_price = peak_price * (1 - active_trailing_stop_pct)
        if current_price <= trailing_stop_price:
            would_exit = True
            exit_trigger = "trailing_stop"
    else:
        # 2. Breakeven stop -- only reached when trailing is NOT active,
        # exactly like generate()'s elif chain. Once breakeven activates
        # (peak crossed the activation line) but the floor hasn't been
        # breached yet, the position holds WITHOUT falling through to the
        # stop_loss check below (same as generate()).
        be_activated, be_floor_pct, _be_staged_level = exit_strategy._resolve_breakeven_floor(
            peak_return_pct, exit_strategy.breakeven_activation_pct,
        )
        if be_activated:
            if return_pct <= be_floor_pct:
                would_exit = True
                exit_trigger = "breakeven_stop"
            # else: still in profit but above floor -> hold (no stop_loss fallthrough)
        elif return_pct <= eff_stop_loss_pct:
            # 3. Initial stop loss (only reached when breakeven never activated).
            eff_min_hold = exit_strategy._effective_min_hold_days(
                return_pct, eff_stop_loss_pct=eff_stop_loss_pct
            )
            suppressed = (
                exit_strategy.min_hold_days_enabled
                and hold_days is not None
                and hold_days < eff_min_hold
                and return_pct > exit_strategy.emergency_stop_bypass_pct
            )
            if not suppressed:
                would_exit = True
                exit_trigger = "stop_loss"

    # 4. Time-based exit -- independent of the branches above, same as generate().
    if not would_exit and hold_days is not None and hold_days >= exit_strategy.max_hold_days:
        would_exit = True
        exit_trigger = "time_based"

    return LotExitVerdict(
        trade_id=str(lot.get("trade_id") or ""),
        symbol=symbol,
        qty=qty,
        entry_price=entry_price,
        peak_price=peak_price,
        entry_signal_strength=entry_signal_strength,
        hold_days=hold_days,
        return_pct=round(return_pct, 4),
        peak_return_pct=round(peak_return_pct, 4),
        eff_stop_loss_pct=eff_stop_loss_pct,
        eff_trailing_activation_pct=eff_trailing_activation_pct,
        would_exit=would_exit,
        exit_trigger=exit_trigger,
    )


def evaluate_lot_level_discrepancies(
    *,
    open_trades: list[dict[str, Any]],
    current_positions_full: dict[str, dict[str, Any]],
    exit_strategy: "SimpleExitV2Strategy",
    aggregate_exit_signals: list["CandidateSignal"],
    atr_pct_map: dict[str, float] | None = None,
    universe_avg_atr_pct: float | None = None,
    config: LotLevelExitDiagnosticConfig | None = None,
    now: datetime | None = None,
) -> list[LotLevelDiscrepancy]:
    """Compare per-lot exit verdicts against the symbol-level verdict that
    ``SimpleExitV2Strategy.generate()`` actually produced this run.

    Only symbols with >= ``config.min_lots`` open lots are evaluated (a
    single-lot symbol cannot be diluted by definition). Returns only the
    symbols where a discrepancy was found -- consistent symbols are not
    included, to keep the shadow log focused on actionable observations.
    """
    cfg = config or LotLevelExitDiagnosticConfig.from_env()
    if not cfg.is_enabled():
        return []

    now_dt = now or datetime.now(timezone.utc)

    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for trade in open_trades:
        sym = str(trade.get("symbol") or "").upper()
        if sym:
            by_symbol.setdefault(sym, []).append(trade)

    aggregate_by_symbol: dict[str, "CandidateSignal"] = {
        str(getattr(sig, "symbol", "")).upper(): sig
        for sig in aggregate_exit_signals
        if getattr(sig, "action", None) == "sell"
    }

    results: list[LotLevelDiscrepancy] = []
    for symbol, lots in by_symbol.items():
        if len(lots) < cfg.min_lots:
            continue

        pos = current_positions_full.get(symbol)
        if not pos:
            continue
        try:
            current_price = float(pos.get("current_price") or 0)
        except (TypeError, ValueError):
            current_price = 0.0
        if current_price <= 0:
            continue

        lot_verdicts = [
            _evaluate_single_lot(
                symbol, lot, current_price, exit_strategy,
                atr_pct_map, universe_avg_atr_pct, now_dt,
            )
            for lot in lots
        ]

        aggregate_signal = aggregate_by_symbol.get(symbol)
        aggregate_would_exit = aggregate_signal is not None
        aggregate_exit_trigger = (
            (aggregate_signal.metadata or {}).get("exit_trigger")
            if aggregate_signal is not None
            else None
        )

        lot_would_exit_any = any(v.would_exit for v in lot_verdicts)
        lot_would_exit_all = all(v.would_exit for v in lot_verdicts)

        discrepancy_type: str | None = None
        if not aggregate_would_exit and lot_would_exit_any:
            discrepancy_type = "aggregate_missed_lot_exit"
        elif aggregate_would_exit and not lot_would_exit_all:
            discrepancy_type = "aggregate_exit_lot_disagreement"

        if discrepancy_type is not None:
            results.append(
                LotLevelDiscrepancy(
                    symbol=symbol,
                    aggregate_would_exit=aggregate_would_exit,
                    aggregate_exit_trigger=aggregate_exit_trigger,
                    lot_verdicts=lot_verdicts,
                    discrepancy_type=discrepancy_type,
                )
            )

    return results


def log_shadow(
    discrepancy: LotLevelDiscrepancy,
    shadow_log_path: Path | str | None = None,
) -> None:
    """Log a lot-level exit discrepancy (diagnostic only, never fires,
    blocks, or splits an exit).
    """
    logger.info(
        "lot_level_exit_diagnostic OBSERVATION symbol=%s type=%s "
        "aggregate_would_exit=%s aggregate_trigger=%s lots=%s",
        discrepancy.symbol,
        discrepancy.discrepancy_type,
        discrepancy.aggregate_would_exit,
        discrepancy.aggregate_exit_trigger,
        [
            {
                "trade_id": v.trade_id,
                "qty": v.qty,
                "would_exit": v.would_exit,
                "exit_trigger": v.exit_trigger,
                "return_pct": v.return_pct,
                "peak_return_pct": v.peak_return_pct,
            }
            for v in discrepancy.lot_verdicts
        ],
    )

    if shadow_log_path is None:
        return

    out_path = Path(shadow_log_path)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "symbol": discrepancy.symbol,
            "discrepancy_type": discrepancy.discrepancy_type,
            "aggregate_would_exit": discrepancy.aggregate_would_exit,
            "aggregate_exit_trigger": discrepancy.aggregate_exit_trigger,
            "lots": [
                {
                    "trade_id": v.trade_id,
                    "qty": v.qty,
                    "entry_price": round(v.entry_price, 4),
                    "peak_price": round(v.peak_price, 4),
                    "entry_signal_strength": v.entry_signal_strength,
                    "hold_days": v.hold_days,
                    "return_pct": v.return_pct,
                    "peak_return_pct": v.peak_return_pct,
                    "eff_stop_loss_pct": v.eff_stop_loss_pct,
                    "eff_trailing_activation_pct": v.eff_trailing_activation_pct,
                    "would_exit": v.would_exit,
                    "exit_trigger": v.exit_trigger,
                }
                for v in discrepancy.lot_verdicts
            ],
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with open(out_path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
    except OSError as exc:
        logger.warning(
            "lot_level_exit_diagnostic: failed to write log to %s: %s", out_path, exc
        )
