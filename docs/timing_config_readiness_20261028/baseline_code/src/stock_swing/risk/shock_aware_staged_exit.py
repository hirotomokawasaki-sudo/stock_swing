"""Shadow-only staged-exit plans for broad shocks and unconfirmed soft stops.

The baseline sell signal remains authoritative.  This module records how a
treatment arm would reduce part of the position and require confirmation on a
later session; it never mutates or filters an executable signal.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from stock_swing.strategy_engine.sector_shock_hold import ExitClassification


@dataclass(frozen=True)
class ShockAwareStagedExitConfig:
    mode: str = "shadow"
    partial_fraction: float = 1.0 / 3.0
    confirmation_sessions: int = 1
    treatment_hard_cap_pct: float = -0.15

    @classmethod
    def from_env(cls) -> "ShockAwareStagedExitConfig":
        mode = os.environ.get("SHOCK_AWARE_STAGED_EXIT_MODE", "shadow").lower()
        try:
            partial_fraction = float(
                os.environ.get("SHOCK_AWARE_STAGED_EXIT_PARTIAL_FRACTION", 1.0 / 3.0)
            )
        except (TypeError, ValueError):
            partial_fraction = 1.0 / 3.0
        if not 0.0 < partial_fraction < 1.0:
            partial_fraction = 1.0 / 3.0
        try:
            confirmation_sessions = int(
                os.environ.get("SHOCK_AWARE_STAGED_EXIT_CONFIRMATION_SESSIONS", 1)
            )
        except (TypeError, ValueError):
            confirmation_sessions = 1
        confirmation_sessions = max(1, confirmation_sessions)
        try:
            treatment_hard_cap_pct = float(
                os.environ.get("SHOCK_AWARE_STAGED_EXIT_HARD_CAP_PCT", -0.15)
            )
        except (TypeError, ValueError):
            treatment_hard_cap_pct = -0.15
        if not math.isfinite(treatment_hard_cap_pct) or not -1.0 < treatment_hard_cap_pct < 0:
            treatment_hard_cap_pct = -0.15
        return cls(
            mode=mode,
            partial_fraction=partial_fraction,
            confirmation_sessions=confirmation_sessions,
            treatment_hard_cap_pct=treatment_hard_cap_pct,
        )

    def is_enabled(self) -> bool:
        return self.mode == "shadow"


@dataclass(frozen=True)
class ShockAwareStagedExitPlan:
    symbol: str
    classification: str
    exit_trigger: str
    baseline_exit_qty: int
    treatment_exit_qty: int
    treatment_hold_qty: int
    partial_fraction: float
    confirmation_sessions: int
    treatment_hard_cap_pct: float
    would_stage: bool
    reason: str
    current_return_pct: float | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class StagedExitCounterfactual:
    baseline_pnl: float
    treatment_pnl: float
    pnl_delta: float
    remainder_exit_session: str | None
    remainder_exit_price: float | None
    remainder_exit_reason: str
    sessions_observed: int
    mfe_pct_from_baseline_exit: float | None
    mae_pct_from_baseline_exit: float | None

    def to_dict(self) -> dict:
        return asdict(self)


def build_shock_aware_staged_exit_plan(
    *,
    symbol: str,
    exit_trigger: str,
    baseline_qty: int,
    classification: ExitClassification,
    current_return_pct: float | None,
    config: ShockAwareStagedExitConfig,
) -> ShockAwareStagedExitPlan:
    """Return a counterfactual plan while preserving the full baseline exit."""
    qty = max(int(baseline_qty or 0), 0)
    trigger = str(exit_trigger or "")
    is_initial_stop = trigger.lower().startswith("stop loss")
    current_return_valid = (
        current_return_pct is not None
        and math.isfinite(current_return_pct)
        and current_return_pct < 0
    )
    hard_cap_breached = (
        current_return_valid
        and current_return_pct <= config.treatment_hard_cap_pct
    )
    would_stage = (
        qty >= 2
        and is_initial_stop
        and current_return_valid
        and classification.classification in {"sector_shock_hold", "soft_stop"}
        and not hard_cap_breached
    )
    if would_stage:
        treatment_qty = min(max(math.ceil(qty * config.partial_fraction), 1), qty - 1)
        reason = (
            "broad_sector_shock_initial_stop_partial_de_risk"
            if classification.classification == "sector_shock_hold"
            else "unconfirmed_soft_stop_partial_de_risk"
        )
    else:
        treatment_qty = qty
        if qty < 2:
            reason = "quantity_too_small_for_partial_exit"
        elif not current_return_valid:
            reason = "invalid_current_return_requires_full_exit"
        elif hard_cap_breached:
            reason = "treatment_hard_cap_requires_full_exit"
        elif not is_initial_stop:
            reason = "not_initial_stop_loss"
        else:
            reason = f"classification_requires_full_exit:{classification.classification}"

    return ShockAwareStagedExitPlan(
        symbol=symbol,
        classification=classification.classification,
        exit_trigger=trigger,
        baseline_exit_qty=qty,
        treatment_exit_qty=treatment_qty,
        treatment_hold_qty=max(qty - treatment_qty, 0),
        partial_fraction=config.partial_fraction,
        confirmation_sessions=config.confirmation_sessions,
        treatment_hard_cap_pct=config.treatment_hard_cap_pct,
        would_stage=would_stage,
        reason=reason,
        current_return_pct=current_return_pct,
    )


def replay_staged_exit_counterfactual(
    *,
    plan: ShockAwareStagedExitPlan,
    average_entry_price: float,
    baseline_exit_price: float,
    future_session_closes: list[tuple[str, float]],
    max_sessions: int,
) -> StagedExitCounterfactual:
    """Replay only prices available up to each future session in chronological order."""
    qty = plan.baseline_exit_qty
    baseline_pnl = (baseline_exit_price - average_entry_price) * qty
    if not plan.would_stage or plan.treatment_hold_qty <= 0:
        return StagedExitCounterfactual(
            baseline_pnl=baseline_pnl,
            treatment_pnl=baseline_pnl,
            pnl_delta=0.0,
            remainder_exit_session=None,
            remainder_exit_price=None,
            remainder_exit_reason="baseline_full_exit",
            sessions_observed=0,
            mfe_pct_from_baseline_exit=None,
            mae_pct_from_baseline_exit=None,
        )

    usable_path: list[tuple[str, float]] = []
    for session, close in future_session_closes[:max(max_sessions, 0)]:
        try:
            parsed_close = float(close)
        except (TypeError, ValueError):
            continue
        if parsed_close > 0 and math.isfinite(parsed_close):
            usable_path.append((session, parsed_close))
    if not usable_path:
        return StagedExitCounterfactual(
            baseline_pnl=baseline_pnl,
            treatment_pnl=baseline_pnl,
            pnl_delta=0.0,
            remainder_exit_session=None,
            remainder_exit_price=None,
            remainder_exit_reason="missing_future_price_path",
            sessions_observed=0,
            mfe_pct_from_baseline_exit=None,
            mae_pct_from_baseline_exit=None,
        )

    remainder_session, remainder_price = usable_path[-1]
    remainder_reason = "horizon_exit"
    observed_prices: list[float] = []
    for offset, (session, close) in enumerate(usable_path, start=1):
        observed_prices.append(close)
        cumulative_return = close / average_entry_price - 1.0
        if cumulative_return <= plan.treatment_hard_cap_pct:
            remainder_session, remainder_price = session, close
            remainder_reason = "treatment_hard_cap"
            break
        if offset >= plan.confirmation_sessions and close <= baseline_exit_price:
            remainder_session, remainder_price = session, close
            remainder_reason = "failed_confirmation"
            break

    treatment_pnl = (
        (baseline_exit_price - average_entry_price) * plan.treatment_exit_qty
        + (remainder_price - average_entry_price) * plan.treatment_hold_qty
    )
    return StagedExitCounterfactual(
        baseline_pnl=baseline_pnl,
        treatment_pnl=treatment_pnl,
        pnl_delta=treatment_pnl - baseline_pnl,
        remainder_exit_session=remainder_session,
        remainder_exit_price=remainder_price,
        remainder_exit_reason=remainder_reason,
        sessions_observed=len(observed_prices),
        mfe_pct_from_baseline_exit=max(observed_prices) / baseline_exit_price - 1.0,
        mae_pct_from_baseline_exit=min(observed_prices) / baseline_exit_price - 1.0,
    )


def log_staged_exit_shadow(
    plan: ShockAwareStagedExitPlan,
    *,
    shadow_log_path: Path,
    run_id: str | None = None,
) -> None:
    """Append a durable shadow record. Callers must suppress this in dry-run mode."""
    shadow_log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "mode": "shadow",
        "run_id": run_id,
        **plan.to_dict(),
    }
    with shadow_log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
