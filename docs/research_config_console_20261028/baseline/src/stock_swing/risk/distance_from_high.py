"""Plan C (2026-08-07, NBIS incident follow-up): 52-week-high distance
diagnostic (observability-only).

Purpose
-------
BreakoutMomentumStrategy fires on 5-day price momentum alone ("strong
bullish momentum (X%) indicates breakout"). It does not distinguish a
genuine breakout to new highs from a sharp reflex bounce off a large prior
drawdown. NBIS (2026-08-04/05/06 BUYs at $221-226) fired repeatedly on
+12-31% five-day momentum while already down >25% from its 52-week high
($299.86, set 2026-06-22) after a sharp late-July drop -- exactly the
profile of a dead-cat bounce, not a fresh breakout.

This module computes a simple, independent "bounce-off-a-drop" diagnostic
from data the pipeline already fetches (Finnhub 52WeekHigh /
52WeekHighDate) and tags each BUY decision with it for shadow-mode logging
only. It never blocks anything and never feeds back into signal_strength,
sizing, or exit thresholds.

Why observability-only (not wired into the strategy) for now
--------------------------------------------------------------
signal_strength already drives sizing AND the exit-strategy conviction
tiers (see simple_exit_v2_strategy.py's HIGH/LOW threshold split). Folding
a 52-week-high-distance penalty directly into signal_strength would
silently change position sizing and stop-loss/trailing thresholds for
every symbol, including genuine breakouts near/at new highs where no such
penalty is warranted, without any paper-verified evidence that doing so
improves outcomes. Per the 2026-08-07 review, this starts as a pure
diagnostic (same pattern as entry_filter.get_small_sample_watchlist()) so
data accumulates before any strategy-level change is proposed. See
docs/console_improvement_tasks.md, "R9: NBIS incident follow-up", for the
planned review/promotion schedule.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# A BUY is flagged as a "post-drop bounce" candidate when BOTH:
#   - price is already this far below its 52-week high (negative pct), AND
#   - momentum (the 5-day return that triggered the breakout signal) is
#     at least this strong.
# Defaults chosen to match the NBIS incident profile (25%+ off high,
# double-digit 5-day bounce) without being so loose that ordinary
# breakouts near a recent local high get flagged.
DEFAULT_MIN_DISTANCE_FROM_HIGH_PCT = -20.0  # i.e. at least 20% below 52w high
DEFAULT_MIN_BOUNCE_MOMENTUM_PCT = 10.0      # i.e. at least +10% momentum


@dataclass
class DistanceFromHighConfig:
    """Threshold configuration for the 52-week-high distance diagnostic.

    Env overrides:
        DISTANCE_FROM_HIGH_MIN_PCT       max allowed distance below 52w high
                                         (negative %, default -20.0)
        DISTANCE_FROM_HIGH_MIN_MOMENTUM  min 5-day momentum %% to flag as a
                                         bounce candidate (default 10.0)
        DISTANCE_FROM_HIGH_DISABLED      set "true" to skip evaluation entirely
    """

    min_distance_from_high_pct: float = DEFAULT_MIN_DISTANCE_FROM_HIGH_PCT
    min_bounce_momentum_pct: float = DEFAULT_MIN_BOUNCE_MOMENTUM_PCT
    disabled: bool = False

    @classmethod
    def from_env(cls) -> "DistanceFromHighConfig":
        return cls(
            min_distance_from_high_pct=float(
                os.environ.get(
                    "DISTANCE_FROM_HIGH_MIN_PCT", DEFAULT_MIN_DISTANCE_FROM_HIGH_PCT
                )
            ),
            min_bounce_momentum_pct=float(
                os.environ.get(
                    "DISTANCE_FROM_HIGH_MIN_MOMENTUM", DEFAULT_MIN_BOUNCE_MOMENTUM_PCT
                )
            ),
            disabled=os.environ.get("DISTANCE_FROM_HIGH_DISABLED", "").lower()
            in ("1", "true", "yes"),
        )


@dataclass
class DistanceFromHighResult:
    symbol: str
    is_bounce_candidate: bool
    distance_from_high_pct: float | None  # negative = below high
    momentum_pct: float | None
    week52_high: float | None
    week52_high_date: str | None
    reason: str
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def compute_distance_from_high_pct(
    latest_close: float | None,
    week52_high: float | None,
) -> float | None:
    """Return (latest_close - 52w_high) / 52w_high * 100, or None if inputs invalid.

    Result is <= 0 for any price at or below its 52-week high (the normal
    case); a positive result would indicate a new 52-week high was just set
    (week52_high is stale relative to latest_close).
    """
    if latest_close is None or week52_high is None:
        return None
    try:
        close_f = float(latest_close)
        high_f = float(week52_high)
    except (TypeError, ValueError):
        return None
    if high_f <= 0:
        return None
    return round((close_f - high_f) / high_f * 100.0, 2)


def classify_bounce_candidate(
    symbol: str,
    latest_close: float | None,
    momentum_pct: float | None,
    metric_payload: dict[str, Any] | None,
    config: DistanceFromHighConfig | None = None,
) -> DistanceFromHighResult:
    """Flag a BUY candidate as a possible post-drop bounce (observability only).

    Args:
        symbol: Stock symbol.
        latest_close: Latest close price used by the momentum feature
            (e.g. PriceMomentumFeature's `latest_close` value).
        momentum_pct: The momentum value that triggered the breakout signal,
            as a percentage (e.g. 29.0 for +29%).
        metric_payload: Finnhub 'stock/metric' payload dict (as returned by
            finnhub_metric_lookup.load_latest_finnhub_metric), or None.
        config: DistanceFromHighConfig (defaults to from_env()).

    Returns:
        DistanceFromHighResult. This function never blocks or modifies a
        decision -- it is purely diagnostic (see module docstring).
    """
    cfg = config or DistanceFromHighConfig.from_env()

    if cfg.disabled:
        return DistanceFromHighResult(
            symbol=symbol,
            is_bounce_candidate=False,
            distance_from_high_pct=None,
            momentum_pct=momentum_pct,
            week52_high=None,
            week52_high_date=None,
            reason="disabled",
        )

    week52_high = None
    week52_high_date = None
    if metric_payload:
        week52_high = metric_payload.get("52WeekHigh")
        week52_high_date = metric_payload.get("52WeekHighDate")

    distance_pct = compute_distance_from_high_pct(latest_close, week52_high)

    if distance_pct is None:
        return DistanceFromHighResult(
            symbol=symbol,
            is_bounce_candidate=False,
            distance_from_high_pct=None,
            momentum_pct=momentum_pct,
            week52_high=week52_high,
            week52_high_date=week52_high_date,
            reason="no_data: missing latest_close or 52-week-high metric",
        )

    if momentum_pct is None:
        return DistanceFromHighResult(
            symbol=symbol,
            is_bounce_candidate=False,
            distance_from_high_pct=distance_pct,
            momentum_pct=None,
            week52_high=week52_high,
            week52_high_date=week52_high_date,
            reason="no_momentum: cannot evaluate bounce pattern without momentum",
        )

    is_bounce = (
        distance_pct <= cfg.min_distance_from_high_pct
        and momentum_pct >= cfg.min_bounce_momentum_pct
    )

    reason = (
        f"post_drop_bounce_candidate: {distance_pct:.1f}% below 52w-high "
        f"(<= {cfg.min_distance_from_high_pct:.1f}%) with {momentum_pct:.1f}% momentum "
        f"(>= {cfg.min_bounce_momentum_pct:.1f}%)"
        if is_bounce
        else (
            f"not_flagged: {distance_pct:.1f}% below 52w-high, "
            f"{momentum_pct:.1f}% momentum"
        )
    )

    return DistanceFromHighResult(
        symbol=symbol,
        is_bounce_candidate=is_bounce,
        distance_from_high_pct=distance_pct,
        momentum_pct=momentum_pct,
        week52_high=week52_high,
        week52_high_date=week52_high_date,
        reason=reason,
    )


def log_observation(
    result: DistanceFromHighResult,
    log_path: Path | str | None = None,
) -> None:
    """Log a distance-from-high observation (diagnostic only, never blocks).

    Mirrors the shadow-log pattern used by sector_shock_hold.py and
    volatility_gate.py: always emits an INFO line, and appends a structured
    JSON record to *log_path* when provided so bounce-candidate BUYs
    accumulate for later review.
    """
    if result.is_bounce_candidate:
        logger.info(
            "distance_from_high OBSERVATION symbol=%s BOUNCE_CANDIDATE "
            "distance=%.1f%% momentum=%.1f%% | %s",
            result.symbol,
            result.distance_from_high_pct,
            result.momentum_pct,
            result.reason,
        )

    if log_path is None:
        return

    out_path = Path(log_path)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "symbol": result.symbol,
            "is_bounce_candidate": result.is_bounce_candidate,
            "distance_from_high_pct": result.distance_from_high_pct,
            "momentum_pct": result.momentum_pct,
            "week52_high": result.week52_high,
            "week52_high_date": result.week52_high_date,
            "reason": result.reason,
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with open(out_path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
    except OSError as exc:
        logger.warning(
            "distance_from_high: failed to write log to %s: %s", out_path, exc
        )
