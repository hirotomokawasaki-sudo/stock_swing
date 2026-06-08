"""Open-shock cooldown guard for broad selloffs near the Monday open.

This guard is intentionally execution-time only. It does not change the exit
strategy itself; it filters generated sell candidates when the market appears
to be in a broad panic immediately after the weekend.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from stock_swing.feature_engine.base_feature import FeatureResult
from stock_swing.risk.weekend_gap_guard import to_us_eastern
from stock_swing.strategy_engine.base_strategy import CandidateSignal
from stock_swing.utils.market_calendar import MarketCalendar


@dataclass(frozen=True)
class OpenShockCooldownMetrics:
    """Computed market-wide shock metrics."""

    in_window: bool
    active: bool
    signals_hit: int
    spy_gap_pct: float | None
    qqq_gap_pct: float | None
    losers_ratio: float | None
    avg_gap_pct: float | None


@dataclass(frozen=True)
class OpenShockCooldownResult:
    """Result of applying the cooldown filter to exit candidates."""

    filtered_signals: list[CandidateSignal]
    metrics: OpenShockCooldownMetrics
    held_count: int
    forced_sell_count: int


DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "window_minutes": 60,
    "activation_min_signals": 2,
    "spy_gap_pct": -0.0125,
    "qqq_gap_pct": -0.02,
    "losers_ratio": 0.60,
    "avg_gap_pct": -0.02,
    "hold_trailing_stop": True,
    "hold_breakeven_stop": True,
    "hold_stop_loss": True,
    "force_sell_return_pct": -0.12,
    "force_sell_symbol_gap_pct": -0.15,
}


def _is_monday_open_window(now_utc: datetime, window_minutes: int) -> bool:
    eastern = to_us_eastern(now_utc)
    is_holiday, _ = MarketCalendar.is_us_holiday(eastern)
    if is_holiday or eastern.weekday() != 0:
        return False
    session_open = eastern.replace(hour=9, minute=30, second=0, microsecond=0)
    session_end = session_open + timedelta(minutes=max(window_minutes, 0))
    return session_open <= eastern < session_end


def _price_feature_map(features: list[FeatureResult]) -> dict[str, float]:
    price_map: dict[str, float] = {}
    for feature in features:
        if feature.feature_name != "price_momentum" or not feature.symbol:
            continue
        latest_close = feature.values.get("latest_close")
        if latest_close:
            price_map[str(feature.symbol).upper()] = float(latest_close)
    return price_map


def _safe_gap(current_price: float | None, previous_close: float | None) -> float | None:
    if current_price is None or previous_close is None:
        return None
    if current_price <= 0 or previous_close <= 0:
        return None
    return (current_price - previous_close) / previous_close


def _classify_exit_type(signal: CandidateSignal) -> str:
    trigger = str(signal.metadata.get("exit_trigger", "") or "").lower()
    reasoning = str(signal.reasoning or "").lower()
    text = f"{trigger} {reasoning}"
    if "trailing stop" in text:
        return "trailing_stop"
    if "breakeven stop" in text:
        return "breakeven_stop"
    if "stop loss" in text:
        return "stop_loss"
    if "max hold period" in text:
        return "time_exit"
    return "other"


def _build_hold_signal(
    signal: CandidateSignal,
    exit_type: str,
    symbol_gap_pct: float | None,
    metrics: OpenShockCooldownMetrics,
) -> CandidateSignal:
    metadata = dict(signal.metadata)
    metadata.update(
        {
            "cooldown_blocked": True,
            "cooldown_original_action": signal.action,
            "cooldown_original_exit_type": exit_type,
            "cooldown_reason": "market_wide_open_shock",
            "cooldown_symbol_gap_pct": symbol_gap_pct,
            "cooldown_metrics": {
                "spy_gap_pct": metrics.spy_gap_pct,
                "qqq_gap_pct": metrics.qqq_gap_pct,
                "losers_ratio": metrics.losers_ratio,
                "avg_gap_pct": metrics.avg_gap_pct,
                "signals_hit": metrics.signals_hit,
            },
        }
    )
    return CandidateSignal(
        strategy_id=signal.strategy_id,
        symbol=signal.symbol,
        action="hold",
        signal_strength=signal.signal_strength,
        generated_at=signal.generated_at,
        time_horizon=signal.time_horizon,
        confidence=signal.confidence,
        reasoning=(
            "Open Shock Cooldown active: held sell near Monday open "
            f"(original={exit_type}, signal={signal.reasoning})"
        ),
        feature_refs=list(signal.feature_refs),
        metadata=metadata,
    )


def apply_open_shock_cooldown(
    exit_signals: list[CandidateSignal],
    features: list[FeatureResult],
    get_mid_price: Callable[[str], float],
    now_utc: datetime | None = None,
    config: dict[str, Any] | None = None,
) -> OpenShockCooldownResult:
    """Hold eligible exit signals during a broad Monday open shock."""
    merged_config = dict(DEFAULT_CONFIG)
    if config:
        merged_config.update(config)

    now_utc = now_utc or datetime.now(UTC)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=UTC)

    if not merged_config.get("enabled", True):
        return OpenShockCooldownResult(
            filtered_signals=exit_signals,
            metrics=OpenShockCooldownMetrics(False, False, 0, None, None, None, None),
            held_count=0,
            forced_sell_count=0,
        )

    in_window = _is_monday_open_window(now_utc, int(merged_config.get("window_minutes", 60)))
    if not in_window:
        return OpenShockCooldownResult(
            filtered_signals=exit_signals,
            metrics=OpenShockCooldownMetrics(False, False, 0, None, None, None, None),
            held_count=0,
            forced_sell_count=0,
        )

    previous_close_map = _price_feature_map(features)

    spy_gap_pct = _safe_gap(get_mid_price("SPY"), previous_close_map.get("SPY"))
    qqq_gap_pct = _safe_gap(get_mid_price("QQQ"), previous_close_map.get("QQQ"))

    symbol_gaps: dict[str, float] = {}
    for symbol, previous_close in previous_close_map.items():
        current_price = get_mid_price(symbol)
        gap_pct = _safe_gap(current_price, previous_close)
        if gap_pct is not None:
            symbol_gaps[symbol] = gap_pct

    losers_ratio = None
    avg_gap_pct = None
    if symbol_gaps:
        losers = sum(1 for gap_pct in symbol_gaps.values() if gap_pct < 0)
        losers_ratio = losers / len(symbol_gaps)
        avg_gap_pct = sum(symbol_gaps.values()) / len(symbol_gaps)

    hit_count = 0
    if spy_gap_pct is not None and spy_gap_pct <= float(merged_config["spy_gap_pct"]):
        hit_count += 1
    if qqq_gap_pct is not None and qqq_gap_pct <= float(merged_config["qqq_gap_pct"]):
        hit_count += 1
    if losers_ratio is not None and losers_ratio >= float(merged_config["losers_ratio"]):
        hit_count += 1
    if avg_gap_pct is not None and avg_gap_pct <= float(merged_config["avg_gap_pct"]):
        hit_count += 1

    active = hit_count >= int(merged_config.get("activation_min_signals", 2))
    metrics = OpenShockCooldownMetrics(
        in_window=True,
        active=active,
        signals_hit=hit_count,
        spy_gap_pct=spy_gap_pct,
        qqq_gap_pct=qqq_gap_pct,
        losers_ratio=losers_ratio,
        avg_gap_pct=avg_gap_pct,
    )
    if not active:
        return OpenShockCooldownResult(
            filtered_signals=exit_signals,
            metrics=metrics,
            held_count=0,
            forced_sell_count=0,
        )

    hold_trailing_stop = bool(merged_config.get("hold_trailing_stop", True))
    hold_breakeven_stop = bool(merged_config.get("hold_breakeven_stop", True))
    hold_stop_loss = bool(merged_config.get("hold_stop_loss", True))
    force_sell_return_pct = float(merged_config.get("force_sell_return_pct", -0.12))
    force_sell_symbol_gap_pct = float(merged_config.get("force_sell_symbol_gap_pct", -0.15))

    filtered: list[CandidateSignal] = []
    held_count = 0
    forced_sell_count = 0
    for signal in exit_signals:
        if signal.action != "sell":
            filtered.append(signal)
            continue

        exit_type = _classify_exit_type(signal)
        symbol_gap_pct = symbol_gaps.get(signal.symbol.upper())
        return_pct = signal.metadata.get("return_pct")
        try:
            return_pct = float(return_pct) if return_pct is not None else None
        except (TypeError, ValueError):
            return_pct = None

        should_force_sell = (
            (return_pct is not None and return_pct <= force_sell_return_pct)
            or (
                symbol_gap_pct is not None
                and symbol_gap_pct <= force_sell_symbol_gap_pct
            )
        )
        if should_force_sell:
            forced_sell_count += 1
            filtered.append(signal)
            continue

        should_hold = (
            (exit_type == "trailing_stop" and hold_trailing_stop)
            or (exit_type == "breakeven_stop" and hold_breakeven_stop)
            or (exit_type == "stop_loss" and hold_stop_loss)
        )
        if should_hold:
            held_count += 1
            filtered.append(_build_hold_signal(signal, exit_type, symbol_gap_pct, metrics))
            continue

        filtered.append(signal)

    return OpenShockCooldownResult(
        filtered_signals=filtered,
        metrics=metrics,
        held_count=held_count,
        forced_sell_count=forced_sell_count,
    )
