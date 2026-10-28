"""Dip-buy / mean-reversion strategy (R14, 2026-08-25) -- SHADOW MODE ONLY.

Background
----------
2026-08-25, main session: during the 2026-08-24 semiconductor sell-off
(circuit breaker went `degraded`/`block_buys` on 8 consecutive losing
trades), the user asked whether a falling market is structurally a buying
opportunity the system currently ignores, and whether a dip-buy strategy
could run alongside the existing `breakout_momentum_v1` without conflict.

R14 Phase 1 (docs/r14_dip_buy_meanreversion_phase1_20260825/README.md)
tested this historically with a throwaway backtest script
(scripts/r14_dip_buy_meanreversion_phase1.py) and returned a GO verdict:
over the identical 2-year window/cost-model/exit-rules used for
breakout_momentum_v1's own R13-C evidence, this mirror-image entry rule
showed comparable-or-better PF, and specifically profited in the exact
chop-regime window (2025-11 to 2026-03) where R13-C's rolling walk-forward
independently confirmed breakout_momentum_v1 has a structural weakness
(PF=0.646 there vs PF=1.170 for this dip-buy rule).

This module is this strategy's PRODUCTION implementation, but wired into
paper_demo.py in SHADOW MODE ONLY (see paper_demo.py's Plan B/C/D/E-style
shadow diagnostics block): it generates candidate signals and logs them to
data/dip_buy_meanreversion_shadow_log.jsonl for forward accumulation, but
those signals are NEVER passed into DecisionEngine/EntryFilterEngine/
PortfolioAllocator and NEVER result in an order. This exactly follows the
same shadow->paper_ab->active promotion path already used for Plan B
(volatility_gate), Plan C (distance_from_high), sector_shock_hold, and the
JP overnight-spillover strategy -- accumulate real forward evidence before
any capital is put at risk.

WHY SHADOW-ONLY (not wired to orders) even though Phase 1 was GO
-------------------------------------------------------------------
Two portfolio-level risks were identified in the Phase 1 review that are
NOT resolved by this module and require a separate design decision before
live wiring:
  1. entry_filter.py's rolling-PF gate (Gate 3) is PER-SYMBOL, not
     per-strategy. A symbol breakout_momentum_v1 just stopped out of will
     have a depressed rolling PF and may block this strategy's entry into
     the SAME symbol shortly after, even though the entry condition here
     is the mirror-opposite signal. Needs an explicit decision: should
     Gate 3 become strategy-scoped, or should dip-buy simply accept being
     blocked by momentum's own recent losses on a symbol?
  2. Circuit breaker / correlation cluster cap / PortfolioAllocator ETF-
     stock band are all portfolio-level shared pools -- a real simultaneous
     run needs an explicit capital-allocation split (env/sub-ledger style,
     matching the separation already planned for the IBKR broker migration
     and the JP semiconductor expansion tracks) rather than assuming both
     strategies draw from the same uncapped pot.

Both are flagged, neither is decided yet -- shadow accumulation lets real
forward data inform that design work in parallel, same pattern as every
other Plan B-E shadow diagnostic.

Signal logic
------------
Direct mirror image of BreakoutMomentumStrategy's own condition:
breakout buys when trailing N-day momentum >= +min_momentum AND
PriceMomentumFeature classifies trend=="bullish"; this fires when trailing
N-day momentum <= -min_momentum_drop AND trend=="bearish" (the SAME
feature's own bearish classification, unchanged -- no new indicator).
Deliberately the least-tunable rule shape possible (default threshold
magnitude matches breakout_momentum_v1's own default 0.05), consistent
with R13-C's repeated caution against untested parameter tuning.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stock_swing.feature_engine.base_feature import FeatureResult
from stock_swing.strategy_engine.base_strategy import BaseStrategy, CandidateSignal

logger = logging.getLogger(__name__)

DEFAULT_MIN_MOMENTUM_DROP = 0.05  # mirrors BreakoutMomentumStrategy's default min_momentum
DEFAULT_MIN_SIGNAL_STRENGTH = 0.40  # mirrors BreakoutMomentumStrategy's default

SHADOW_LOG_RELATIVE = Path("data/dip_buy_meanreversion_shadow_log.jsonl")


@dataclass
class DipBuySignalConfig:
    """Threshold configuration for the dip-buy mean-reversion shadow signal.

    Env overrides:
        DIP_BUY_MIN_MOMENTUM_DROP   min trailing-momentum drop magnitude to
                                     flag a dip-buy candidate (default 0.05,
                                     i.e. -5%)
        DIP_BUY_MIN_SIGNAL_STRENGTH floor for computed signal_strength
                                     (default 0.40)
        DIP_BUY_SHADOW_DISABLED     set "true" to skip evaluation entirely
    """

    min_momentum_drop: float = DEFAULT_MIN_MOMENTUM_DROP
    min_signal_strength: float = DEFAULT_MIN_SIGNAL_STRENGTH
    disabled: bool = False

    @classmethod
    def from_env(cls) -> "DipBuySignalConfig":
        return cls(
            min_momentum_drop=float(
                os.environ.get("DIP_BUY_MIN_MOMENTUM_DROP", DEFAULT_MIN_MOMENTUM_DROP)
            ),
            min_signal_strength=float(
                os.environ.get("DIP_BUY_MIN_SIGNAL_STRENGTH", DEFAULT_MIN_SIGNAL_STRENGTH)
            ),
            disabled=os.environ.get("DIP_BUY_SHADOW_DISABLED", "").lower()
            in ("1", "true", "yes"),
        )


class DipBuyMeanReversionStrategy(BaseStrategy):
    """Mirror image of BreakoutMomentumStrategy for SHADOW-MODE-ONLY use.

    strategy_id is suffixed `_shadow` so that, even if a future engineer
    accidentally wires this into the live signal list, it is immediately
    obvious in decision records / attribution reports that this is not an
    approved live strategy (see STRATEGY_SCOPE.md convention).
    """

    strategy_id = "dip_buy_meanreversion_v1_shadow"

    def __init__(self, config: DipBuySignalConfig | None = None):
        self.config = config or DipBuySignalConfig.from_env()

    def generate(self, features: list[FeatureResult]) -> list[CandidateSignal]:
        cfg = self.config
        if cfg.disabled:
            return []

        momentum_features = [
            f for f in features if f.feature_name == "price_momentum" and f.symbol
        ]

        signals: list[CandidateSignal] = []
        now = datetime.now(timezone.utc)
        BLOCKING_QUALITY_FLAGS = {"stale_data", "insufficient_bars", "insufficient_price_data"}

        for mf in momentum_features:
            symbol = mf.symbol
            quality_flags = set(mf.quality_flags or [])
            if quality_flags & BLOCKING_QUALITY_FLAGS:
                continue

            momentum = mf.values.get("momentum", 0.0)
            trend = mf.values.get("trend", "unknown")

            # Mirror image of breakout's `momentum >= min_momentum and trend == "bullish"`.
            if momentum <= -cfg.min_momentum_drop and trend == "bearish":
                magnitude = abs(momentum) - cfg.min_momentum_drop
                signal_strength = min(1.0, 0.40 + magnitude * 3.0)
                signal_strength = max(cfg.min_signal_strength, round(signal_strength, 4))
                signals.append(
                    CandidateSignal(
                        strategy_id=self.strategy_id,
                        symbol=symbol,
                        action="buy",
                        signal_strength=signal_strength,
                        generated_at=now,
                        time_horizon="1w",
                        confidence=signal_strength * 0.85,  # same conservative scaling as breakout
                        reasoning=(
                            f"[SHADOW-ONLY, R14] Mean-reversion dip candidate: "
                            f"{momentum * 100:.1f}% trailing momentum"
                        ),
                        feature_refs=[mf.feature_name],
                        metadata={
                            "momentum": momentum,
                            "trend": trend,
                            "bars_used": mf.values.get("bars_used"),
                            "latest_close": mf.values.get("latest_close"),
                            "atr": mf.values.get("atr"),
                            "quality_flags": list(quality_flags),
                        },
                    )
                )

        return signals


def log_shadow(
    signal: CandidateSignal,
    shadow_log_path: Path | str | None = None,
) -> None:
    """Log a dip-buy shadow signal without submitting any order.

    Mirrors the shadow-logging pattern used by overnight_spillover_shadow.py
    / volatility_gate.py: always emits an INFO line, and appends a
    structured JSON record to *shadow_log_path* when provided so results
    accumulate for a future review (following the same shadow-review cadence
    used elsewhere: an initial volume check after ~1-2 weeks, mid-review
    around 3-4 weeks before any promotion decision).
    """
    logger.info(
        "dip_buy_meanreversion SHADOW symbol=%s strength=%.3f momentum=%s | %s",
        signal.symbol,
        signal.signal_strength,
        (signal.metadata or {}).get("momentum"),
        signal.reasoning,
    )

    if shadow_log_path is None:
        return

    log_path = Path(shadow_log_path)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        record: dict[str, Any] = {
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "symbol": signal.symbol,
            "strategy_id": signal.strategy_id,
            "signal_strength": signal.signal_strength,
            "confidence": signal.confidence,
            "momentum": (signal.metadata or {}).get("momentum"),
            "trend": (signal.metadata or {}).get("trend"),
            "reasoning": signal.reasoning,
            "mode": "shadow",
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
    except OSError as exc:
        logger.warning(
            "dip_buy_meanreversion: failed to write shadow log to %s: %s", log_path, exc
        )
