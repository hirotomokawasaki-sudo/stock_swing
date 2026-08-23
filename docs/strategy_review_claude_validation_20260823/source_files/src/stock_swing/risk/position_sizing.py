"""Hybrid position sizing policy.

Initial implementation uses:
- max risk per trade as % of equity
- max position notional as % of equity
- max total exposure based on regime
- fallback risk_per_share using default stop % when no explicit stop is available

R2-v2 / H5 (2026-07-23):
- PositionSizingPolicy optionally accepts AllocationConfig so that
  stock / ETF multipliers come from the same YAML as PortfolioAllocator.
- PositionSizingResult gains before_multiplier_qty / after_multiplier_qty
  for console before/after display.
"""

from __future__ import annotations

import os as _os
from dataclasses import dataclass
from math import floor
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stock_swing.risk.allocation_config import AllocationConfig


REGIME_LIMITS = {
    "bullish": 0.85,  # Moderately aggressive for bull markets
    "neutral": 0.75,  # Target 70-75% exposure in neutral regime
    "cautious": 0.60, # Conservative in cautious regime
    "unknown": 0.75,  # Same as neutral when regime is uncertain
}

# 2026-07-30: 0.06 → 0.08 (ユーザー指示: 有効上限 60K → 80K / ~$1M equity)
# History: 0.08 → 0.06 (2026-05-15), 0.06 → 0.08 (2026-07-30)
DEFAULT_MAX_POSITION_NOTIONAL_PCT = 0.08
DEFAULT_MAX_SECTOR_EXPOSURE_PCT = 0.55
# Legacy module-level multipliers kept for backward compatibility.
# When PositionSizingPolicy is constructed with an AllocationConfig these are
# overridden by YAML values (stock_new_buy_multiplier / etf_new_buy_multiplier).
ETF_POSITION_SIZE_MULTIPLIER = 0.70  # Restored to 0.70: actual ETF PF=2.776 (broker data); earlier 0.35 was based on erroneous pre-rebuild data
STOCK_POSITION_SIZE_MULTIPLIER: float = float(_os.environ.get("STOCK_POSITION_SIZE_MULTIPLIER", "0.5"))

ETF_SYMBOLS = {
    'SHOC','SOXQ','SOXX','SMH','FTXL','PTF','SMHX','FRWD','TTEQ','GTOP','CHPX','CHPS','PSCT','QTEC','TDIV','SKYY','QTUM'
}

SYMBOL_SECTORS = {
    'NVDA':'semis', 'AVGO':'semis', 'AMD':'semis', 'TSM':'semis', 'ASML':'semis', 'INTC':'semis', 'MU':'semis', 'ARM':'semis', 'AMAT':'semis', 'LRCX':'semis', 'KLAC':'semis', 'QCOM':'semis', 'MRVL':'semis', 'SMCI':'semis', 'SNPS':'semis', 'CDNS':'semis', 'SOXX':'semis', 'SOXQ':'semis', 'SMH':'semis', 'FTXL':'semis', 'SMHX':'semis', 'SHOC':'semis', 'CHPX':'semis', 'CHPS':'semis',
    'MSFT':'software', 'CRM':'software', 'NOW':'software', 'SNOW':'software', 'MDB':'software', 'DDOG':'software', 'PLTR':'software', 'ADBE':'software', 'ORCL':'software', 'PATH':'software', 'FICO':'software', 'SKYY':'software', 'TTEQ':'software', 'GTOP':'software', 'PTF':'software', 'QTEC':'software', 'PSCT':'software', 'TDIV':'software', 'FRWD':'software', 'IBM':'software', 'CSCO':'software', 'HPE':'software', 'DELL':'software', 'HPQ':'software', 'CIEN':'software', 'RBRK':'software', 'CRWD':'software', 'PANW':'software', 'FTNT':'software', 'ANET':'software', 'NBIS':'software', 'CRDO':'software', 'INTU':'software',
    'GOOGL':'internet', 'AMZN':'internet', 'META':'internet', 'TSLA':'internet', 'V':'fintech', 'MA':'fintech', 'QTUM':'thematic',
    # 2026-08-19 (JP semiconductor/AI expansion Phase 2, section 5 — see
    # docs/jp_semiconductor_ai_expansion_phase2_design.md and
    # docs/jp_semiconductor_ai_expansion_plan.md). JP semiconductor-equipment
    # and -material makers are deliberately folded into the SAME 'semis'
    # sector key as their US counterparts (NOT a new 'jp_semis' key), so
    # that the existing max_sector_exposure_pct cap in PositionSizingPolicy
    # correctly limits COMBINED US+JP semiconductor exposure once JP orders
    # are wired in (Phase 3, post-IBKR). This mapping has NO effect today:
    # no JP symbol can be sized/ordered until Phase 3 wires in an IBKR
    # broker client, and current_sector_exposure for a JP symbol is always 0
    # until then (paper_executor.py only ever queries the currently-connected
    # Alpaca broker's positions).
    '6857.T':'semis',  # Advantest
    '8035.T':'semis',  # Tokyo Electron
    '6146.T':'semis',  # Disco
    '6920.T':'semis',  # Lasertec
    '7735.T':'semis',  # Screen Holdings
    '3436.T':'semis',  # Sumco
    '4063.T':'semis',  # Shin-Etsu Chemical (semiconductor-material business)
    '4062.T':'semis',  # Ibiden (IC package substrates)
    # Adjacent-but-not-core-semiconductor JP candidates get their own sector
    # keys (per Phase 2 design section 5's "暫定、Phase3で要再検討" note) so
    # they are not diluted into 'semis' capacity, nor left completely
    # unclassified.
    '5803.T':'jp_networking',  # Fujikura (AI datacenter optical/copper cable)
    '5801.T':'jp_networking',  # Furukawa Electric (same)
    '6506.T':'jp_robotics',    # Yaskawa Electric (robotics, aligns with existing robotics_ai theme)
}


@dataclass
class PositionSizingInputs:
    account_equity: float
    current_price: float
    current_total_exposure: float
    market_regime: str = "neutral"
    symbol: str | None = None
    asset_class: str | None = None
    max_risk_per_trade_pct: float = 0.005  # 0.5% risk per trade
    max_position_notional_pct: float = DEFAULT_MAX_POSITION_NOTIONAL_PCT
    default_stop_pct: float = 0.05
    risk_per_share: float | None = None
    current_sector_exposure: float = 0.0
    max_sector_exposure_pct: float = DEFAULT_MAX_SECTOR_EXPOSURE_PCT
    confidence: float | None = None
    exposure_cap_override: float | None = None  # Dynamic cap override (0.0–1.0); if set, supersedes REGIME_LIMITS


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
    max_sector_exposure_usd: float
    remaining_sector_capacity_usd: float
    risk_per_share_used: float
    regime_used: str
    asset_class_used: str
    sector_used: str | None
    skip_reason: str | None = None
    # R2-v2 / H5: before/after multiplier quantities for console display
    before_multiplier_qty: int | None = None   # qty before asset-class multiplier
    after_multiplier_qty: int | None = None    # qty after multiplier (== final_shares when multiplier < 1)
    multiplier_applied: float | None = None    # the multiplier value used
    # 2026-08-14 (roadmap gap #3): confidence_multiplier was computed and
    # applied to sizing (see PositionSizingPolicy.compute()'s
    # confidence_multiplier local var) but never recorded anywhere -- a
    # roadmap gap analysis found R4-v2's "confidence calibration" plan had
    # no record of confidence's actual sizing impact to calibrate against.
    # This field makes that value visible in DecisionRecord.evidence.sizing
    # going forward (existing historical decisions predating this change
    # will not have it -- see docs/console_improvement_tasks.md 穴3 対応).
    confidence_multiplier: float | None = None


def classify_asset_class(symbol: str | None, asset_class: str | None = None) -> str:
    symbol = (symbol or '').upper()
    return asset_class or ('etf' if symbol in ETF_SYMBOLS else 'stock')


# 2026-08-19 (JP semiconductor/AI expansion Phase 2 design — see
# docs/jp_semiconductor_ai_expansion_phase2_design.md section 3-C).
# JPX trades in round lots (単元株), almost universally 100 shares per unit
# for the candidate symbols in this expansion (post-2018 unification; TSE
# unified nearly all listings to a 100-share unit by 2018). This helper
# rounds a computed share count DOWN to the nearest tradable unit so JP
# order quantities are never rejected for violating lot-size rules.
#
# NOT wired into PositionSizingPolicy.size() yet for non-JP symbols: this is
# a standalone utility, applied automatically only when the symbol looks
# like a JP ticker (".T" suffix, Yahoo/most JP broker convention), so it is
# a no-op for every currently-traded US symbol (verified in
# tests/unit/test_position_sizing_policy.py's JP rounding tests).
JP_SYMBOL_SUFFIX = ".T"
JP_TRADING_UNIT = 100


def is_jp_symbol(symbol: str | None) -> bool:
    """Return True if `symbol` looks like a JPX-listed ticker (e.g. "8035.T")."""
    return bool(symbol) and symbol.upper().endswith(JP_SYMBOL_SUFFIX)


def round_to_jp_trading_unit(shares: int, unit: int = JP_TRADING_UNIT) -> int:
    """Round `shares` down to the nearest JPX trading unit (default 100).

    Floors (rounds toward zero / down) rather than rounding to nearest, so
    the resulting order never exceeds the risk/notional/exposure budget that
    produced `shares` in the first place.

    Args:
        shares: Raw computed share count (may be negative for a sell-side
            calculation elsewhere in the codebase, though this function is
            only used for BUY sizing today).
        unit: Trading unit size (default 100, the near-universal JPX round
            lot since the 2018 unit-size unification).

    Returns:
        `shares` rounded down to the nearest multiple of `unit`. Returns 0
        if `shares` is smaller than one full unit.
    """
    if shares <= 0 or unit <= 0:
        return 0
    return (shares // unit) * unit


def _resolve_asset_class(symbol: str | None, asset_class: str | None = None) -> str:
    return classify_asset_class(symbol, asset_class)


def effective_position_notional_pct(symbol: str | None, asset_class: str | None = None, base_pct: float = DEFAULT_MAX_POSITION_NOTIONAL_PCT) -> float:
    resolved_asset_class = _resolve_asset_class(symbol, asset_class)
    pct = float(base_pct)
    if resolved_asset_class == 'etf':
        pct *= ETF_POSITION_SIZE_MULTIPLIER
    elif resolved_asset_class == 'stock':
        pct *= STOCK_POSITION_SIZE_MULTIPLIER
    return round(pct, 6)


class PositionSizingPolicy:
    """Hybrid sizing policy using risk, notional, and exposure caps.

    R2-v2 / H5: accepts optional AllocationConfig so that stock/ETF multipliers
    come from the same YAML source as PortfolioAllocator.
    """

    def __init__(self, alloc_config: "AllocationConfig | None" = None) -> None:
        """Initialize policy.

        Args:
            alloc_config: When supplied, stock_new_buy_multiplier and
                etf_new_buy_multiplier are read from this config.  When None,
                the legacy module-level constants (ETF_POSITION_SIZE_MULTIPLIER /
                STOCK_POSITION_SIZE_MULTIPLIER) are used as fallback.
        """
        self._alloc_config = alloc_config

    def _get_multipliers(self) -> tuple[float, float]:
        """Return (stock_multiplier, etf_multiplier) to apply to final_shares.

        When alloc_config is supplied the multipliers come from YAML and are
        applied to final_shares; effective_position_notional_pct is called with
        base_pct only (no legacy baked-in multiplier).

        When alloc_config is NOT supplied (legacy path), effective_position_notional_pct
        already bakes the multiplier into the notional cap, so we return 1.0 here to
        avoid double-applying.
        """
        if self._alloc_config is not None:
            return (
                self._alloc_config.stock_new_buy_multiplier,
                self._alloc_config.etf_new_buy_multiplier,
            )
        # Legacy: multiplier already applied inside effective_position_notional_pct
        return (1.0, 1.0)

    def _notional_pct(self, symbol: str, asset_class: str, base_pct: float) -> float:
        """Return the notional cap pct for sizing.

        When alloc_config is set, multiplier is applied to final_shares (not here),
        so return base_pct unchanged.  Legacy path delegates to effective_position_notional_pct
        which bakes the multiplier in.
        """
        if self._alloc_config is not None:
            return float(base_pct)
        return effective_position_notional_pct(symbol, asset_class, base_pct)

    def size(self, inputs: PositionSizingInputs) -> PositionSizingResult:  # noqa: C901
        equity = max(float(inputs.account_equity or 0), 0.0)
        price = max(float(inputs.current_price or 0), 0.0)
        exposure = max(float(inputs.current_total_exposure or 0), 0.0)
        regime = (inputs.market_regime or "neutral").lower()
        regime_limit = inputs.exposure_cap_override if inputs.exposure_cap_override is not None else REGIME_LIMITS.get(regime, REGIME_LIMITS["neutral"])
        symbol = (inputs.symbol or '').upper()
        asset_class = classify_asset_class(symbol, inputs.asset_class)
        sector = SYMBOL_SECTORS.get(symbol)

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
        notional_pct = self._notional_pct(symbol, asset_class, float(inputs.max_position_notional_pct))
        max_position_notional_usd = equity * notional_pct
        max_total_exposure_usd = equity * regime_limit
        remaining_capacity = max_total_exposure_usd - exposure
        max_sector_exposure_usd = equity * float(inputs.max_sector_exposure_pct)
        remaining_sector_capacity = max_sector_exposure_usd - float(inputs.current_sector_exposure or 0)

        shares_by_risk = max(floor(max_loss_usd / risk_per_share), 0)
        shares_by_notional = max(floor(max_position_notional_usd / price), 0)
        shares_by_exposure = max(floor(max(remaining_capacity, 0.0) / price), 0)
        shares_by_sector = max(floor(max(remaining_sector_capacity, 0.0) / price), 0) if sector else shares_by_exposure
        base_final_shares = min(shares_by_risk, shares_by_notional, shares_by_exposure, shares_by_sector)

        confidence = float(inputs.confidence) if inputs.confidence is not None else None
        confidence_multiplier = 1.0
        if confidence is not None:
            if confidence >= 0.80:
                confidence_multiplier = 1.2
            elif confidence < 0.60:
                confidence_multiplier = 0.7
        boosted = floor(base_final_shares * confidence_multiplier)
        cap = min(shares_by_risk, shares_by_notional, shares_by_exposure, shares_by_sector)
        final_shares = min(boosted, cap)

        # R2-v2 / H5: apply asset-class multiplier from AllocationConfig (YAML)
        stock_mult, etf_mult = self._get_multipliers()
        asset_multiplier = etf_mult if asset_class == "etf" else stock_mult
        before_multiplier_qty = final_shares
        if asset_multiplier != 1.0 and final_shares > 0:
            final_shares = max(floor(final_shares * asset_multiplier), 0)
        after_multiplier_qty = final_shares

        # 2026-08-19 (JP semiconductor/AI expansion Phase 2, section 3-C):
        # JPX trades in round lots (default 100 shares/unit). This guard is
        # a final post-processing step applied ONLY to JP-ticker symbols
        # (".T" suffix) and is a strict no-op for every US symbol traded
        # today — it does not change any existing US sizing behavior.
        if is_jp_symbol(symbol):
            final_shares = round_to_jp_trading_unit(final_shares)

        skip_reason = None
        if remaining_capacity <= 0:
            skip_reason = "insufficient_remaining_exposure"
        elif sector and remaining_sector_capacity <= 0:
            skip_reason = "insufficient_remaining_sector_exposure"
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
            max_sector_exposure_usd=round(max_sector_exposure_usd, 2),
            remaining_sector_capacity_usd=round(max(remaining_sector_capacity, 0.0), 2),
            risk_per_share_used=round(risk_per_share, 4),
            regime_used=regime,
            asset_class_used=asset_class,
            sector_used=sector,
            skip_reason=skip_reason,
            before_multiplier_qty=before_multiplier_qty,
            after_multiplier_qty=after_multiplier_qty,
            multiplier_applied=asset_multiplier,
            confidence_multiplier=confidence_multiplier,
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
            max_sector_exposure_usd=0.0,
            remaining_sector_capacity_usd=0.0,
            risk_per_share_used=0.0,
            regime_used=regime,
            asset_class_used=classify_asset_class(inputs.symbol, inputs.asset_class),
            sector_used=SYMBOL_SECTORS.get((inputs.symbol or '').upper()),
            skip_reason=reason,
            before_multiplier_qty=0,
            after_multiplier_qty=0,
            multiplier_applied=None,
        )
