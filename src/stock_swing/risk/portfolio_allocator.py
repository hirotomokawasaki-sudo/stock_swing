"""Portfolio allocation enforcement for ETF vs Stock targets.

R2-v2 / H5 (2026-07-23): refactored to use AllocationConfig as single source of truth.
  - allocation_band enforced via projected-allocation check
  - symbol classification via symbol_registry (unknown symbols blocked for BUY)
  - stock / ETF multipliers from YAML (not hardcoded)
  - PortfolioAllocator.check_projected_band() is the canonical guard
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Set

from stock_swing.risk.allocation_config import (
    AllocationConfig,
    classify_symbol,
    get_etf_symbols_from_registry,
    read_allocation_config,
    read_symbol_registry,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProjectedBandResult:
    """Outcome of check_projected_band()."""
    allowed: bool
    reason: str
    current_pct: float
    projected_pct: float
    band_min: float
    band_max: float
    asset_class: str  # 'etf' or 'stock'


class PortfolioAllocator:
    """Enforce portfolio allocation rules (ETF vs Stocks).

    Config source (single YAML):
        portfolio_allocation.yaml  →  AllocationConfig (via read_allocation_config)

    Classification source (single YAML):
        symbol_registry.yaml  →  read_symbol_registry / classify_symbol

    Key methods:
        check_projected_band()        – per-order projected allocation guard
        filter_decisions_by_allocation()  – pre-run BUY filter
        get_allocation_status()       – monitoring snapshot
    """

    def __init__(
        self,
        config_path: Path | str | None = None,
        registry_path: Path | str | None = None,
        *,
        config: AllocationConfig | None = None,
        registry: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """Initialize allocator from YAML files or pre-loaded objects (for testing).

        Args:
            config_path: Path to portfolio_allocation.yaml (None → project-relative default).
            registry_path: Path to symbol_registry.yaml (None → project-relative default).
            config: Pre-loaded AllocationConfig (overrides config_path; useful in tests).
            registry: Pre-loaded symbol registry dict (overrides registry_path; useful in tests).
        """
        self.config: AllocationConfig = config if config is not None else read_allocation_config(config_path)
        self._registry: dict[str, dict[str, Any]] = registry if registry is not None else read_symbol_registry(registry_path)
        self._etf_symbols: frozenset[str] = get_etf_symbols_from_registry(self._registry)

        logger.info(
            "PortfolioAllocator: stock_target=%.0f%% (%.0f%%–%.0f%%) "
            "ETF_target=%.0f%% (%.0f%%–%.0f%%) "
            "stock_mult=%.2f etf_mult=%.2f registry=%d symbols",
            self.config.stock_target * 100,
            self.config.stock_band_min * 100,
            self.config.stock_band_max * 100,
            self.config.etf_target * 100,
            self.config.etf_band_min * 100,
            self.config.etf_band_max * 100,
            self.config.stock_new_buy_multiplier,
            self.config.etf_new_buy_multiplier,
            len(self._registry),
        )

    # ------------------------------------------------------------------
    # Public: classification helpers
    # ------------------------------------------------------------------

    def is_etf(self, symbol: str) -> bool:
        """Return True when symbol is classified as ETF in the registry."""
        ac = classify_symbol(symbol, self._registry)
        if ac == "unknown":
            # Fall back to the ETF symbol set derived from registry
            return symbol.upper() in self._etf_symbols
        return ac == "etf"

    def classify(self, symbol: str) -> str:
        """Return 'etf', 'stock', or 'unknown' for *symbol*."""
        return classify_symbol(symbol, self._registry)

    @property
    def etf_symbols(self) -> frozenset[str]:
        """Frozenset of ETF symbols from the registry."""
        return self._etf_symbols

    # ------------------------------------------------------------------
    # Public: projected allocation guard (core of H5)
    # ------------------------------------------------------------------

    def check_projected_band(
        self,
        symbol: str,
        proposed_notional: float,
        current_positions: Dict[str, Any],
        equity: float,
    ) -> ProjectedBandResult:
        """Check whether adding *proposed_notional* for *symbol* stays within the allocation band.

        Uses *equity* as the denominator (A-definition: market value / account equity).

        Args:
            symbol: Ticker to buy.
            proposed_notional: Dollar value of the proposed order (qty × price).
            current_positions: {symbol: {'market_value': float, ...}} current open positions.
            equity: Total account equity (denominator).

        Returns:
            ProjectedBandResult with allowed flag and diagnostic fields.
        """
        if not self.config.use_projected_allocation:
            return ProjectedBandResult(
                allowed=True, reason="projected_check_disabled",
                current_pct=0.0, projected_pct=0.0,
                band_min=0.0, band_max=1.0, asset_class="unknown",
            )

        sym_class = self.classify(symbol)
        is_etf_sym = sym_class == "etf"
        asset_class = "etf" if is_etf_sym else "stock"

        # current invested values by class
        etf_mv = sum(
            float(pos.get("market_value", 0))
            for sym, pos in current_positions.items()
            if classify_symbol(sym, self._registry) == "etf"
            or sym.upper() in self._etf_symbols
        )
        stock_mv = sum(
            float(pos.get("market_value", 0))
            for sym, pos in current_positions.items()
            if classify_symbol(sym, self._registry) != "etf"
            and sym.upper() not in self._etf_symbols
        )

        denom = max(float(equity), 1.0)

        if is_etf_sym:
            current_pct = etf_mv / denom
            projected_pct = (etf_mv + proposed_notional) / denom
            band_min = self.config.etf_band_min
            band_max = self.config.etf_band_max
        else:
            current_pct = stock_mv / denom
            projected_pct = (stock_mv + proposed_notional) / denom
            band_min = self.config.stock_band_min
            band_max = self.config.stock_band_max

        if projected_pct > band_max:
            reason = (
                f"projected_{asset_class}_pct={projected_pct:.1%} > band_max={band_max:.1%}"
            )
            logger.info(
                "check_projected_band: BLOCKED %s (%s) proposed=$%.0f "
                "current=%.1f%% projected=%.1f%% band=[%.1f%%–%.1f%%]",
                symbol, asset_class, proposed_notional,
                current_pct * 100, projected_pct * 100,
                band_min * 100, band_max * 100,
            )
            return ProjectedBandResult(
                allowed=False, reason=reason,
                current_pct=current_pct, projected_pct=projected_pct,
                band_min=band_min, band_max=band_max, asset_class=asset_class,
            )

        return ProjectedBandResult(
            allowed=True,
            reason=f"{asset_class}_projected={projected_pct:.1%} within [{band_min:.1%}–{band_max:.1%}]",
            current_pct=current_pct, projected_pct=projected_pct,
            band_min=band_min, band_max=band_max, asset_class=asset_class,
        )

    # ------------------------------------------------------------------
    # Public: decision filtering (pre-run BUY filter)
    # ------------------------------------------------------------------

    def filter_decisions_by_allocation(
        self,
        decisions: List[Any],
        current_positions: Dict[str, Any],
        etf_symbols: Set[str] | None = None,   # legacy; ignored if registry loaded
        account_equity: float | None = None,
    ) -> List[Any]:
        """Filter BUY decisions: unknown symbols blocked, band overweight blocked.

        Rules (in order):
        1. SELL decisions pass through unchanged.
        2. Unknown symbol (not in registry) → BUY blocked.
        3. Projected allocation would exceed band_max → BUY blocked.
        4. ETF hard cap (legacy exact cap) remains as additional guard.

        Args:
            decisions: List of decision objects with .proposed_order.{symbol, side, notional}.
            current_positions: {symbol: {market_value, ...}} current positions.
            etf_symbols: Legacy override; ignored when registry contains entries.
            account_equity: Total account equity for percentage calculations.

        Returns:
            Filtered (and reordered) list of decisions.
        """
        if not decisions:
            return []

        sell_decisions = [d for d in decisions if d.proposed_order.side != "buy"]
        buy_decisions = [d for d in decisions if d.proposed_order.side == "buy"]

        if not buy_decisions:
            return decisions

        equity = float(account_equity or 0) or None

        # Resolve ETF symbol set: prefer registry, fall back to caller-supplied set
        effective_etf_syms: frozenset[str] = (
            self._etf_symbols if self._registry
            else frozenset(etf_symbols or [])
        )

        filtered_buys: list[Any] = []
        blocked_unknown = 0
        blocked_band = 0

        # FIX-ALLOC-5: running_positions accumulates accepted BUY notionals
        # within this run so that a second BUY cannot push over the band even
        # if the first BUY has not yet settled into current_positions.
        # We work on a shallow copy so broker current_positions stay immutable.
        running_positions: Dict[str, Any] = dict(current_positions)

        for d in buy_decisions:
            symbol: str = d.proposed_order.symbol

            # --- Rule 1: unknown symbol ---
            if self._registry and self.classify(symbol) == "unknown":
                blocked_unknown += 1
                logger.warning(
                    "PortfolioAllocator: blocking BUY %s – not in symbol_registry. "
                    "Add to config/reference/symbol_registry.yaml to allow.",
                    symbol,
                )
                continue

            # --- Rule 2: projected band check (uses running_positions, not just broker) ---
            notional: float = 0.0
            if equity and equity > 0:
                notional_raw = getattr(d.proposed_order, "notional", None)
                if notional_raw is None:
                    qty = getattr(d.proposed_order, "quantity", None) or getattr(d.proposed_order, "qty", 0) or 0
                    price = getattr(d.proposed_order, "limit_price", None) or getattr(d.proposed_order, "price", 0) or 0
                    if float(price) <= 0:
                        blocked_band += 1
                        logger.info(
                            "PortfolioAllocator: blocking BUY %s – price_unavailable",
                            symbol,
                        )
                        continue
                    notional_raw = float(qty) * float(price)
                notional = float(notional_raw)

                if notional > 0:
                    band_result = self.check_projected_band(symbol, notional, running_positions, equity)
                    if not band_result.allowed:
                        blocked_band += 1
                        logger.info(
                            "PortfolioAllocator: blocking BUY %s – %s (cumulative projection)",
                            symbol, band_result.reason,
                        )
                        continue

            filtered_buys.append(d)

            # FIX-ALLOC-5: Add accepted BUY notional to running_positions
            # so the next iteration sees the projected exposure.
            if notional > 0:
                sym_upper = symbol.upper()
                existing = running_positions.get(sym_upper, {})
                existing_mv = float(existing.get("market_value", 0))
                running_positions[sym_upper] = {
                    **existing,
                    "market_value": existing_mv + notional,
                    "_projected": True,  # flag: not yet broker-confirmed
                }

        if blocked_unknown:
            logger.warning(
                "PortfolioAllocator: blocked %d BUY(s) for unregistered symbols", blocked_unknown
            )
        if blocked_band:
            logger.info(
                "PortfolioAllocator: blocked %d BUY(s) for projected band overweight", blocked_band
            )

        # --- Legacy ETF hard cap (keep as belt-and-suspenders) ---
        if equity and equity > 0:
            etf_mv = sum(
                float(pos.get("market_value", 0))
                for sym, pos in current_positions.items()
                if sym.upper() in effective_etf_syms
            )
            etf_cap_usd = equity * self.config.etf_target
            etf_over_cap = etf_mv > etf_cap_usd
        else:
            etf_over_cap = False

        final_buys: list[Any] = []
        blocked_etf = 0
        etf_mv_running = (
            sum(float(pos.get("market_value", 0)) for sym, pos in current_positions.items() if sym.upper() in effective_etf_syms)
            if equity else 0.0
        )
        etf_cap_usd = (equity or 0) * self.config.etf_target

        for d in filtered_buys:
            symbol = d.proposed_order.symbol
            is_etf_buy = symbol.upper() in effective_etf_syms
            if is_etf_buy and etf_over_cap:
                blocked_etf += 1
                logger.info(
                    "PortfolioAllocator: blocking ETF BUY %s – ETF mv $%.0f >= cap $%.0f",
                    symbol, etf_mv_running, etf_cap_usd,
                )
                continue
            final_buys.append(d)

        # --- Ordering: prioritise under-weight asset class ---
        if equity and equity > 0:
            etf_mv_now = sum(
                float(pos.get("market_value", 0))
                for sym, pos in current_positions.items()
                if sym.upper() in effective_etf_syms
            )
            stock_mv_now = sum(
                float(pos.get("market_value", 0))
                for sym, pos in current_positions.items()
                if sym.upper() not in effective_etf_syms
            )
            denom = max(float(equity), 1.0)
            etf_pct = etf_mv_now / denom
            stock_pct = stock_mv_now / denom
            etf_deficit = self.config.etf_target - etf_pct
            stock_deficit = self.config.stock_target - stock_pct

            etf_buys = [d for d in final_buys if d.proposed_order.symbol.upper() in effective_etf_syms]
            stock_buys = [d for d in final_buys if d.proposed_order.symbol.upper() not in effective_etf_syms]

            REBALANCE_THRESHOLD = 0.05
            if etf_deficit > REBALANCE_THRESHOLD:
                final_buys = etf_buys + stock_buys
            elif stock_deficit > REBALANCE_THRESHOLD:
                final_buys = stock_buys + etf_buys

        return sell_decisions + final_buys

    # ------------------------------------------------------------------
    # Public: monitoring snapshot
    # ------------------------------------------------------------------

    def get_allocation_status(
        self,
        current_positions: Dict[str, Any],
        etf_symbols: Set[str] | None = None,
        account_equity: float | None = None,
    ) -> Dict[str, Any]:
        """Return current allocation metrics for console / monitoring.

        Args:
            current_positions: {symbol: {market_value, ...}} current positions.
            etf_symbols: Legacy override (ignored when registry loaded).
            account_equity: Total account equity.
        """
        effective_etf_syms = (
            self._etf_symbols if self._registry
            else frozenset(etf_symbols or [])
        )

        etf_mv = sum(
            float(pos.get("market_value", 0))
            for sym, pos in current_positions.items()
            if sym.upper() in effective_etf_syms
        )
        stock_mv = sum(
            float(pos.get("market_value", 0))
            for sym, pos in current_positions.items()
            if sym.upper() not in effective_etf_syms
        )
        total_mv = etf_mv + stock_mv
        denom = max(float(account_equity or 0) or total_mv, 1.0)

        current_etf_pct = etf_mv / denom
        current_stock_pct = stock_mv / denom
        etf_cap_usd = denom * self.config.etf_target

        return {
            "total_value": total_mv,
            "etf_value": etf_mv,
            "stock_value": stock_mv,
            "current_etf_pct": current_etf_pct,
            "current_stock_pct": current_stock_pct,
            "target_etf_pct": self.config.etf_target,
            "target_stock_pct": self.config.stock_target,
            "etf_band": (self.config.etf_band_min, self.config.etf_band_max),
            "stock_band": (self.config.stock_band_min, self.config.stock_band_max),
            "etf_cap_usd": etf_cap_usd,
            "etf_cap_hit": etf_mv >= etf_cap_usd,
            "etf_deficit": self.config.etf_target - current_etf_pct,
            "stock_deficit": self.config.stock_target - current_stock_pct,
            "needs_rebalance": current_etf_pct < (self.config.etf_target - 0.05),
            # multipliers from YAML (same source as sizing)
            "stock_new_buy_multiplier": self.config.stock_new_buy_multiplier,
            "etf_new_buy_multiplier": self.config.etf_new_buy_multiplier,
        }
