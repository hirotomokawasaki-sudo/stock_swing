"""Hybrid position sizing policy.

Initial implementation uses:
- max risk per trade as % of equity
- max position notional as % of equity
- max total exposure based on regime
- fallback risk_per_share using default stop % when no explicit stop is available
"""

from __future__ import annotations

from dataclasses import dataclass
from math import floor


REGIME_LIMITS = {
    "bullish": 0.70,
    "neutral": 0.50,
    "cautious": 0.30,
    "unknown": 0.50,
}


@dataclass
class PositionSizingInputs:
    account_equity: float
    current_price: float
    current_total_exposure: float
    market_regime: str = "neutral"
    max_risk_per_trade_pct: float = 0.005
    max_position_notional_pct: float = 0.08
    default_stop_pct: float = 0.05
    risk_per_share: float | None = None


@dataclass
class PositionSizingResult:
    shares_by_risk: int
    shares_by_notional: int
    shares_by_exposure: int
    final_shares: int
    max_loss_usd: float
    max_position_notional_usd: float
    max_total_exposure_usd: float
    remaining_exposure_capacity_usd: float
    risk_per_share_used: float
    regime_used: str
    skip_reason: str | None = None


class PositionSizingPolicy:
    """Hybrid sizing policy using risk, notional, and exposure caps."""

    def size(self, inputs: PositionSizingInputs) -> PositionSizingResult:
        equity = max(float(inputs.account_equity or 0), 0.0)
        price = max(float(inputs.current_price or 0), 0.0)
        exposure = max(float(inputs.current_total_exposure or 0), 0.0)
        regime = (inputs.market_regime or "neutral").lower()
        regime_limit = REGIME_LIMITS.get(regime, REGIME_LIMITS["neutral"])

        if equity <= 0:
            return self._empty(inputs, regime, "invalid_account_equity")
        if price <= 0:
            return self._empty(inputs, regime, "invalid_current_price")

        risk_per_share = inputs.risk_per_share
        if risk_per_share is None or risk_per_share <= 0:
            risk_per_share = price * float(inputs.default_stop_pct)
        if risk_per_share <= 0:
            return self._empty(inputs, regime, "invalid_risk_per_share")

        max_loss_usd = equity * float(inputs.max_risk_per_trade_pct)
        max_position_notional_usd = equity * float(inputs.max_position_notional_pct)
        max_total_exposure_usd = equity * regime_limit
        remaining_capacity = max_total_exposure_usd - exposure

        shares_by_risk = max(floor(max_loss_usd / risk_per_share), 0)
        shares_by_notional = max(floor(max_position_notional_usd / price), 0)
        shares_by_exposure = max(floor(max(remaining_capacity, 0.0) / price), 0)
        final_shares = min(shares_by_risk, shares_by_notional, shares_by_exposure)

        skip_reason = None
        if remaining_capacity <= 0:
            skip_reason = "insufficient_remaining_exposure"
        elif shares_by_risk < 1:
            skip_reason = "shares_by_risk_below_1"
        elif shares_by_notional < 1:
            skip_reason = "shares_by_notional_below_1"
        elif shares_by_exposure < 1:
            skip_reason = "shares_by_exposure_below_1"
        elif final_shares < 1:
            skip_reason = "final_shares_below_1"

        return PositionSizingResult(
            shares_by_risk=shares_by_risk,
            shares_by_notional=shares_by_notional,
            shares_by_exposure=shares_by_exposure,
            final_shares=final_shares,
            max_loss_usd=round(max_loss_usd, 2),
            max_position_notional_usd=round(max_position_notional_usd, 2),
            max_total_exposure_usd=round(max_total_exposure_usd, 2),
            remaining_exposure_capacity_usd=round(max(remaining_capacity, 0.0), 2),
            risk_per_share_used=round(risk_per_share, 4),
            regime_used=regime,
            skip_reason=skip_reason,
        )

    def _empty(self, inputs: PositionSizingInputs, regime: str, reason: str) -> PositionSizingResult:
        return PositionSizingResult(
            shares_by_risk=0,
            shares_by_notional=0,
            shares_by_exposure=0,
            final_shares=0,
            max_loss_usd=0.0,
            max_position_notional_usd=0.0,
            max_total_exposure_usd=0.0,
            remaining_exposure_capacity_usd=0.0,
            risk_per_share_used=0.0,
            regime_used=regime,
            skip_reason=reason,
        )
