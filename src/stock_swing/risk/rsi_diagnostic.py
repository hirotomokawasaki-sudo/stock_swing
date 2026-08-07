"""Plan E (2026-08-08, R10 follow-up #2): Massive RSI overbought diagnostic
(observability-only).

Purpose
-------
`MassiveClient.fetch_sma()` / `fetch_rsi()` (src/stock_swing/sources/
massive_client.py) have been implemented since the Massive API migration
but have never been called anywhere in the pipeline. `PriceMomentumFeature`
instead computes its own simple ATR approximation (average True Range from
raw OHLC bars) for stop-price sizing, which is unrelated to RSI. No
component currently checks whether a BUY candidate is already
"overbought" by a standard RSI(14) reading -- a signal that would be
directly relevant to BreakoutMomentumStrategy, which fires purely on
5-day price momentum and could otherwise buy into an already-extended
move (a related but distinct failure mode from the NBIS post-drop-bounce
pattern Plan C targets).

Why observability-only (not wired into signal_strength/sizing/exit)
----------------------------------------------------------------------
Same rationale as Plan B/C/D: RSI(14) has never been validated against
this strategy's actual trade outcomes. Some of the strategy's best
winners may well have fired at high RSI (a strong breakout often *is*
overbought by definition). Wiring an untested threshold into
signal_strength or a hard block risks quietly cutting off good trades.
This module only fetches, classifies, and logs -- it never blocks or
resizes anything. See docs/console_improvement_tasks.md for the planned
review/promotion schedule (same shadow -> paper_ab -> active pattern as
Plan B/C/D).

Why fetch only on BUY decisions (not the full universe)
----------------------------------------------------------
Calling Massive's SMA/RSI endpoints for the full ~44-symbol universe on
every paper_demo run would roughly double Massive API call volume for
data that is only useful when a BUY is actually being considered. Mirrors
the existing Plan B/C/D pattern (Finnhub metric/news lookups also happen
only on BUY decisions) to keep this diagnostic's marginal cost low and
predictable.
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

DEFAULT_RSI_WINDOW = 14
DEFAULT_OVERBOUGHT_THRESHOLD = 75.0


@dataclass
class RsiDiagnosticConfig:
    """Threshold configuration for the RSI overbought diagnostic.

    Env overrides:
        RSI_DIAGNOSTIC_WINDOW               RSI window size (default 14)
        RSI_DIAGNOSTIC_OVERBOUGHT_THRESHOLD  RSI value at/above which a BUY
                                             is flagged overbought
                                             (default 75.0)
        RSI_DIAGNOSTIC_DISABLED             set "true" to skip evaluation
                                             entirely (default: not disabled)
    """

    window: int = DEFAULT_RSI_WINDOW
    overbought_threshold: float = DEFAULT_OVERBOUGHT_THRESHOLD
    disabled: bool = False

    @classmethod
    def from_env(cls) -> "RsiDiagnosticConfig":
        return cls(
            window=int(os.environ.get("RSI_DIAGNOSTIC_WINDOW", DEFAULT_RSI_WINDOW)),
            overbought_threshold=float(
                os.environ.get(
                    "RSI_DIAGNOSTIC_OVERBOUGHT_THRESHOLD",
                    DEFAULT_OVERBOUGHT_THRESHOLD,
                )
            ),
            disabled=os.environ.get("RSI_DIAGNOSTIC_DISABLED", "").lower()
            in ("1", "true", "yes"),
        )


@dataclass
class RsiDiagnosticResult:
    symbol: str
    is_overbought: bool
    rsi_value: float | None
    window: int
    reason: str
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def fetch_latest_rsi(
    symbol: str,
    massive_client: Any,
    window: int = DEFAULT_RSI_WINDOW,
) -> float | None:
    """Fetch the most recent RSI(window) value for *symbol* via Massive.

    Best-effort, never raises: any client/network error returns None so the
    caller (a shadow diagnostic) can log a "no_data" classification instead
    of failing the run. Mirrors finnhub_metric_lookup.py's
    "read best-effort, tolerate absence" contract.
    """
    try:
        rows = massive_client.fetch_rsi(symbol, window=window)
    except Exception as exc:
        logger.warning("rsi_diagnostic: fetch_rsi failed for %s: %s", symbol, exc)
        return None

    if not rows:
        return None

    # fetch_rsi() returns rows in the order the Massive SDK yields them
    # (ascending by timestamp per massive_client.fetch_sma/fetch_rsi
    # docstrings and observed behaviour); take the most recent one
    # defensively by max(timestamp) rather than assuming order.
    try:
        latest = max(rows, key=lambda r: r.get("timestamp") or datetime.min)
    except (TypeError, ValueError):
        latest = rows[-1]

    value = latest.get("value")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_rsi_overbought(
    symbol: str,
    rsi_value: float | None,
    config: RsiDiagnosticConfig | None = None,
) -> RsiDiagnosticResult:
    """Classify whether a BUY candidate's RSI reading is overbought
    (observability only -- never blocks or modifies a decision).

    Args:
        symbol: Stock symbol.
        rsi_value: Latest RSI(window) value (e.g. from fetch_latest_rsi()),
            or None if unavailable.
        config: RsiDiagnosticConfig (defaults to from_env()).

    Returns:
        RsiDiagnosticResult. `is_overbought` flags RSI >= overbought
        threshold; this is purely diagnostic (see module docstring).
    """
    cfg = config or RsiDiagnosticConfig.from_env()

    if cfg.disabled:
        return RsiDiagnosticResult(
            symbol=symbol,
            is_overbought=False,
            rsi_value=None,
            window=cfg.window,
            reason="disabled",
        )

    if rsi_value is None:
        return RsiDiagnosticResult(
            symbol=symbol,
            is_overbought=False,
            rsi_value=None,
            window=cfg.window,
            reason="no_data: RSI value unavailable",
        )

    is_overbought = rsi_value >= cfg.overbought_threshold
    reason = (
        f"overbought: RSI({cfg.window})={rsi_value:.1f} "
        f">= threshold={cfg.overbought_threshold:.1f}"
        if is_overbought
        else (
            f"not_flagged: RSI({cfg.window})={rsi_value:.1f} "
            f"< threshold={cfg.overbought_threshold:.1f}"
        )
    )

    return RsiDiagnosticResult(
        symbol=symbol,
        is_overbought=is_overbought,
        rsi_value=rsi_value,
        window=cfg.window,
        reason=reason,
    )


def log_shadow(
    result: RsiDiagnosticResult,
    shadow_log_path: Path | str | None = None,
) -> None:
    """Log an RSI-diagnostic shadow observation (diagnostic only, never
    blocks).

    Mirrors the shadow-log pattern used by volatility_gate.py,
    distance_from_high.py, and news_sentiment.py: always emits an INFO
    line when flagged, and appends a structured JSON record to
    *shadow_log_path* when provided so overbought BUYs accumulate for
    later review.
    """
    if result.is_overbought:
        logger.info(
            "rsi_diagnostic SHADOW symbol=%s OVERBOUGHT rsi=%s window=%s | %s",
            result.symbol,
            result.rsi_value,
            result.window,
            result.reason,
        )

    if shadow_log_path is None:
        return

    out_path = Path(shadow_log_path)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "symbol": result.symbol,
            "is_overbought": result.is_overbought,
            "rsi_value": result.rsi_value,
            "window": result.window,
            "reason": result.reason,
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with open(out_path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
    except OSError as exc:
        logger.warning(
            "rsi_diagnostic: failed to write shadow log to %s: %s", out_path, exc
        )
