"""Unified allocation config loader for R2-v2 / H5.

Single source of truth for:
- Stock 85% / ETF 15% targets and bands
- Position sizing multipliers (stock / ETF)
- Sector / cluster caps
- ETF classification (from symbol_registry.yaml)

Both PortfolioAllocator and PositionSizingPolicy import from here so that
every layer reads the same YAML values.

History:
    R2-v2 / H5 (2026-07-23): extracted from portfolio_allocator.py + position_sizing.py
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Canonical YAML paths (relative to project root; callers may override)
_DEFAULT_ALLOC_PATH = Path("config/strategy/portfolio_allocation.yaml")
_DEFAULT_REGISTRY_PATH = Path("config/reference/symbol_registry.yaml")


@dataclass(frozen=True)
class AllocationConfig:
    """Parsed portfolio_allocation.yaml with fail-closed defaults.

    Defaults match portfolio_allocation.yaml as of 2026-07-23.
    All defaults are *fail-closed*: unknown symbols blocked, small multipliers, tight bands.
    """
    # --- Targets ---
    stock_target: float = 0.85
    etf_target: float = 0.15

    # --- Allocation band (market value / equity basis) ---
    stock_band_min: float = 0.80
    stock_band_max: float = 0.92
    etf_band_min: float = 0.08
    etf_band_max: float = 0.20

    # --- position sizing multipliers (risk adjustment, not strategy allocation) ---
    stock_new_buy_multiplier: float = 0.25   # temporary; YAML comment says 1.0 after R0-v2
    etf_new_buy_multiplier: float = 1.0

    # --- Concentration caps ---
    sector_cap_pct: float = 0.80
    correlated_cluster_cap_pct: float = 0.40

    # --- Band enforcement ---
    use_projected_allocation: bool = True
    configuration_issue: str | None = None


def read_allocation_config(path: Path | str | None = None) -> AllocationConfig:
    """Load AllocationConfig from portfolio_allocation.yaml.

    Falls back to fail-closed defaults when the file is missing or broken.

    Args:
        path: Path to portfolio_allocation.yaml.  When None uses project-relative default.

    Returns:
        AllocationConfig populated from YAML, or defaults on error.
    """
    resolved = Path(path) if path else _DEFAULT_ALLOC_PATH
    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("allocation_root_not_mapping")
        portfolio = raw.get("portfolio", {})
        if not isinstance(portfolio, dict): raise ValueError("portfolio_not_mapping")
        alloc = portfolio.get("allocation", {})
        band = portfolio.get("allocation_band", {})
        if not isinstance(alloc, dict) or not isinstance(band, dict): raise ValueError("allocation_nested_not_mapping")
        def number(value, fraction=True):
            if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or value < 0 or (fraction and value > 1):
                raise ValueError("allocation_invalid_number")
            return float(value)
        projected = portfolio.get("use_projected_allocation", True)
        if type(projected) is not bool: raise ValueError("allocation_invalid_boolean")
        config = AllocationConfig(
            stock_target=number(alloc.get("stocks", .85)), etf_target=number(alloc.get("ETFs", .15)),
            stock_band_min=number(band.get("stocks_min", .80)),stock_band_max=number(band.get("stocks_max", .92)),
            etf_band_min=number(band.get("etf_min", .08)),etf_band_max=number(band.get("etf_max", .20)),
            stock_new_buy_multiplier=number(raw.get("stock_new_buy_multiplier", .25),False),
            etf_new_buy_multiplier=number(raw.get("etf_new_buy_multiplier", 1.),False),
            sector_cap_pct=number(raw.get("sector_cap_pct", .80)),correlated_cluster_cap_pct=number(raw.get("correlated_cluster_cap_pct", .40)),
            use_projected_allocation=projected)
        if config.stock_band_min > config.stock_band_max or config.etf_band_min > config.etf_band_max:
            raise ValueError("allocation_reversed_band")
        return config
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        issue = "allocation_config_unavailable:" + type(exc).__name__
        logger.warning("%s at %s", issue, resolved)
        return AllocationConfig(configuration_issue=issue)


# ---------------------------------------------------------------------------
# Symbol registry helpers
# ---------------------------------------------------------------------------

def read_symbol_registry(path: Path | str | None = None) -> dict[str, dict[str, Any]]:
    """Load symbol_registry.yaml → {SYMBOL: {asset_class, sector, ...}}.

    Returns an empty dict on error (callers must handle unknown symbols).

    Args:
        path: Path to symbol_registry.yaml.  When None uses project-relative default.
    """
    resolved = Path(path) if path else _DEFAULT_REGISTRY_PATH
    if not resolved.exists():
        logger.warning("symbol_registry: %s not found – classification unavailable", resolved)
        return {}

    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
        symbols = raw.get("symbols") if isinstance(raw, dict) else None
        if not isinstance(symbols, dict) or not symbols: raise ValueError("registry_not_mapping")
        for symbol, info in symbols.items():
            if not isinstance(symbol, str) or not symbol.strip() or not isinstance(info, dict): raise ValueError("registry_invalid_row")
            if info.get("asset_class") not in {"stock", "etf"}: raise ValueError("registry_invalid_asset_class")
            if "is_semiconductor_related" in info and type(info["is_semiconductor_related"]) is not bool: raise ValueError("registry_invalid_boolean")
        if len({s.upper() for s in symbols}) != len(symbols): raise ValueError("registry_duplicate_symbol")
        return {sym.upper(): info for sym, info in symbols.items()}
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        logger.warning("symbol_registry unavailable at %s (%s)", resolved, type(exc).__name__)
        return {}


def get_etf_symbols_from_registry(registry: dict[str, dict[str, Any]]) -> frozenset[str]:
    """Return the set of ETF symbols from the registry.

    Args:
        registry: Parsed symbol registry dict (output of read_symbol_registry).
    """
    return frozenset(
        sym for sym, info in registry.items()
        if (info.get("asset_class") or "").lower() == "etf"
    )


def classify_symbol(symbol: str, registry: dict[str, dict[str, Any]]) -> str:
    """Return 'etf', 'stock', or 'unknown' for a given symbol.

    'unknown' means the symbol is not in the registry.  Callers should block
    BUY orders for unknown symbols until the registry is updated.

    Args:
        symbol: Ticker symbol (case-insensitive).
        registry: Parsed symbol registry dict.
    """
    info = registry.get(symbol.upper())
    if info is None:
        return "unknown"
    ac = (info.get("asset_class") or "").lower()
    if ac in ("etf", "stock"):
        return ac
    return "unknown"
