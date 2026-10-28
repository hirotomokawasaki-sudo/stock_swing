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


def read_allocation_config(path: Path | str | None = None) -> AllocationConfig:
    """Load AllocationConfig from portfolio_allocation.yaml.

    Falls back to fail-closed defaults when the file is missing or broken.

    Args:
        path: Path to portfolio_allocation.yaml.  When None uses project-relative default.

    Returns:
        AllocationConfig populated from YAML, or defaults on error.
    """
    resolved = Path(path) if path else _DEFAULT_ALLOC_PATH
    if not resolved.exists():
        logger.warning("allocation_config: %s not found – using defaults", resolved)
        return AllocationConfig()

    try:
        raw: dict[str, Any] = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.warning("allocation_config: failed to parse %s (%s) – using defaults", resolved, exc)
        return AllocationConfig()

    portfolio = raw.get("portfolio", {})
    alloc = portfolio.get("allocation", {})
    band = portfolio.get("allocation_band", {})

    return AllocationConfig(
        stock_target=float(alloc.get("stocks", 0.85)),
        etf_target=float(alloc.get("ETFs", 0.15)),
        stock_band_min=float(band.get("stocks_min", 0.80)),
        stock_band_max=float(band.get("stocks_max", 0.92)),
        etf_band_min=float(band.get("etf_min", 0.08)),
        etf_band_max=float(band.get("etf_max", 0.20)),
        stock_new_buy_multiplier=float(raw.get("stock_new_buy_multiplier", 0.25)),
        etf_new_buy_multiplier=float(raw.get("etf_new_buy_multiplier", 1.0)),
        sector_cap_pct=float(raw.get("sector_cap_pct", 0.80)),
        correlated_cluster_cap_pct=float(raw.get("correlated_cluster_cap_pct", 0.40)),
        use_projected_allocation=bool(portfolio.get("use_projected_allocation", True)),
    )


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
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.warning("symbol_registry: failed to parse %s (%s)", resolved, exc)
        return {}

    return {sym.upper(): info for sym, info in raw.get("symbols", {}).items()}


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
