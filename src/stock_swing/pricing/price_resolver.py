from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable


@dataclass(frozen=True)
class PriceCandidate:
    source: str
    price: float
    timestamp: datetime | None = None
    confidence: float = 0.5
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_positive(self) -> bool:
        return self.price > 0


@dataclass(frozen=True)
class PriceResolution:
    symbol: str
    price: float
    source: str
    confidence: float
    timestamp: datetime | None = None
    warnings: list[str] = field(default_factory=list)
    candidates: list[PriceCandidate] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.price > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "price": round(self.price, 6),
            "source": self.source,
            "confidence": round(self.confidence, 4),
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "warnings": list(self.warnings),
            "candidates": [
                {
                    "source": c.source,
                    "price": round(c.price, 6),
                    "timestamp": c.timestamp.isoformat() if c.timestamp else None,
                    "confidence": round(c.confidence, 4),
                }
                for c in self.candidates
            ],
        }


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


class PriceResolver:
    """Single authority for selecting execution and tracking prices."""

    def __init__(
        self,
        *,
        broker_client: Any | None = None,
        massive_client: Any | None = None,
        now_fn: Callable[[], datetime] | None = None,
        max_bar_age_days: int = 7,
        stale_position_deviation_pct: float = 0.30,
    ) -> None:
        self.broker_client = broker_client
        self.massive_client = massive_client
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.max_bar_age = timedelta(days=max_bar_age_days)
        self.stale_position_deviation_pct = stale_position_deviation_pct

    def _fresh_enough(self, ts: datetime | None) -> bool:
        if ts is None:
            return False
        return self.now_fn() - ts <= self.max_bar_age

    def from_decision_latest_close(self, symbol: str, decision: Any) -> PriceCandidate | None:
        evidence = getattr(decision, "evidence", None)
        if not isinstance(evidence, dict):
            return None
        try:
            price = float(evidence.get("latest_close") or 0)
        except (TypeError, ValueError):
            return None
        if price <= 0:
            return None
        return PriceCandidate(source="decision_latest_close", price=price, confidence=0.90)

    def from_feature_latest_close(self, symbol: str, feature_price: float | None) -> PriceCandidate | None:
        try:
            price = float(feature_price or 0)
        except (TypeError, ValueError):
            return None
        if price <= 0:
            return None
        return PriceCandidate(source="feature_latest_close", price=price, confidence=0.85)

    def from_limit_price(self, symbol: str, limit_price: float | None) -> PriceCandidate | None:
        try:
            price = float(limit_price or 0)
        except (TypeError, ValueError):
            return None
        if price <= 0:
            return None
        return PriceCandidate(source="limit_price", price=price, confidence=0.65)

    def from_broker_bar(self, symbol: str) -> PriceCandidate | None:
        if self.broker_client is None:
            return None
        try:
            env = self.broker_client.fetch_bars(symbol, timeframe="1Day", limit=1)
            payload = env.payload if hasattr(env, "payload") else env
            if isinstance(payload, dict):
                bars = payload.get("bars", [])
            elif isinstance(payload, list):
                bars = payload
            else:
                return None
            if not bars:
                return None
            bar = bars[-1]
            if not isinstance(bar, dict):
                return None
            price = float(bar.get("c") or bar.get("close") or 0)
            ts = _parse_ts(bar.get("t") or bar.get("timestamp"))
            # No timestamp → accept (matches original paper_executor behaviour).
            # Explicit timestamp present → reject only if stale.
            if price <= 0:
                return None
            if ts is not None and not self._fresh_enough(ts):
                return None
            return PriceCandidate(
                source="broker_bar",
                price=price,
                timestamp=ts,
                confidence=0.55,
                raw={"bar": bar},
            )
        except Exception:
            return None

    def from_broker_quote_mid(self, symbol: str) -> PriceCandidate | None:
        if self.broker_client is None:
            return None
        try:
            env = self.broker_client.fetch_latest_quote(symbol)
            payload = env.payload if hasattr(env, "payload") else env
            if not isinstance(payload, dict):
                return None
            quote = payload.get("quote", payload)
            if not isinstance(quote, dict):
                return None
            bid = float(quote.get("bp") or quote.get("bid_price") or 0)
            ask = float(quote.get("ap") or quote.get("ask_price") or 0)
            if bid <= 0 or ask <= 0:
                return None
            return PriceCandidate(
                source="broker_quote_mid",
                price=(bid + ask) / 2,
                confidence=0.75,
                raw={"bid": bid, "ask": ask},
            )
        except Exception:
            return None

    def resolve_entry_sizing_price(
        self,
        symbol: str,
        *,
        decision: Any | None = None,
        limit_price: float | None = None,
    ) -> PriceResolution:
        candidates = [
            self.from_decision_latest_close(symbol, decision),
            self.from_broker_quote_mid(symbol),
            self.from_broker_bar(symbol),
            self.from_limit_price(symbol, limit_price),
        ]
        valid = [c for c in candidates if c and c.is_positive]
        if not valid:
            return PriceResolution(symbol=symbol, price=0.0, source="none", confidence=0.0)
        best = valid[0]
        return PriceResolution(
            symbol=symbol,
            price=best.price,
            source=best.source,
            confidence=best.confidence,
            timestamp=best.timestamp,
            candidates=valid,
        )

    def resolve_exit_price(
        self,
        symbol: str,
        *,
        position_current_price: float | None,
        feature_price: float | None,
    ) -> PriceResolution:
        warnings: list[str] = []
        candidates: list[PriceCandidate] = []

        position_candidate = None
        try:
            p = float(position_current_price or 0)
            if p > 0:
                position_candidate = PriceCandidate("position_current_price", p, confidence=0.70)
                candidates.append(position_candidate)
        except (TypeError, ValueError):
            pass

        feature_candidate = self.from_feature_latest_close(symbol, feature_price)
        if feature_candidate:
            candidates.append(feature_candidate)

        if position_candidate and feature_candidate:
            deviation = abs(position_candidate.price - feature_candidate.price) / feature_candidate.price
            if deviation > self.stale_position_deviation_pct:
                warnings.append(
                    "position_current_price deviates from feature_latest_close "
                    f"by {deviation:.1%}; using feature price"
                )
                return PriceResolution(
                    symbol=symbol,
                    price=feature_candidate.price,
                    source="feature_over_stale_position",
                    confidence=feature_candidate.confidence,
                    candidates=candidates,
                    warnings=warnings,
                )

        if position_candidate:
            return PriceResolution(
                symbol=symbol,
                price=position_candidate.price,
                source=position_candidate.source,
                confidence=position_candidate.confidence,
                candidates=candidates,
            )
        if feature_candidate:
            return PriceResolution(
                symbol=symbol,
                price=feature_candidate.price,
                source=feature_candidate.source,
                confidence=feature_candidate.confidence,
                candidates=candidates,
            )
        return PriceResolution(symbol=symbol, price=0.0, source="none", confidence=0.0)
