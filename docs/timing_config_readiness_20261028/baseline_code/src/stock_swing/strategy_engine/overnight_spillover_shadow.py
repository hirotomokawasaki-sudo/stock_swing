"""Overnight spillover shadow signal logger (JP semiconductor/AI expansion).

New module (2026-08-19, Phase 2.5 — see docs/jp_semiconductor_ai_expansion_plan.md
section "Phase 2.5: Shadow検証").

Background
----------
Phase 1 (docs/jp_semiconductor_ai_expansion_plan.md, section 7) established via
2-year historical data that Japanese semiconductor-equipment/material stocks
show a much stronger correlation between the prior US session's benchmark
return (SOXX) and the *next* JPX session's return than same-day correlation —
consistent with an overnight information-spillover effect (US market moves
overnight, JPX reacts the next morning).

This module is a **shadow-only, read-only signal logger**. It mirrors the
existing shadow-mode pattern used by `sector_shock_hold.py` and
`volatility_gate.py`: it computes what an overnight-spillover BUY signal
*would* have looked like each day and appends a structured JSON record for
later analysis, but it does NOT submit any order and does NOT require any
broker connection (only market data via yfinance, same as
scripts/analyze_jp_semiconductor_correlation.py).

CRITICAL: This module is entirely independent of the IBKR migration
(docs/broker_migration_ibkr_plan.md). It can — and should — start
accumulating forward-looking shadow data well before IBKR connectivity is
established, since Phase 1's historical backtest and this module's forward
shadow log measure the same hypothesis from two different angles (past vs.
future data), and forward validation before committing to Phase 3 (live
wiring) is exactly the kind of "observe before act" pattern this project's
other roadmap items (sector_shock_hold, volatility_gate) have followed.

Not wired into paper_demo.py or any execution path. Intended to be invoked
by a dedicated daily script/cron job (see
scripts/log_jp_overnight_spillover_shadow.py).
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Threshold for what counts as a "large" prior-session US benchmark move,
# consistent with the conditional gap analysis in Phase 1
# (scripts/analyze_jp_semiconductor_correlation.py: LARGE_MOVE_THRESHOLD_PCT).
DEFAULT_LARGE_MOVE_THRESHOLD_PCT = 2.0

# Tier weighting derived from Phase 1's spillover correlation ranking
# (docs/jp_semiconductor_ai_expansion_plan.md section 7-A). Higher tier ->
# stronger historical spillover correlation -> higher signal_strength weight
# when a large US move is observed. This is a placeholder calibration; see
# module docstring note on recalibrating once shadow data accumulates.
JP_CANDIDATE_TIERS: dict[str, int] = {
    "6857.T": 1,  # Advantest
    "8035.T": 1,  # Tokyo Electron
    "6146.T": 1,  # Disco
    "6920.T": 2,  # Lasertec
    "7735.T": 2,  # Screen Holdings
    "3436.T": 2,  # Sumco
    "4063.T": 2,  # Shin-Etsu Chemical
    "4062.T": 2,  # Ibiden
    "5803.T": 3,  # Fujikura
    "5801.T": 3,  # Furukawa Electric
    "6506.T": 3,  # Yaskawa Electric
}

TIER_WEIGHT = {1: 1.0, 2: 0.7, 3: 0.5}

SHADOW_LOG_RELATIVE = Path("data/jp_overnight_spillover_shadow_log.jsonl")


@dataclass
class OvernightSpilloverSignal:
    """Result of evaluating one JP candidate symbol against the prior US
    session's benchmark move.
    """

    symbol: str
    us_benchmark_symbol: str
    us_benchmark_return_pct: float
    would_signal: bool
    direction: str  # "up", "down", or "none"
    signal_strength: float
    reason: str
    tier: int | None = None
    mode: str = "shadow"
    # Populated once the JP symbol's *next* open is known (either same-day
    # if run after JPX open, or backfilled the following day). None means
    # "not yet observed" — a forward shadow log naturally has this gap
    # until the outcome is known.
    jp_open_gap_pct: float | None = None


def evaluate_overnight_spillover_signal(
    symbol: str,
    us_benchmark_symbol: str,
    us_benchmark_return_pct: float,
    *,
    threshold_pct: float = DEFAULT_LARGE_MOVE_THRESHOLD_PCT,
    jp_open_gap_pct: float | None = None,
) -> OvernightSpilloverSignal:
    """Evaluate whether a JP candidate would receive an overnight-spillover
    BUY signal, given the prior US benchmark session's return.

    This is a pure function (no I/O) so it is directly unit-testable; see
    tests/unit/test_overnight_spillover_shadow.py.

    Args:
        symbol: JP symbol (e.g. "8035.T").
        us_benchmark_symbol: Reference US benchmark (e.g. "SOXX").
        us_benchmark_return_pct: Prior US session's daily return, as a
            percentage (e.g. 2.5 for +2.5%).
        threshold_pct: Minimum |return| to count as a "large move" (default
            matches Phase 1's conditional gap analysis threshold).
        jp_open_gap_pct: Optional, if the actual JP overnight gap is already
            known (e.g. backfilling a prior day's shadow record).

    Returns:
        OvernightSpilloverSignal with would_signal=True when
        |us_benchmark_return_pct| >= threshold_pct.
    """
    tier = JP_CANDIDATE_TIERS.get(symbol)

    # NaN guard (2026-09-04 regression fix): a NaN benchmark return must never
    # count as a large move. Without this, `abs(nan) < threshold` evaluates
    # False and falls through to the would_signal=True branch -- on
    # 2026-09-04T00:20Z a half-formed yfinance row produced a NaN SOXX return
    # and all 11 JP candidates were logged as would_signal=True garbage.
    if us_benchmark_return_pct is None or math.isnan(us_benchmark_return_pct):
        return OvernightSpilloverSignal(
            symbol=symbol,
            us_benchmark_symbol=us_benchmark_symbol,
            us_benchmark_return_pct=0.0,
            would_signal=False,
            direction="none",
            signal_strength=0.0,
            reason="invalid_us_return: NaN/None benchmark return (data quality guard)",
            tier=tier,
            jp_open_gap_pct=jp_open_gap_pct,
        )

    abs_return = abs(us_benchmark_return_pct)

    if abs_return < threshold_pct:
        return OvernightSpilloverSignal(
            symbol=symbol,
            us_benchmark_symbol=us_benchmark_symbol,
            us_benchmark_return_pct=round(us_benchmark_return_pct, 4),
            would_signal=False,
            direction="none",
            signal_strength=0.0,
            reason=(
                f"below_threshold: |{us_benchmark_return_pct:.2f}%| < "
                f"{threshold_pct:.2f}%"
            ),
            tier=tier,
            jp_open_gap_pct=jp_open_gap_pct,
        )

    direction = "up" if us_benchmark_return_pct > 0 else "down"
    tier_weight = TIER_WEIGHT.get(tier, 0.3) if tier is not None else 0.3
    # signal_strength scales with move magnitude (capped contribution beyond
    # 2x threshold) and tier weight, clamped to [0, 1] — same clamp
    # philosophy as breakout_momentum_strategy's signal_strength.
    magnitude_component = min(abs_return / (threshold_pct * 2), 1.0)
    signal_strength = round(min(magnitude_component * tier_weight, 1.0), 4)

    return OvernightSpilloverSignal(
        symbol=symbol,
        us_benchmark_symbol=us_benchmark_symbol,
        us_benchmark_return_pct=round(us_benchmark_return_pct, 4),
        would_signal=True,
        direction=direction,
        signal_strength=signal_strength,
        reason=(
            f"large_move: {us_benchmark_symbol} {us_benchmark_return_pct:+.2f}% "
            f"(tier={tier if tier is not None else 'unranked'})"
        ),
        tier=tier,
        jp_open_gap_pct=jp_open_gap_pct,
    )


def log_shadow(
    result: OvernightSpilloverSignal,
    shadow_log_path: Path | str | None = None,
) -> None:
    """Log an overnight-spillover shadow signal without submitting any order.

    Mirrors volatility_gate.log_shadow() / sector_shock_hold's shadow
    logging pattern: always emits a human-readable INFO line, and appends a
    structured JSON record to *shadow_log_path* when provided so results
    accumulate across runs for Phase 2.5 forward-validation review.
    """
    logger.info(
        "overnight_spillover SHADOW symbol=%s would_signal=%s direction=%s "
        "strength=%s mode=%s | %s",
        result.symbol,
        result.would_signal,
        result.direction,
        f"{result.signal_strength:.3f}",
        result.mode,
        result.reason,
    )

    if shadow_log_path is None:
        return

    log_path = Path(shadow_log_path)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        record: dict[str, Any] = {
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "symbol": result.symbol,
            "us_benchmark_symbol": result.us_benchmark_symbol,
            "us_benchmark_return_pct": result.us_benchmark_return_pct,
            "would_signal": result.would_signal,
            "direction": result.direction,
            "signal_strength": result.signal_strength,
            "reason": result.reason,
            "tier": result.tier,
            "jp_open_gap_pct": result.jp_open_gap_pct,
            "mode": result.mode,
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
    except OSError as exc:
        logger.warning(
            "overnight_spillover: failed to write shadow log to %s: %s", log_path, exc
        )
