from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from stock_swing.sources.massive_client import MassiveBar, MassiveClient


def get_latest_massive_close(
    client: MassiveClient,
    symbol: str,
    lookback_days: int = 5,
) -> tuple[float | None, str | None]:
    end_date = datetime.now(UTC).date()
    start_date = end_date.fromordinal(end_date.toordinal() - lookback_days)
    bars = client.fetch_daily_bars(symbol, start_date.isoformat(), end_date.isoformat(), limit=lookback_days + 2)
    if not bars:
        return (None, None)
    latest = max(bars, key=lambda b: b.timestamp)
    latest_ts = latest.timestamp.replace(tzinfo=UTC) if latest.timestamp.tzinfo is None else latest.timestamp.astimezone(UTC)
    return (float(latest.close), latest_ts.date().isoformat())


def compute_stale_price_overrides(
    positions: list[dict[str, Any]],
    massive: MassiveClient,
    *,
    min_deviation_pct: float = 5.0,
    previous_overrides: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    previous_overrides = previous_overrides or {}

    overrides: dict[str, Any] = {}
    logs: list[str] = []
    errors: list[str] = []

    for pos in positions:
        symbol = pos.get("symbol")
        if not symbol:
            continue

        try:
            broker_price = float(pos.get("current_price") or 0)
        except (TypeError, ValueError):
            broker_price = 0
        if broker_price <= 0:
            continue

        try:
            fresh_price, fresh_date = get_latest_massive_close(massive, symbol)
            if not fresh_price or not fresh_date:
                raise ValueError("no fresh daily close returned")

            deviation_pct = abs((fresh_price - broker_price) / broker_price) * 100
            if deviation_pct > min_deviation_pct:
                overrides[symbol] = {
                    "fresh_price": float(fresh_price),
                    "broker_price": broker_price,
                    "deviation_pct": deviation_pct,
                    "date": fresh_date,
                    "source": "massive_direct",
                    "updated_at": datetime.now(UTC).isoformat(),
                }
                logs.append(
                    f"  ⚠️  {symbol}: Broker ${broker_price:.2f} → Fresh ${fresh_price:.2f} ({deviation_pct:+.2f}%)"
                )
        except Exception as exc:
            prev = previous_overrides.get(symbol)
            if prev:
                overrides[symbol] = prev
                logs.append(f"  ↺ {symbol}: Massive fetch failed, preserved previous override")
            errors.append(f"{symbol}: {exc}")

    return overrides, logs, errors


def apply_price_overrides(
    positions_by_symbol: dict[str, dict[str, Any]],
    overrides: dict[str, Any],
) -> int:
    applied = 0
    for symbol, override in overrides.items():
        pos = positions_by_symbol.get(symbol)
        if not pos:
            continue
        try:
            fresh_price = float(override["fresh_price"])
        except (KeyError, TypeError, ValueError):
            continue
        pos["current_price"] = fresh_price
        applied += 1
    return applied


def apply_empty_override_guard(
    *,
    new_overrides: dict[str, Any],
    previous_payload: dict[str, Any] | None,
    generated_at: str,
) -> tuple[dict[str, Any], bool, bool, str | None]:
    previous_payload = previous_payload or {}
    previous_overrides = previous_payload.get("overrides", {}) if isinstance(previous_payload, dict) else {}
    clear_pending = bool(previous_payload.get("clear_pending", False))
    clear_pending_since = previous_payload.get("clear_pending_since")

    if new_overrides:
        return new_overrides, False, False, None

    if not previous_overrides:
        return {}, False, False, None

    if clear_pending:
        return {}, False, False, None

    return previous_overrides, True, True, clear_pending_since or generated_at
