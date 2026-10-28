"""F7: Regime-Aware Exit — Sector Shock Recovery Hold (shadow/paper A-B only).

Purpose
-------
Detect when a stop-loss signal is triggered during a **broad sector drawdown**
(e.g. semiconductors: SMH, SOXX, SOX) and classify whether the symbol is
behaving in line with the sector (potential recovery candidate) or is
materially weaker (genuine stop-loss candidate).

IMPORTANT: This module is **shadow-only**.  It logs what would happen if the
hold logic were applied, but does NOT override live exit decisions.
To enable paper A/B behaviour, set SECTOR_SHOCK_HOLD_MODE=paper_ab in env.
Never enable SECTOR_SHOCK_HOLD_MODE=live without:
  1. emergency hard loss cap per position,
  2. recovery_hold_timeout guard,
  3. at least 20 paper A/B trades showing improvement.

Exit path taxonomy
------------------
hard_stop:
    Symbol is materially weaker than its benchmark sector, has a
    thesis-breaking event, or breaches portfolio risk limits.
    → exit immediately.

soft_stop:
    Loss/ATR/drawdown thresholds touched but the symbol is NOT
    materially underperforming its sector.
    → flag for monitoring; do not exit immediately.

sector_shock_hold:
    Broad sector selloff confirmed (SMH/SOXX/SOX below shock threshold)
    AND symbol is within acceptable relative-weakness range.
    → hold with recovery_hold_timeout clock; check every trading day.

recovery_hold_timeout:
    Symbol still held after max_hold_days (3 / 5 / 10 config windows)
    without confirmed recovery.
    → partial or full exit.

relative_weakness_exit:
    Symbol continues to underperform sector during recovery window.
    → exit.

partial_de_risk:
    Reduce position by 50% while maintaining exposure to potential upside.

Usage (shadow mode)
-------------------
from stock_swing.strategy_engine.sector_shock_hold import (
    SectorShockHoldConfig,
    SectorShockAnalyzer,
    ExitClassification,
)

config = SectorShockHoldConfig.from_env()
analyzer = SectorShockAnalyzer(config)
result = analyzer.classify(
    symbol="NVDA",
    current_return_pct=-0.085,
    symbol_1d_return_pct=-0.05,
    sector_1d_return_pcts={"SMH": -0.048, "SOXX": -0.051},
)
# result.classification -> "sector_shock_hold" | "hard_stop" | "soft_stop" | ...
# result.shadow_log contains structured reasoning for review
"""
from __future__ import annotations

import json
import logging
import math
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Benchmark symbols for semiconductor sector shock detection ──────────────
DEFAULT_SECTOR_BENCHMARKS = ["SMH", "SOXX", "QQQ", "SPY"]
SEMICONDUCTOR_BENCHMARKS  = ["SMH", "SOXX"]


# ── Config ───────────────────────────────────────────────────────────────────

@dataclass
class SectorShockHoldConfig:
    """Configuration for sector-shock recovery hold logic.

    Env overrides:
        SECTOR_SHOCK_HOLD_MODE          shadow | paper_ab | disabled  (default: shadow)
        SECTOR_SHOCK_BENCHMARK_SYMBOLS  comma-separated, default SMH,SOXX
        SECTOR_SHOCK_THRESHOLD_PCT      sector 1-day decline to trigger shock detection
                                        default -3.0 (i.e. -3%)
        SECTOR_SHOCK_MIN_BENCHMARKS     minimum benchmarks breaching the threshold
                                        default 2
        SECTOR_SHOCK_BREADTH_MIN        minimum fraction of benchmarks breaching
                                        the threshold, default 0.5
        SECTOR_SHOCK_REL_WEAKNESS_MAX   max relative weakness vs sector to allow hold
                                        default 2.0 (symbol can be 2x worse than sector)
        SECTOR_SHOCK_MAX_HOLD_DAYS_3    first review window in trading days (default 3)
        SECTOR_SHOCK_MAX_HOLD_DAYS_5    second review window (default 5)
        SECTOR_SHOCK_MAX_HOLD_DAYS_10   final timeout (default 10)
        SECTOR_SHOCK_HARD_LOSS_CAP_PCT  emergency hard stop below this return (default -15%)
    """

    mode: str = "shadow"                     # shadow | paper_ab | disabled
    benchmark_symbols: list[str] = field(default_factory=lambda: list(SEMICONDUCTOR_BENCHMARKS))
    sector_shock_threshold_pct: float = -3.0  # sector 1d return below this = shock
    # 2026-08-14 (Stop Loss role-purification redesign): rolling 3-day
    # cumulative sector return threshold, checked as an OR-condition alongside
    # the single-day threshold above. Root cause this fixes: a genuine
    # sector-wide shock (e.g. 2026-06-05 SMH -9.2%/SOXX -10.4%) can partially
    # bounce back the very next day (2026-06-08 SMH +5.0%/SOXX +5.9%) while
    # remaining deeply negative on a rolling 3-day basis (2026-06-08 SMH
    # return_3d=-6.2%/SOXX=-7.2%). Stop-loss decisions for individual
    # positions typically fire a few days after the initial shock (median
    # hold-to-stop is 4-6 days in this system), so a same-day-only check
    # systematically misses shocks whose worst single day has already
    # passed. This was the actual cause of sector_shock_shadow_count staying
    # at 0 for months despite real, identifiable sector shocks occurring in
    # the trade history (see docs/daily_logs/2026-08-14.md "Stop Loss 再設計").
    sector_shock_rolling_days: int = 3
    sector_shock_rolling_threshold_pct: float = -5.0  # rolling 3d return below this = shock
    sector_shock_min_benchmarks: int = 2
    sector_shock_breadth_min: float = 0.5
    relative_weakness_max: float = 2.0        # symbol can be at most 2x the sector decline
    max_hold_days_3: int = 3
    max_hold_days_5: int = 5
    max_hold_days_10: int = 10
    hard_loss_cap_pct: float = -15.0          # emergency stop regardless of sector

    @classmethod
    def from_env(cls) -> "SectorShockHoldConfig":
        benchmark_env = os.environ.get("SECTOR_SHOCK_BENCHMARK_SYMBOLS", "")
        benchmarks = (
            [s.strip().upper() for s in benchmark_env.split(",") if s.strip()]
            if benchmark_env
            else list(SEMICONDUCTOR_BENCHMARKS)
        )
        return cls(
            mode=os.environ.get("SECTOR_SHOCK_HOLD_MODE", "shadow").lower(),
            benchmark_symbols=benchmarks,
            sector_shock_threshold_pct=float(
                os.environ.get("SECTOR_SHOCK_THRESHOLD_PCT", -3.0)
            ),
            sector_shock_rolling_days=int(
                os.environ.get("SECTOR_SHOCK_ROLLING_DAYS", 3)
            ),
            sector_shock_rolling_threshold_pct=float(
                os.environ.get("SECTOR_SHOCK_ROLLING_THRESHOLD_PCT", -5.0)
            ),
            sector_shock_min_benchmarks=max(
                1, int(os.environ.get("SECTOR_SHOCK_MIN_BENCHMARKS", 2))
            ),
            sector_shock_breadth_min=min(
                1.0,
                max(0.0, float(os.environ.get("SECTOR_SHOCK_BREADTH_MIN", 0.5))),
            ),
            relative_weakness_max=float(
                os.environ.get("SECTOR_SHOCK_REL_WEAKNESS_MAX", 2.0)
            ),
            max_hold_days_3=int(os.environ.get("SECTOR_SHOCK_MAX_HOLD_DAYS_3", 3)),
            max_hold_days_5=int(os.environ.get("SECTOR_SHOCK_MAX_HOLD_DAYS_5", 5)),
            max_hold_days_10=int(os.environ.get("SECTOR_SHOCK_MAX_HOLD_DAYS_10", 10)),
            hard_loss_cap_pct=float(
                os.environ.get("SECTOR_SHOCK_HARD_LOSS_CAP_PCT", -15.0)
            ),
        )


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class ExitClassification:
    """Result of classifying an exit signal in the sector shock context."""

    symbol: str
    classification: str  # hard_stop | soft_stop | sector_shock_hold | recovery_hold_timeout
                         # | relative_weakness_exit | partial_de_risk
    confidence: str      # high | medium | low
    reasoning: list[str] = field(default_factory=list)
    shadow_log: dict[str, Any] = field(default_factory=dict)
    recommended_action: str = "exit"  # exit | hold | partial_exit | monitor


@dataclass
class SectorShockState:
    """Persisted hold state for an active sector_shock_hold trade."""

    symbol: str
    hold_started_at: str          # ISO8601
    hold_started_return_pct: float
    hold_started_sector_return_avg: float
    days_held: int = 0
    last_checked_at: str = ""
    last_symbol_return_pct: float = 0.0
    last_sector_return_avg: float = 0.0
    partial_de_risk_done: bool = False
    experiment_id: str = "sector_shock_hold_shadow"


# ── Core analyzer ─────────────────────────────────────────────────────────────

class SectorShockAnalyzer:
    """Classify exit signals as hard_stop, soft_stop, or sector_shock_hold.

    This analyzer is sector-aware: it uses intraday or 1-day returns of
    configured benchmark ETFs (SMH, SOXX, etc.) to determine whether a
    symbol's weakness is idiosyncratic or sector-wide.

    In shadow mode, decisions are logged but do NOT override the live exit.
    In paper_ab mode, the hold decision is returned to the caller which can
    implement it as a paper-only A/B experiment.
    """

    def __init__(self, config: SectorShockHoldConfig) -> None:
        self.config = config

    def is_enabled(self) -> bool:
        return self.config.mode in ("shadow", "paper_ab")

    def classify(
        self,
        symbol: str,
        current_return_pct: float,
        symbol_1d_return_pct: float | None,
        sector_1d_return_pcts: dict[str, float],
        sector_rolling_return_pcts: dict[str, float] | None = None,
        days_held: int = 0,
        is_thesis_broken: bool = False,
        exceeds_portfolio_risk_limit: bool = False,
    ) -> ExitClassification:
        """Classify an exit signal in the regime-aware framework.

        Args:
            symbol:                   Ticker symbol.
            current_return_pct:       Current cumulative return from entry (e.g. -0.085).
            symbol_1d_return_pct:     Symbol 1-day return today (e.g. -0.05).
            sector_1d_return_pcts:    Dict of benchmark → 1-day return for sector ETFs.
            sector_rolling_return_pcts: Dict of benchmark → rolling N-day cumulative
                                      return for sector ETFs (N = config.sector_shock_
                                      rolling_days, default 3d). Optional; when omitted
                                      or empty, only the single-day check (Rule 5) applies,
                                      preserving prior behavior. See sector_shock_rolling_
                                      threshold_pct docstring on SectorShockHoldConfig for
                                      why this was added (2026-08-14).
            days_held:                Trading days position has been open (for timeout check).
            is_thesis_broken:         True if a company-specific event invalidates the thesis.
            exceeds_portfolio_risk_limit: True if portfolio risk limit is exceeded.

        Returns:
            ExitClassification with classification and recommended_action.
        """
        cfg = self.config
        reasoning: list[str] = []
        shadow_log: dict[str, Any] = {
            "symbol": symbol,
            "current_return_pct": round(current_return_pct * 100, 2),
            "symbol_1d_return_pct": (
                round(symbol_1d_return_pct * 100, 2)
                if symbol_1d_return_pct is not None
                else None
            ),
            "sector_1d_return_pcts": {
                k: round(v * 100, 2) for k, v in sector_1d_return_pcts.items()
            },
            "days_held": days_held,
            "is_thesis_broken": is_thesis_broken,
            "exceeds_portfolio_risk_limit": exceeds_portfolio_risk_limit,
            "mode": cfg.mode,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }

        # ── Rule 1: Emergency hard loss cap (no hold allowed below this) ────
        if current_return_pct * 100 <= cfg.hard_loss_cap_pct:
            reasoning.append(
                f"hard_loss_cap: return={current_return_pct*100:.1f}% <= cap={cfg.hard_loss_cap_pct:.1f}%"
            )
            shadow_log["decision_reason"] = "hard_loss_cap"
            return ExitClassification(
                symbol=symbol,
                classification="hard_stop",
                confidence="high",
                reasoning=reasoning,
                shadow_log=shadow_log,
                recommended_action="exit",
            )

        # ── Rule 2: Thesis-breaking event → always hard stop ────────────────
        if is_thesis_broken:
            reasoning.append("thesis_broken: company-specific event invalidates hold")
            shadow_log["decision_reason"] = "thesis_broken"
            return ExitClassification(
                symbol=symbol,
                classification="hard_stop",
                confidence="high",
                reasoning=reasoning,
                shadow_log=shadow_log,
                recommended_action="exit",
            )

        # ── Rule 3: Portfolio risk limit exceeded → always hard stop ─────────
        if exceeds_portfolio_risk_limit:
            reasoning.append("portfolio_risk_limit: exceeds max open risk budget")
            shadow_log["decision_reason"] = "portfolio_risk_limit"
            return ExitClassification(
                symbol=symbol,
                classification="hard_stop",
                confidence="high",
                reasoning=reasoning,
                shadow_log=shadow_log,
                recommended_action="exit",
            )

        # ── Rule 4: Recovery hold timeout check ──────────────────────────────
        if days_held >= cfg.max_hold_days_10:
            reasoning.append(
                f"recovery_hold_timeout: days_held={days_held} >= max={cfg.max_hold_days_10}"
            )
            shadow_log["decision_reason"] = "recovery_hold_timeout_10d"
            return ExitClassification(
                symbol=symbol,
                classification="recovery_hold_timeout",
                confidence="high",
                reasoning=reasoning,
                shadow_log=shadow_log,
                recommended_action="exit",
            )

        # Missing symbol or sector returns cannot support a shock-recovery
        # exception.  Keep the baseline exit and make the data-quality failure
        # explicit rather than substituting signal_strength as a fake return.
        if symbol_1d_return_pct is None or not sector_1d_return_pcts:
            missing = []
            if symbol_1d_return_pct is None:
                missing.append("symbol_session_return")
            if not sector_1d_return_pcts:
                missing.append("sector_session_returns")
            reasoning.append(
                "insufficient_data: missing " + ",".join(missing) + "; baseline exit retained"
            )
            shadow_log["decision_reason"] = "insufficient_data"
            shadow_log["missing_inputs"] = missing
            return ExitClassification(
                symbol=symbol,
                classification="insufficient_data",
                confidence="low",
                reasoning=reasoning,
                shadow_log=shadow_log,
                recommended_action="exit",
            )

        # ── Rule 5: Detect sector-wide shock ─────────────────────────────────
        # Use ALL benchmarks passed in sector_1d_return_pcts.
        # (2026-07-28 fix): previously this filtered by cfg.benchmark_symbols (global [SMH, SOXX]),
        # which silently discarded per-symbol benchmarks like QQQ/SPY/SKYY even when the
        # caller passed them.  The filtering responsibility has moved to the caller:
        # get_symbol_sector_returns() pre-selects the correct per-symbol subset, so classify()
        # should trust what it receives.  cfg.benchmark_symbols is now only used as the
        # fallback in get_symbol_sector_returns() when a symbol is not in the registry.
        relevant_benchmarks = dict(sector_1d_return_pcts)
        sector_shock_detected = False
        avg_sector_return = 0.0
        if relevant_benchmarks:
            avg_sector_return = sum(relevant_benchmarks.values()) / len(relevant_benchmarks)
            shock_count_1d = sum(
                1
                for value in relevant_benchmarks.values()
                if value * 100 <= cfg.sector_shock_threshold_pct
            )
            required_count_1d = min(
                cfg.sector_shock_min_benchmarks,
                max(1, math.ceil(len(relevant_benchmarks) * cfg.sector_shock_breadth_min)),
            )
            shock_breadth_1d = shock_count_1d / len(relevant_benchmarks)
            sector_shock_detected = (
                shock_count_1d >= required_count_1d
                and shock_breadth_1d >= cfg.sector_shock_breadth_min
            )
            shadow_log["avg_sector_return_pct"] = round(avg_sector_return * 100, 2)
            shadow_log["sector_shock_count_1d"] = shock_count_1d
            shadow_log["sector_shock_breadth_1d"] = round(shock_breadth_1d, 3)
            shadow_log["sector_shock_detected_1d"] = sector_shock_detected

        # ── Rule 5b (2026-08-14): rolling N-day sector shock check ──────────
        # OR-combined with the single-day check above. A shock whose worst
        # single day has already passed (e.g. a sharp drop followed by a
        # partial next-day bounce) can still show a deeply negative rolling
        # cumulative return; relying on the single-day check alone
        # systematically misses this pattern, which is common because
        # stop_loss decisions for individual positions typically fire a few
        # days after the initial shock day, not on the shock day itself.
        avg_sector_rolling_return = 0.0
        rolling_shock_detected = False
        if sector_rolling_return_pcts:
            relevant_rolling = dict(sector_rolling_return_pcts)
            if relevant_rolling:
                avg_sector_rolling_return = sum(relevant_rolling.values()) / len(relevant_rolling)
                shock_count_rolling = sum(
                    1
                    for value in relevant_rolling.values()
                    if value * 100 <= cfg.sector_shock_rolling_threshold_pct
                )
                required_count_rolling = min(
                    cfg.sector_shock_min_benchmarks,
                    max(1, math.ceil(len(relevant_rolling) * cfg.sector_shock_breadth_min)),
                )
                shock_breadth_rolling = shock_count_rolling / len(relevant_rolling)
                rolling_shock_detected = (
                    shock_count_rolling >= required_count_rolling
                    and shock_breadth_rolling >= cfg.sector_shock_breadth_min
                )
                shadow_log["avg_sector_rolling_return_pct"] = round(avg_sector_rolling_return * 100, 2)
                shadow_log["sector_shock_count_rolling"] = shock_count_rolling
                shadow_log["sector_shock_breadth_rolling"] = round(
                    shock_breadth_rolling, 3
                )
                shadow_log["sector_shock_rolling_days"] = cfg.sector_shock_rolling_days
                shadow_log["sector_shock_detected_rolling"] = rolling_shock_detected

        if rolling_shock_detected and not sector_shock_detected:
            # Rolling check caught a shock the single-day check missed.
            # Use the rolling average as the effective sector return for the
            # relative-weakness comparison below (Rule 6), since it is the
            # measure that actually detected the shock in this case.
            sector_shock_detected = True
            avg_sector_return = avg_sector_rolling_return
            reasoning.append(
                f"sector_shock_detected via rolling {cfg.sector_shock_rolling_days}d "
                f"return={avg_sector_rolling_return*100:.1f}% "
                f"<= threshold={cfg.sector_shock_rolling_threshold_pct:.1f}% "
                f"(single-day check did not trigger)"
            )
        shadow_log["sector_shock_detected"] = sector_shock_detected

        # ── Rule 6: Relative weakness check ──────────────────────────────────
        if sector_shock_detected and avg_sector_return < 0:
            if symbol_1d_return_pct < 0 and avg_sector_return < 0:
                # Ratio: how much worse is symbol vs sector? 1.0 = same; 2.0 = twice as bad
                relative_weakness_ratio = symbol_1d_return_pct / avg_sector_return
                shadow_log["relative_weakness_ratio"] = round(relative_weakness_ratio, 3)
            else:
                relative_weakness_ratio = 0.0
                shadow_log["relative_weakness_ratio"] = 0.0

            if relative_weakness_ratio > cfg.relative_weakness_max:
                # Symbol is significantly worse than sector → still exit
                reasoning.append(
                    f"relative_weakness_exit: ratio={relative_weakness_ratio:.2f} "
                    f"> max={cfg.relative_weakness_max:.2f} "
                    f"(symbol_1d={symbol_1d_return_pct*100:.1f}% "
                    f"vs sector_avg={avg_sector_return*100:.1f}%)"
                )
                shadow_log["decision_reason"] = "relative_weakness_exit"
                return ExitClassification(
                    symbol=symbol,
                    classification="relative_weakness_exit",
                    confidence="medium",
                    reasoning=reasoning,
                    shadow_log=shadow_log,
                    recommended_action="exit",
                )
            else:
                # Sector-wide shock; symbol is not materially underperforming
                reasoning.append(
                    f"sector_shock_hold: sector_avg={avg_sector_return*100:.1f}% "
                    f"shock_threshold={cfg.sector_shock_threshold_pct:.1f}% "
                    f"relative_weakness_ratio={relative_weakness_ratio:.2f} "
                    f"<= max={cfg.relative_weakness_max:.2f}"
                )
                # Check partial de-risk at 5-day window
                recommended = "hold"
                if days_held >= cfg.max_hold_days_5:
                    recommended = "partial_exit"
                    reasoning.append(
                        f"partial_de_risk: days_held={days_held} >= 5d window"
                    )
                shadow_log["decision_reason"] = "sector_shock_hold"
                return ExitClassification(
                    symbol=symbol,
                    classification="sector_shock_hold",
                    confidence="medium",
                    reasoning=reasoning,
                    shadow_log=shadow_log,
                    recommended_action=recommended,
                )
        elif not sector_shock_detected and sector_1d_return_pcts:
            # No sector shock; treat as soft_stop (monitor, don't exit immediately)
            reasoning.append(
                f"soft_stop: no_sector_shock avg_sector={avg_sector_return*100:.1f}% "
                f"symbol={symbol_1d_return_pct*100:.1f}%"
            )
            shadow_log["decision_reason"] = "soft_stop"
            return ExitClassification(
                symbol=symbol,
                classification="soft_stop",
                confidence="low",
                reasoning=reasoning,
                shadow_log=shadow_log,
                recommended_action="monitor",
            )
        # The missing-data path is handled before shock detection. This branch
        # is unreachable for valid finite inputs but remains fail-closed.
        reasoning.append("insufficient_data: unclassifiable regime; baseline exit retained")
        shadow_log["decision_reason"] = "insufficient_data"
        return ExitClassification(
            symbol=symbol,
            classification="insufficient_data",
            confidence="low",
            reasoning=reasoning,
            shadow_log=shadow_log,
            recommended_action="exit",
        )

    def log_shadow(
        self,
        result: ExitClassification,
        shadow_log_path: Path | str | None = None,
    ) -> None:
        """Log shadow decision for later review without overriding live exit.

        Writes a structured JSON line to *shadow_log_path* (if provided) so
        that sector_shock_hold events accumulate across runs for A/B
        activation tracking.  Also emits a human-readable INFO log line.

        Args:
            result:           Classification result from classify().
            shadow_log_path:  Path to the .jsonl file to append to.
                              When None, only the INFO log line is emitted
                              (legacy behaviour).
        """
        # ── Human-readable log line (always) ────────────────────────────────
        logger.info(
            "sector_shock_hold SHADOW symbol=%s classification=%s action=%s "
            "return=%.1f%% | %s",
            result.symbol,
            result.classification,
            result.recommended_action,
            result.shadow_log.get("current_return_pct", 0),
            "; ".join(result.reasoning),
        )

        # ── Persistent JSONL record (when path is provided) ──────────────────
        if shadow_log_path is None:
            return

        log_path = Path(shadow_log_path)
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "logged_at": datetime.now(timezone.utc).isoformat(),
                "symbol": result.symbol,
                "classification": result.classification,
                "recommended_action": result.recommended_action,
                "confidence": result.confidence,
                "reasoning": result.reasoning,
                **result.shadow_log,
            }
            line = json.dumps(record, ensure_ascii=False) + "\n"
            # Atomic append: write to temp file then rename is not possible for
            # append-only logs; use direct append with fsync for safety.
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
                os.fsync(fh.fileno())
        except Exception as exc:
            logger.warning(
                "sector_shock_hold: failed to write shadow log to %s: %s",
                log_path, exc,
            )


def get_symbol_sector_returns(
    symbol: str,
    all_benchmark_returns: dict[str, float],
    symbol_registry: dict[str, dict],
    fallback_benchmarks: list[str] | None = None,
) -> dict[str, float]:
    """Return the per-symbol subset of benchmark returns for sector_shock classification.

    Uses benchmark_symbols from symbol_registry.yaml for the given symbol.
    Falls back to fallback_benchmarks (usually SectorShockHoldConfig.benchmark_symbols)
    when the symbol is not in the registry or has no benchmark_symbols defined.

    This function was introduced (2026-07-28) to fix a bug where paper_demo.py
    used the global [SMH, SOXX] benchmark for ALL symbols, including non-semiconductor
    stocks like ADBE, AMZN, PLTR, META, HPQ whose correct benchmarks are QQQ/SPY/SKYY.
    The root cause was that symbol_registry.yaml had correct per-symbol data but
    paper_demo.py never read it for sector_shock.

    Args:
        symbol:               Trading symbol (e.g. "ADBE").
        all_benchmark_returns: Dict of all available benchmark returns keyed by symbol
                              (e.g. {"SMH": -0.03, "QQQ": -0.025, "SPY": -0.02}).
        symbol_registry:      Loaded symbol_registry.yaml as dict[SYMBOL, info_dict].
        fallback_benchmarks:  Benchmark list to use when symbol is not in registry.
                              Defaults to ["SMH", "SOXX"] if None.

    Returns:
        Dict of {benchmark_symbol: daily_return} for the symbol's sector.
    """
    fb = fallback_benchmarks if fallback_benchmarks is not None else list(SEMICONDUCTOR_BENCHMARKS)
    reg_info = symbol_registry.get(symbol) or {}
    bm_list: list[str] = reg_info.get("benchmark_symbols") or fb
    return {bm: all_benchmark_returns[bm] for bm in bm_list if bm in all_benchmark_returns}
