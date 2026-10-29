"""Session-aligned returns for sector-shock exit diagnostics.

Daily bars are useful as the previous-session anchor, but they must not be
treated as the current session return while the US market is open.  This
module combines an exact-date daily close with a live broker quote and fails
closed when either side of that calculation is missing or stale.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

from stock_swing.utils.market_calendar import MarketCalendar


ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class DailyReturnReference:
    symbol: str
    session_date: date
    close: float
    return_1d: float | None
    source: str


@dataclass(frozen=True)
class SessionReturnObservation:
    symbol: str
    return_pct: float | None
    previous_close: float | None
    current_price: float | None
    expected_session_date: str
    reference_session_date: str | None
    source: str
    quality_status: str
    reason: str
    observed_at: str

    @property
    def is_valid(self) -> bool:
        return self.quality_status == "valid" and self.return_pct is not None


def expected_completed_session_date(now_utc: datetime) -> date:
    """Return the market date of the latest completed US regular session."""
    return MarketCalendar.previous_trading_close_utc(now_utc).astimezone(ET).date()


def _finite_float(value: Any, *, positive: bool = False) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or (positive and parsed <= 0):
        return None
    return parsed


def _parse_feature_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(ET).date()


def _is_live_session(now_utc: datetime) -> bool:
    now_et = now_utc.astimezone(ET)
    is_holiday, _ = MarketCalendar.is_us_holiday(now_et)
    return (
        now_et.weekday() < 5
        and not is_holiday
        and time(4, 0) <= now_et.time() < MarketCalendar.REGULAR_END
    )


def load_benchmark_daily_references(
    prices_path: Path,
    returns_path: Path,
    *,
    symbols: set[str],
    expected_date: date,
) -> dict[str, DailyReturnReference]:
    """Load exact-date benchmark references; stale/latest-row fallback is forbidden."""
    closes: dict[str, float] = {}
    returns: dict[str, float] = {}

    try:
        with prices_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                symbol = str(row.get("symbol") or "").upper()
                if symbol not in symbols or row.get("date") != expected_date.isoformat():
                    continue
                close = _finite_float(row.get("close"), positive=True)
                if close is not None:
                    closes[symbol] = close
    except (OSError, csv.Error, UnicodeError):
        closes = {}

    try:
        with returns_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                symbol = str(row.get("symbol") or "").upper()
                if symbol not in symbols or row.get("date") != expected_date.isoformat():
                    continue
                daily_return = _finite_float(row.get("daily_return"))
                if daily_return is not None:
                    returns[symbol] = daily_return
    except (OSError, csv.Error, UnicodeError):
        returns = {}

    return {
        symbol: DailyReturnReference(
            symbol=symbol,
            session_date=expected_date,
            close=close,
            return_1d=returns.get(symbol),
            source="benchmark_csv_exact_date",
        )
        for symbol, close in closes.items()
    }


def _feature_references(
    features: Iterable[Any],
    *,
    symbols: set[str],
    expected_date: date,
    current_date: date,
    live_session: bool,
) -> dict[str, DailyReturnReference]:
    references: dict[str, DailyReturnReference] = {}
    for feature in features:
        symbol = str(getattr(feature, "symbol", "") or "").upper()
        if symbol not in symbols or getattr(feature, "feature_name", "") != "price_momentum":
            continue
        values = getattr(feature, "values", {}) or {}
        metadata = getattr(feature, "metadata", {}) or {}
        latest_date = _parse_feature_date(metadata.get("latest_time"))
        latest_close = _finite_float(values.get("latest_close"), positive=True)
        return_1d = _finite_float(values.get("return_1d"))
        if latest_date is None or latest_close is None:
            continue

        if latest_date == expected_date:
            references[symbol] = DailyReturnReference(
                symbol=symbol,
                session_date=expected_date,
                close=latest_close,
                return_1d=return_1d,
                source="price_feature_exact_date",
            )
            continue

        # Some daily feeds expose an in-progress current-session bar. Recover
        # the previous close from that bar's return instead of using the partial
        # close itself as the comparison anchor.
        if (
            live_session
            and latest_date == current_date
            and return_1d is not None
            and return_1d > -1.0
        ):
            previous_close = latest_close / (1.0 + return_1d)
            if math.isfinite(previous_close) and previous_close > 0:
                references[symbol] = DailyReturnReference(
                    symbol=symbol,
                    session_date=expected_date,
                    close=previous_close,
                    return_1d=None,
                    source="price_feature_current_bar_derived_previous_close",
                )
    return references


def build_session_return_observations(
    *,
    features: Iterable[Any],
    symbols: Iterable[str],
    get_mid_price: Callable[[str], float],
    now_utc: datetime,
    benchmark_prices_path: Path,
    benchmark_returns_path: Path,
) -> dict[str, SessionReturnObservation]:
    """Build return observations aligned to the current or last completed session."""
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    else:
        now_utc = now_utc.astimezone(timezone.utc)

    requested = {str(symbol).upper() for symbol in symbols if symbol}
    expected_date = expected_completed_session_date(now_utc)
    now_et = now_utc.astimezone(ET)
    live_session = _is_live_session(now_utc)

    references = load_benchmark_daily_references(
        benchmark_prices_path,
        benchmark_returns_path,
        symbols=requested,
        expected_date=expected_date,
    )
    references.update(
        _feature_references(
            features,
            symbols=requested,
            expected_date=expected_date,
            current_date=now_et.date(),
            live_session=live_session,
        )
    )

    observations: dict[str, SessionReturnObservation] = {}
    for symbol in sorted(requested):
        reference = references.get(symbol)
        common = {
            "symbol": symbol,
            "expected_session_date": expected_date.isoformat(),
            "reference_session_date": (
                reference.session_date.isoformat() if reference is not None else None
            ),
            "observed_at": now_utc.isoformat(),
        }
        if reference is None:
            observations[symbol] = SessionReturnObservation(
                return_pct=None,
                previous_close=None,
                current_price=None,
                source="none",
                quality_status="insufficient_data",
                reason="missing_exact_date_daily_reference",
                **common,
            )
            continue

        if live_session:
            try:
                current_price = _finite_float(get_mid_price(symbol), positive=True)
            except Exception:
                current_price = None
            if current_price is None:
                observations[symbol] = SessionReturnObservation(
                    return_pct=None,
                    previous_close=reference.close,
                    current_price=None,
                    source=reference.source,
                    quality_status="insufficient_data",
                    reason="missing_live_quote",
                    **common,
                )
                continue
            observations[symbol] = SessionReturnObservation(
                return_pct=(current_price - reference.close) / reference.close,
                previous_close=reference.close,
                current_price=current_price,
                source=f"live_quote_vs_{reference.source}",
                quality_status="valid",
                reason="current_session_quote_vs_previous_completed_close",
                **common,
            )
            continue

        if reference.return_1d is None:
            observations[symbol] = SessionReturnObservation(
                return_pct=None,
                previous_close=reference.close,
                current_price=reference.close,
                source=reference.source,
                quality_status="insufficient_data",
                reason="missing_completed_session_return",
                **common,
            )
            continue
        observations[symbol] = SessionReturnObservation(
            return_pct=reference.return_1d,
            previous_close=None,
            current_price=reference.close,
            source=reference.source,
            quality_status="valid",
            reason="latest_completed_session_return",
            **common,
        )

    return observations
