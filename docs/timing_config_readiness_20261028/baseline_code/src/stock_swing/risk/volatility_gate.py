"""Plan B (2026-08-07, NBIS incident follow-up): volatility upper-bound gate.

Purpose
-------
The existing entry filter (entry_filter.py) has an ADR *lower* bound
(``min_adr_pct``) that excludes symbols that barely move, but no *upper*
bound: a symbol with extreme realized volatility can pass every existing
gate (volume, ADR floor, rolling PF) as long as its historical trades
happen to look fine. NBIS (3-month annualized return std ~130%, already
>25% below its 52-week high) is exactly such a case: three BUYs fired on
"strong bullish momentum" that was very plausibly noise/dead-cat-bounce on
an extreme-volatility name, and all three were stopped out together for
-$7,774 on 2026-08-06.

IMPORTANT: This module is **shadow-only** by default (mirrors the
sector_shock_hold.py rollout pattern). It logs what *would* have happened
if a volatility cap were enforced, but does NOT block any BUY while in
shadow mode. This is intentional: unlike Plan A's cooldown guard (which is
narrow and obviously safe), a volatility cap risks cutting off some of the
strategy's best winners too -- several of NBIS's own historical wins
(e.g. +$5,288 closed 2026-06-25) came from the same high-volatility
profile. The threshold must be calibrated against historical BUY signals
(win vs loss, by volatility bucket) before being enabled for real, per the
2026-08-07 review's explicit recommendation to run Plan B as a graded
shadow -> paper A/B rollout, not an immediate hard gate.

To promote past shadow, set VOLATILITY_GATE_MODE=paper_ab (still
non-blocking, but flags the decision as an explicit A/B candidate for a
strategy variant) or VOLATILITY_GATE_MODE=active (actually blocks BUYs --
requires the historical calibration + review sign-off described in
docs/console_improvement_tasks.md, "R9: NBIS incident follow-up").
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

# Default cap on 3-month annualized return std (Finnhub '3MonthADReturnStd',
# expressed as a percentage, e.g. 130.0 = 130%). Derived from a one-time scan
# of the current universe's most recent Finnhub metric snapshots (2026-08-07):
# distribution ranged from GOOGL ~38% to NBIS ~133%, with a fairly continuous
# spread rather than an obvious natural cutoff. 120.0 is set deliberately
# high (blocks only the single most extreme name, NBIS, at the time of
# writing) so that shadow-mode logging starts capturing real signal without
# guessing at an aggressive, unvalidated threshold. This value MUST be
# revisited once shadow data accumulates -- see docs/console_improvement_tasks.md.
DEFAULT_MAX_3M_RETURN_STD_PCT = 120.0


@dataclass
class VolatilityGateConfig:
    """Threshold configuration for the volatility upper-bound gate.

    Env overrides:
        VOLATILITY_GATE_MODE                shadow | paper_ab | active | disabled
                                            (default: shadow)
        VOLATILITY_GATE_MAX_3M_STD_PCT      max 3-month annualized return std %
                                            (default: 120.0)
    """

    mode: str = "shadow"
    max_3m_return_std_pct: float = DEFAULT_MAX_3M_RETURN_STD_PCT

    @classmethod
    def from_env(cls) -> "VolatilityGateConfig":
        return cls(
            mode=os.environ.get("VOLATILITY_GATE_MODE", "shadow").lower(),
            max_3m_return_std_pct=float(
                os.environ.get(
                    "VOLATILITY_GATE_MAX_3M_STD_PCT", DEFAULT_MAX_3M_RETURN_STD_PCT
                )
            ),
        )

    def is_enabled(self) -> bool:
        return self.mode in ("shadow", "paper_ab", "active")

    def would_block(self) -> bool:
        """Whether classify() results should actually be enforced as a block."""
        return self.mode == "active"


@dataclass
class VolatilityClassification:
    symbol: str
    would_block: bool
    reason: str
    return_std_3m_pct: float | None
    mode: str
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def classify_buy_volatility(
    symbol: str,
    metric_payload: dict[str, Any] | None,
    config: VolatilityGateConfig | None = None,
) -> VolatilityClassification:
    """Classify whether a BUY candidate's realized volatility exceeds the cap.

    Args:
        symbol: Stock symbol.
        metric_payload: Finnhub 'stock/metric' payload dict (as returned by
            finnhub_metric_lookup.load_latest_finnhub_metric), or None if
            unavailable.
        config: VolatilityGateConfig (defaults to from_env()).

    Returns:
        VolatilityClassification. `would_block` reflects the *rule outcome*
        regardless of mode -- callers must check config.would_block() (i.e.
        mode == "active") before actually using this to filter a decision.
        In shadow/paper_ab mode this is purely diagnostic.
    """
    cfg = config or VolatilityGateConfig.from_env()

    if metric_payload is None:
        return VolatilityClassification(
            symbol=symbol,
            would_block=False,
            reason="no_metric_data: cannot evaluate volatility, allowing by default",
            return_std_3m_pct=None,
            mode=cfg.mode,
        )

    std_3m = metric_payload.get("3MonthADReturnStd")
    if std_3m is None:
        return VolatilityClassification(
            symbol=symbol,
            would_block=False,
            reason="missing_3m_std: field absent from metric payload",
            return_std_3m_pct=None,
            mode=cfg.mode,
        )

    try:
        std_3m_f = float(std_3m)
    except (TypeError, ValueError):
        return VolatilityClassification(
            symbol=symbol,
            would_block=False,
            reason=f"invalid_3m_std: unparseable value {std_3m!r}",
            return_std_3m_pct=None,
            mode=cfg.mode,
        )

    if std_3m_f > cfg.max_3m_return_std_pct:
        return VolatilityClassification(
            symbol=symbol,
            would_block=True,
            reason=(
                f"volatility_gate: 3m_return_std={std_3m_f:.1f}% "
                f"> cap={cfg.max_3m_return_std_pct:.1f}%"
            ),
            return_std_3m_pct=std_3m_f,
            mode=cfg.mode,
        )

    return VolatilityClassification(
        symbol=symbol,
        would_block=False,
        reason=(
            f"within_cap: 3m_return_std={std_3m_f:.1f}% "
            f"<= cap={cfg.max_3m_return_std_pct:.1f}%"
        ),
        return_std_3m_pct=std_3m_f,
        mode=cfg.mode,
    )


def log_shadow(
    result: VolatilityClassification,
    shadow_log_path: Path | str | None = None,
) -> None:
    """Log a volatility-gate shadow decision without affecting live behaviour.

    Mirrors sector_shock_hold.SectorShockAnalyzer.log_shadow(): always emits
    a human-readable INFO line, and appends a structured JSON record to
    *shadow_log_path* when provided so results accumulate across runs for
    later threshold calibration / paper A/B review.
    """
    logger.info(
        "volatility_gate SHADOW symbol=%s would_block=%s std_3m=%s%% mode=%s | %s",
        result.symbol,
        result.would_block,
        f"{result.return_std_3m_pct:.1f}" if result.return_std_3m_pct is not None else "n/a",
        result.mode,
        result.reason,
    )

    if shadow_log_path is None:
        return

    log_path = Path(shadow_log_path)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "symbol": result.symbol,
            "would_block": result.would_block,
            "reason": result.reason,
            "return_std_3m_pct": result.return_std_3m_pct,
            "mode": result.mode,
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
    except OSError as exc:
        logger.warning(
            "volatility_gate: failed to write shadow log to %s: %s", log_path, exc
        )
