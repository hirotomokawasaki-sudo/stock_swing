"""Shadow-first economic drawdown control, separate from operational HALTs.

Operational integrity failures (broker/tracker mismatch, missing critical
evidence, order-path failures) belong to the manually latched circuit breaker.
Market losses need different recovery semantics, so this module tracks them in
an independent state machine with staged risk reduction and hysteresis.

The metric is the cash-flow-adjusted account-equity return from the start of
the oldest session in a consecutive N-session NYSE window to the latest equity
observation.  Broker equity already contains realized and unrealized PnL, so
using the equity curve avoids the old realized-only ``weekly_total_loss_pct``
blind spot.
"""

from __future__ import annotations

import dataclasses
import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, time, timedelta, timezone
from enum import IntEnum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from stock_swing.utils.market_calendar import MarketCalendar


class EconomicRiskLevel(IntEnum):
    normal = 0
    reduce_size = 1
    block_buys = 2
    halt_new_risk = 3


class EconomicRiskStateError(RuntimeError):
    """Raised when persisted economic-risk state cannot be trusted."""


@dataclass(frozen=True)
class EconomicRiskPolicy:
    enabled: bool = False
    mode: str = "shadow"
    lookback_sessions: int = 5
    reduce_size_threshold_pct: float = -4.0
    block_buys_threshold_pct: float = -6.0
    halt_new_risk_threshold_pct: float = -8.0
    reduce_size_recovery_pct: float = -3.0
    block_buys_recovery_pct: float = -4.5
    halt_new_risk_recovery_pct: float = -6.5
    recovery_sessions_required: int = 2
    size_multiplier: float = 0.5
    max_history_sessions: int = 20

    @property
    def enforced(self) -> bool:
        return self.enabled and self.mode == "enforce"

    def validate(self) -> None:
        if self.mode not in {"shadow", "enforce"}:
            raise ValueError("economic_risk_off.mode must be 'shadow' or 'enforce'")
        if not 2 <= self.lookback_sessions <= 30:
            raise ValueError("lookback_sessions must be between 2 and 30")
        if not (
            self.halt_new_risk_threshold_pct
            < self.block_buys_threshold_pct
            < self.reduce_size_threshold_pct
            < 0
        ):
            raise ValueError("entry thresholds must satisfy halt < block < reduce < 0")
        if self.reduce_size_recovery_pct <= self.reduce_size_threshold_pct:
            raise ValueError("reduce_size recovery threshold must exceed its entry threshold")
        if self.block_buys_recovery_pct <= self.block_buys_threshold_pct:
            raise ValueError("block_buys recovery threshold must exceed its entry threshold")
        if self.halt_new_risk_recovery_pct <= self.halt_new_risk_threshold_pct:
            raise ValueError("halt_new_risk recovery threshold must exceed its entry threshold")
        if self.recovery_sessions_required < 1:
            raise ValueError("recovery_sessions_required must be positive")
        if not 0 < self.size_multiplier <= 1:
            raise ValueError("size_multiplier must be in (0, 1]")
        if self.max_history_sessions < self.lookback_sessions:
            raise ValueError("max_history_sessions must cover lookback_sessions")


@dataclass
class SessionEquityObservation:
    market_date: str
    start_equity: float
    latest_equity: float
    start_external_cash_flow: float
    latest_external_cash_flow: float
    first_observed_at: str
    last_observed_at: str


@dataclass
class EconomicRiskState:
    status: str = EconomicRiskLevel.normal.name
    action: str = "allow"
    observed_pct: float | None = None
    metric_name: str = "rolling_session_total_loss_pct"
    window_start_date: str | None = None
    window_end_date: str | None = None
    data_status: str = "insufficient_history"
    recovery_sessions: int = 0
    recovery_last_counted_market_date: str | None = None
    changed_at: str | None = None
    last_evaluated_at: str | None = None
    history: list[SessionEquityObservation] = field(default_factory=list)

    @property
    def level(self) -> EconomicRiskLevel:
        try:
            return EconomicRiskLevel[self.status]
        except KeyError as exc:
            raise EconomicRiskStateError(f"unknown economic risk status: {self.status}") from exc

    @property
    def blocks_new_buys(self) -> bool:
        return self.level >= EconomicRiskLevel.block_buys

    def effective_size_multiplier(self, policy: EconomicRiskPolicy) -> float:
        if self.level == EconomicRiskLevel.reduce_size:
            return policy.size_multiplier
        if self.blocks_new_buys:
            return 0.0
        return 1.0

    def to_summary(self, policy: EconomicRiskPolicy) -> dict[str, Any]:
        return {
            "enabled": policy.enabled,
            "mode": policy.mode,
            "enforced": policy.enforced,
            "status": self.status,
            "action": self.action,
            "observed_pct": self.observed_pct,
            "metric_name": self.metric_name,
            "lookback_sessions": policy.lookback_sessions,
            "window_start_date": self.window_start_date,
            "window_end_date": self.window_end_date,
            "data_status": self.data_status,
            "recovery_sessions": self.recovery_sessions,
            "recovery_sessions_required": policy.recovery_sessions_required,
            "last_evaluated_at": self.last_evaluated_at,
            "thresholds": {
                "reduce_size_pct": policy.reduce_size_threshold_pct,
                "block_buys_pct": policy.block_buys_threshold_pct,
                "halt_new_risk_pct": policy.halt_new_risk_threshold_pct,
            },
        }


def load_policy_from_dict(payload: dict[str, Any]) -> EconomicRiskPolicy:
    """Load the optional policy section from the shared guardrail YAML."""
    raw = payload.get("economic_risk_off")
    if not isinstance(raw, dict):
        return EconomicRiskPolicy()

    thresholds = raw.get("thresholds") or {}
    recovery = raw.get("recovery") or {}
    policy = EconomicRiskPolicy(
        enabled=bool(raw.get("enabled", False)),
        mode=str(raw.get("mode", "shadow")),
        lookback_sessions=int(raw.get("lookback_sessions", 5)),
        reduce_size_threshold_pct=float(thresholds.get("reduce_size_pct", -4.0)),
        block_buys_threshold_pct=float(thresholds.get("block_buys_pct", -6.0)),
        halt_new_risk_threshold_pct=float(thresholds.get("halt_new_risk_pct", -8.0)),
        reduce_size_recovery_pct=float(recovery.get("reduce_size_above_pct", -3.0)),
        block_buys_recovery_pct=float(recovery.get("block_buys_above_pct", -4.5)),
        halt_new_risk_recovery_pct=float(recovery.get("halt_new_risk_above_pct", -6.5)),
        recovery_sessions_required=int(recovery.get("consecutive_sessions", 2)),
        size_multiplier=float(raw.get("size_multiplier", 0.5)),
        max_history_sessions=int(raw.get("max_history_sessions", 20)),
    )
    policy.validate()
    return policy


def load_cumulative_external_cash_flow(
    path: Path,
    *,
    expected_account_id: str | None = None,
) -> float:
    """Read the audited cumulative external cash-flow adjustment.

    Missing or malformed evidence is an error instead of silently assuming
    zero.  Shadow mode reports the error; future enforced mode can fail closed.
    """
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        account_id = str(payload.get("broker_account_id") or "")
        if expected_account_id and account_id != expected_account_id:
            raise ValueError("broker account does not match reconciliation evidence")
        value = float(payload["external_cash_adjustment"])
    except Exception as exc:
        raise EconomicRiskStateError(f"external cash-flow evidence unavailable: {path}") from exc
    if not math.isfinite(value):
        raise EconomicRiskStateError("external cash-flow adjustment must be finite")
    return value


def _coerce_as_of(as_of: datetime | None) -> datetime:
    value = as_of or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _market_date(as_of: datetime | None) -> date:
    return _coerce_as_of(as_of).astimezone(ZoneInfo("America/New_York")).date()


def _is_trading_session(value: date) -> bool:
    if value.weekday() >= 5:
        return False
    dt = datetime.combine(value, time(12), tzinfo=ZoneInfo("America/New_York"))
    is_holiday, _ = MarketCalendar.is_us_holiday(dt)
    return not is_holiday


def trading_session_dates_ending(end_date: date, count: int) -> list[str]:
    """Return the final ``count`` NYSE session dates ending on/before a date."""
    result: list[str] = []
    candidate = end_date
    scanned = 0
    while len(result) < count and scanned < 90:
        if _is_trading_session(candidate):
            result.append(candidate.isoformat())
        candidate -= timedelta(days=1)
        scanned += 1
    if len(result) != count:
        raise EconomicRiskStateError("could not construct consecutive NYSE sessions")
    return list(reversed(result))


def _metric_from_history(
    history: list[SessionEquityObservation],
    lookback_sessions: int,
) -> tuple[float | None, str, str | None, str | None]:
    if len(history) < lookback_sessions:
        return None, "insufficient_history", None, None

    selected = history[-lookback_sessions:]
    end_date = date.fromisoformat(selected[-1].market_date)
    expected = trading_session_dates_ending(end_date, lookback_sessions)
    actual = [item.market_date for item in selected]
    if actual != expected:
        return None, "incomplete_sessions", selected[0].market_date, selected[-1].market_date

    start = selected[0]
    end = selected[-1]
    if start.start_equity <= 0:
        return None, "invalid_start_equity", start.market_date, end.market_date

    external_flow_delta = end.latest_external_cash_flow - start.start_external_cash_flow
    pnl = end.latest_equity - start.start_equity - external_flow_delta
    pct = round(pnl / start.start_equity * 100, 4)
    return pct, "ready", start.market_date, end.market_date


def _target_level(observed_pct: float, policy: EconomicRiskPolicy) -> EconomicRiskLevel:
    if observed_pct <= policy.halt_new_risk_threshold_pct:
        return EconomicRiskLevel.halt_new_risk
    if observed_pct <= policy.block_buys_threshold_pct:
        return EconomicRiskLevel.block_buys
    if observed_pct <= policy.reduce_size_threshold_pct:
        return EconomicRiskLevel.reduce_size
    return EconomicRiskLevel.normal


def _recovery_threshold(level: EconomicRiskLevel, policy: EconomicRiskPolicy) -> float:
    if level == EconomicRiskLevel.halt_new_risk:
        return policy.halt_new_risk_recovery_pct
    if level == EconomicRiskLevel.block_buys:
        return policy.block_buys_recovery_pct
    if level == EconomicRiskLevel.reduce_size:
        return policy.reduce_size_recovery_pct
    return float("inf")


def _action_for_level(level: EconomicRiskLevel) -> str:
    return {
        EconomicRiskLevel.normal: "allow",
        EconomicRiskLevel.reduce_size: "reduce_size",
        EconomicRiskLevel.block_buys: "block_buys",
        EconomicRiskLevel.halt_new_risk: "halt_new_risk",
    }[level]


def _apply_transition(
    state: EconomicRiskState,
    *,
    target: EconomicRiskLevel,
    observed_pct: float,
    market_date: str,
    now: str,
    policy: EconomicRiskPolicy,
) -> EconomicRiskState:
    current = state.level
    if target > current:
        return replace(
            state,
            status=target.name,
            action=_action_for_level(target),
            recovery_sessions=0,
            recovery_last_counted_market_date=None,
            changed_at=now,
        )

    if target == current or current == EconomicRiskLevel.normal:
        return replace(
            state,
            recovery_sessions=0,
            recovery_last_counted_market_date=None,
        )

    threshold = _recovery_threshold(current, policy)
    if observed_pct <= threshold:
        return replace(
            state,
            recovery_sessions=0,
            recovery_last_counted_market_date=None,
        )

    recovery_sessions = state.recovery_sessions
    last_counted = state.recovery_last_counted_market_date
    if last_counted != market_date:
        recovery_sessions += 1
        last_counted = market_date

    if recovery_sessions < policy.recovery_sessions_required:
        return replace(
            state,
            recovery_sessions=recovery_sessions,
            recovery_last_counted_market_date=last_counted,
        )

    next_level = EconomicRiskLevel(current - 1)
    return replace(
        state,
        status=next_level.name,
        action=_action_for_level(next_level),
        recovery_sessions=0,
        recovery_last_counted_market_date=None,
        changed_at=now,
    )


class EconomicRiskStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> EconomicRiskState:
        if not self.path.exists():
            return EconomicRiskState()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            known = {item.name for item in dataclasses.fields(EconomicRiskState)}
            state_data = {key: value for key, value in payload.items() if key in known}
            state_data["history"] = [
                SessionEquityObservation(**item)
                for item in (state_data.get("history") or [])
            ]
            state = EconomicRiskState(**state_data)
            _ = state.level
            return state
        except Exception as exc:
            raise EconomicRiskStateError(f"economic risk state is invalid: {self.path}") from exc

    def save(self, state: EconomicRiskState) -> None:
        payload = asdict(state)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=str(self.path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def observe(
        self,
        policy: EconomicRiskPolicy,
        *,
        equity: float,
        cumulative_external_cash_flow: float,
        as_of: datetime | None = None,
        persist: bool = True,
    ) -> EconomicRiskState:
        policy.validate()
        current = self.load()
        now_dt = _coerce_as_of(as_of)
        now = now_dt.astimezone(timezone.utc).isoformat()

        if not policy.enabled:
            state = replace(current, data_status="disabled", last_evaluated_at=now)
            if persist:
                self.save(state)
            return state
        if not math.isfinite(equity) or equity <= 0:
            raise EconomicRiskStateError("equity must be positive and finite")
        if not math.isfinite(cumulative_external_cash_flow):
            raise EconomicRiskStateError("cumulative external cash flow must be finite")

        current_market_date = _market_date(now_dt)
        if not _is_trading_session(current_market_date):
            state = replace(current, data_status="non_trading_session", last_evaluated_at=now)
            if persist:
                self.save(state)
            return state

        market_date_str = current_market_date.isoformat()
        history = list(current.history)
        observations_by_date = {item.market_date: item for item in history}
        existing = observations_by_date.get(market_date_str)
        if existing is not None:
            observations_by_date[market_date_str] = replace(
                existing,
                latest_equity=float(equity),
                latest_external_cash_flow=float(cumulative_external_cash_flow),
                last_observed_at=now,
            )
        else:
            observations_by_date[market_date_str] = SessionEquityObservation(
                market_date=market_date_str,
                start_equity=float(equity),
                latest_equity=float(equity),
                start_external_cash_flow=float(cumulative_external_cash_flow),
                latest_external_cash_flow=float(cumulative_external_cash_flow),
                first_observed_at=now,
                last_observed_at=now,
            )
        history = sorted(observations_by_date.values(), key=lambda item: item.market_date)[
            -policy.max_history_sessions :
        ]

        observed_pct, data_status, window_start, window_end = _metric_from_history(
            history,
            policy.lookback_sessions,
        )
        state = replace(
            current,
            history=history,
            observed_pct=observed_pct,
            data_status=data_status,
            window_start_date=window_start,
            window_end_date=window_end,
            last_evaluated_at=now,
        )
        if observed_pct is not None:
            state = _apply_transition(
                state,
                target=_target_level(observed_pct, policy),
                observed_pct=observed_pct,
                market_date=market_date_str,
                now=now,
                policy=policy,
            )
        if persist:
            self.save(state)
        return state
