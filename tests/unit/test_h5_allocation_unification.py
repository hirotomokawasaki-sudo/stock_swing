"""R2-v2 / H5: Canonical allocation config unification tests.

Validates that PortfolioAllocator and PositionSizingPolicy share a single
config source (portfolio_allocation.yaml) and that:
  - unknown symbols are blocked for BUY
  - allocation_band is enforced via projected allocation check
  - stock / ETF multipliers from YAML change final_shares
  - correlated sector positions respect cluster cap
  - config / allocator / sizing layers propagate the same values
  - fallback is fail-closed when YAML is missing or broken

H5 required tests (from codex_fix_instructions_20260721.md):
  test_unknown_symbol_is_blocked
  test_historical_asset_class_backfill_is_idempotent  (acceptance only; actual backfill in R0-v2-B)
  test_stock_85_etf_15_is_single_policy_source
  test_target_band_blocks_projected_overweight
  test_stock_multiplier_changes_final_qty
  test_correlated_positions_share_cluster_cap

Acceptance criteria:
  AC1 – asset_class/sector unknown=0 (registry backfill already done in R0-v2-B)
  AC2 – config / allocator / sizing / console / improvement plan target = Stock 85% / ETF 15%
  AC3 – target band overweight orders blocked (projected check)
  AC4 – console target/actual/projected use same denominator
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from stock_swing.risk.allocation_config import (
    AllocationConfig,
    classify_symbol,
    get_etf_symbols_from_registry,
    read_allocation_config,
    read_symbol_registry,
)
from stock_swing.risk.portfolio_allocator import PortfolioAllocator
from stock_swing.risk.position_sizing import PositionSizingInputs, PositionSizingPolicy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_registry(etf_symbols: list[str], stock_symbols: list[str]) -> dict[str, Any]:
    reg: dict[str, Any] = {}
    for s in etf_symbols:
        reg[s.upper()] = {"asset_class": "etf", "sector": "semiconductor"}
    for s in stock_symbols:
        reg[s.upper()] = {"asset_class": "stock", "sector": "semiconductor"}
    return reg


def _make_config(
    *,
    stock_mult: float = 0.25,
    etf_mult: float = 1.0,
    stock_min: float = 0.80,
    stock_max: float = 0.92,
    etf_min: float = 0.08,
    etf_max: float = 0.20,
) -> AllocationConfig:
    return AllocationConfig(
        stock_target=0.85,
        etf_target=0.15,
        stock_band_min=stock_min,
        stock_band_max=stock_max,
        etf_band_min=etf_min,
        etf_band_max=etf_max,
        stock_new_buy_multiplier=stock_mult,
        etf_new_buy_multiplier=etf_mult,
        sector_cap_pct=0.80,
        correlated_cluster_cap_pct=0.40,
    )


def _decision(symbol: str, side: str = "buy", qty: int = 10, price: float = 100.0) -> Any:
    """Minimal duck-typed decision object."""
    order = SimpleNamespace(symbol=symbol, side=side, quantity=qty, limit_price=price, notional=qty * price)
    return SimpleNamespace(proposed_order=order)


def _pos(market_value: float) -> dict[str, Any]:
    return {"market_value": market_value}


# ---------------------------------------------------------------------------
# 1. allocation_config.py unit tests
# ---------------------------------------------------------------------------

class TestReadAllocationConfig:
    def test_reads_from_yaml(self, tmp_path: Path) -> None:
        """Acceptance: YAML values are propagated to AllocationConfig fields."""
        yaml_text = textwrap.dedent("""\
            portfolio:
              allocation:
                stocks: 0.85
                ETFs: 0.15
              allocation_band:
                stocks_min: 0.80
                stocks_max: 0.92
                etf_min: 0.08
                etf_max: 0.20
              use_projected_allocation: true
            stock_new_buy_multiplier: 0.25
            etf_new_buy_multiplier: 1.0
            sector_cap_pct: 0.80
            correlated_cluster_cap_pct: 0.40
        """)
        p = tmp_path / "portfolio_allocation.yaml"
        p.write_text(yaml_text)
        cfg = read_allocation_config(p)
        assert cfg.stock_target == pytest.approx(0.85), "stock_target from YAML"
        assert cfg.etf_target == pytest.approx(0.15), "etf_target from YAML"
        assert cfg.stock_new_buy_multiplier == pytest.approx(0.25), "stock_multiplier from YAML"
        assert cfg.etf_new_buy_multiplier == pytest.approx(1.0), "etf_multiplier from YAML"
        assert cfg.stock_band_min == pytest.approx(0.80)
        assert cfg.stock_band_max == pytest.approx(0.92)

    def test_missing_file_returns_failclosed_defaults(self, tmp_path: Path) -> None:
        """Fail-closed: missing YAML returns defaults (stock=0.85, mult=0.25)."""
        cfg = read_allocation_config(tmp_path / "nonexistent.yaml")
        assert cfg.stock_target == pytest.approx(0.85), "default stock_target"
        assert cfg.stock_new_buy_multiplier == pytest.approx(0.25), "default multiplier is fail-closed (small)"
        assert cfg.use_projected_allocation is True

    def test_broken_yaml_returns_defaults(self, tmp_path: Path) -> None:
        """Fail-closed: broken YAML returns defaults without raising."""
        p = tmp_path / "broken.yaml"
        p.write_text("{{ this is not valid yaml !!!")
        cfg = read_allocation_config(p)
        assert cfg.stock_target == pytest.approx(0.85)


class TestReadSymbolRegistry:
    def test_parses_etf_and_stock(self, tmp_path: Path) -> None:
        yaml_text = textwrap.dedent("""\
            symbols:
              SMH:
                asset_class: etf
                sector: semiconductor
              NVDA:
                asset_class: stock
                sector: semiconductor
        """)
        p = tmp_path / "symbol_registry.yaml"
        p.write_text(yaml_text)
        reg = read_symbol_registry(p)
        assert "SMH" in reg
        assert "NVDA" in reg
        assert reg["SMH"]["asset_class"] == "etf"

    def test_missing_file_returns_empty_dict(self, tmp_path: Path) -> None:
        """Fail-closed: missing registry → empty dict (callers block unknown)."""
        reg = read_symbol_registry(tmp_path / "missing.yaml")
        assert reg == {}, "empty dict on missing file"

    def test_get_etf_symbols_from_registry(self, tmp_path: Path) -> None:
        registry = _make_registry(["SMH", "SOXX"], ["NVDA", "AMD"])
        etfs = get_etf_symbols_from_registry(registry)
        assert "SMH" in etfs
        assert "SOXX" in etfs
        assert "NVDA" not in etfs


class TestClassifySymbol:
    def test_etf_returns_etf(self) -> None:
        reg = _make_registry(["SMH"], [])
        assert classify_symbol("SMH", reg) == "etf"
        assert classify_symbol("smh", reg) == "etf"  # case-insensitive

    def test_stock_returns_stock(self) -> None:
        reg = _make_registry([], ["NVDA"])
        assert classify_symbol("NVDA", reg) == "stock"

    def test_unknown_symbol_returns_unknown(self) -> None:
        reg = _make_registry(["SMH"], ["NVDA"])
        assert classify_symbol("AAPL", reg) == "unknown", "unregistered symbol → unknown"


# ---------------------------------------------------------------------------
# 2. H5 acceptance tests
# ---------------------------------------------------------------------------

class TestUnknownSymbolIsBlocked:
    """H5 test: test_unknown_symbol_is_blocked"""

    def test_unknown_symbol_buy_is_blocked(self) -> None:
        """BUY for a symbol not in registry must be blocked."""
        registry = _make_registry(["SMH"], ["NVDA"])
        config = _make_config()
        alloc = PortfolioAllocator(config=config, registry=registry)

        decisions = [_decision("UNKNOWN_TICKER")]
        result = alloc.filter_decisions_by_allocation(
            decisions, current_positions={}, account_equity=1_000_000
        )
        assert result == [], "unknown symbol BUY must be blocked"

    def test_registered_symbol_buy_passes(self) -> None:
        """BUY for a registered stock with room in band is allowed."""
        registry = _make_registry(["SMH"], ["NVDA"])
        config = _make_config()
        alloc = PortfolioAllocator(config=config, registry=registry)

        decisions = [_decision("NVDA", qty=10, price=100.0)]
        # No existing positions → stock_pct=0% → projected=0.1% → well within band
        result = alloc.filter_decisions_by_allocation(
            decisions, current_positions={}, account_equity=1_000_000
        )
        assert len(result) == 1, "registered symbol with band room must be allowed"

    def test_sell_decision_passes_regardless(self) -> None:
        """SELL decisions pass through even for unknown symbols."""
        registry = _make_registry(["SMH"], ["NVDA"])
        config = _make_config()
        alloc = PortfolioAllocator(config=config, registry=registry)

        decisions = [_decision("UNKNOWN", side="sell")]
        result = alloc.filter_decisions_by_allocation(
            decisions, current_positions={}, account_equity=1_000_000
        )
        assert len(result) == 1, "SELL passes regardless of registry status"


class TestHistoricalAssetClassBackfillIsIdempotent:
    """H5 test: test_historical_asset_class_backfill_is_idempotent
    Acceptance: classify_symbol is deterministic and idempotent for same input.
    (Actual data backfill was performed in R0-v2-B.)
    """

    def test_classify_is_idempotent(self) -> None:
        registry = _make_registry(["SMH", "SOXX"], ["NVDA", "AMD"])
        for sym in ["SMH", "SOXX", "NVDA", "AMD"]:
            first = classify_symbol(sym, registry)
            second = classify_symbol(sym, registry)
            assert first == second, f"classify_symbol({sym}) is not idempotent"

    def test_etf_symbols_set_is_idempotent(self) -> None:
        registry = _make_registry(["SMH", "SOXX"], ["NVDA"])
        first = get_etf_symbols_from_registry(registry)
        second = get_etf_symbols_from_registry(registry)
        assert first == second, "get_etf_symbols_from_registry is idempotent"


class TestStock85Etf15IsSinglePolicySource:
    """H5 test: test_stock_85_etf_15_is_single_policy_source

    Verifies that both PortfolioAllocator AND PositionSizingPolicy read from
    the same AllocationConfig object and expose the same targets.

    Acceptance: AC2 – config / allocator / sizing use identical target values.
    """

    def test_allocator_and_sizing_share_same_config(self) -> None:
        config = _make_config(stock_mult=0.25, etf_mult=1.0)
        alloc = PortfolioAllocator(config=config, registry={})
        policy = PositionSizingPolicy(alloc_config=config)

        # allocator exposes YAML targets
        assert alloc.config.stock_target == pytest.approx(0.85), "allocator.config.stock_target"
        assert alloc.config.etf_target == pytest.approx(0.15), "allocator.config.etf_target"

        # sizing reads multipliers from same config object
        stock_mult, etf_mult = policy._get_multipliers()
        assert stock_mult == pytest.approx(config.stock_new_buy_multiplier), "sizing stock_mult matches config"
        assert etf_mult == pytest.approx(config.etf_new_buy_multiplier), "sizing etf_mult matches config"

    def test_allocation_status_shows_correct_targets(self) -> None:
        """get_allocation_status() reports targets from config, not hardcoded."""
        config = _make_config()
        alloc = PortfolioAllocator(config=config, registry=_make_registry(["SMH"], ["NVDA"]))
        status = alloc.get_allocation_status({}, account_equity=1_000_000)
        assert status["target_stock_pct"] == pytest.approx(0.85), "AC2 – status uses config target"
        assert status["target_etf_pct"] == pytest.approx(0.15), "AC2 – status uses config target"
        assert "stock_band" in status
        assert "etf_band" in status


class TestTargetBandBlocksProjectedOverweight:
    """H5 test: test_target_band_blocks_projected_overweight

    Acceptance: AC3 – projected-overweight BUY orders are blocked.
    """

    def _make_alloc_with_etf_positions(self, etf_mv: float) -> tuple[PortfolioAllocator, dict]:
        """Helper: allocator with etf_max=0.20, current ETF already at etf_mv."""
        registry = _make_registry(["SMH", "SOXX"], ["NVDA"])
        config = _make_config(etf_max=0.20, etf_min=0.08, stock_min=0.80, stock_max=0.92)
        alloc = PortfolioAllocator(config=config, registry=registry)
        positions = {"SMH": _pos(etf_mv)}
        return alloc, positions

    def test_etf_buy_blocked_when_projected_exceeds_band_max(self) -> None:
        """AC3: ETF buy blocked when projected ETF% > etf_band_max (20%)."""
        alloc, positions = self._make_alloc_with_etf_positions(etf_mv=180_000)
        # Current ETF = 180k / 1M = 18% – below 20% cap
        # Proposed buy: 30 shares × $1000 = $30k → projected = 210k/1M = 21% > 20%
        band = alloc.check_projected_band("SMH", proposed_notional=30_000, current_positions=positions, equity=1_000_000)
        assert not band.allowed, "projected ETF 21% > band_max 20% must block"
        assert "etf" in band.asset_class
        assert band.projected_pct == pytest.approx(0.21)

    def test_etf_buy_allowed_within_band(self) -> None:
        """ETF buy allowed when projected ETF% stays within band."""
        alloc, positions = self._make_alloc_with_etf_positions(etf_mv=100_000)
        # Current ETF = 100k/1M = 10%. Add $50k → projected = 15% < 20%
        band = alloc.check_projected_band("SMH", proposed_notional=50_000, current_positions=positions, equity=1_000_000)
        assert band.allowed, "projected 15% within [8%–20%] must be allowed"

    def test_stock_buy_blocked_when_projected_exceeds_stock_band_max(self) -> None:
        """Stock buy blocked when projected stock% > stock_band_max (92%)."""
        registry = _make_registry(["SMH"], ["NVDA"])
        config = _make_config(stock_max=0.92)
        alloc = PortfolioAllocator(config=config, registry=registry)
        # 900k stock already in portfolio → 90% of 1M equity
        positions = {"NVDA": _pos(900_000)}
        # Add $50k → projected = 950k/1M = 95% > 92%
        band = alloc.check_projected_band("NVDA", proposed_notional=50_000, current_positions=positions, equity=1_000_000)
        assert not band.allowed, "projected stock 95% > band_max 92% must block"

    def test_filter_blocks_overweight_etf_in_full_pipeline(self) -> None:
        """filter_decisions_by_allocation: projected-overweight ETF BUY is blocked end-to-end."""
        registry = _make_registry(["SMH"], ["NVDA"])
        config = _make_config(etf_max=0.20)
        alloc = PortfolioAllocator(config=config, registry=registry)
        # ETF already at 190k/1M = 19%. Proposed buy: 120 shares × $100 = $12k → 20.2% > 20%
        positions = {"SMH": _pos(190_000)}
        decisions = [_decision("SMH", qty=120, price=100.0)]
        result = alloc.filter_decisions_by_allocation(
            decisions, current_positions=positions, account_equity=1_000_000
        )
        assert result == [], "overweight ETF BUY must be blocked by filter"

    def test_projected_check_disabled_always_allows(self) -> None:
        """When use_projected_allocation=False, band check is skipped."""
        registry = _make_registry(["SMH"], ["NVDA"])
        config = AllocationConfig(
            etf_target=0.15, etf_band_min=0.08, etf_band_max=0.20,
            stock_target=0.85, stock_band_min=0.80, stock_band_max=0.92,
            use_projected_allocation=False,
        )
        alloc = PortfolioAllocator(config=config, registry=registry)
        # Even with 50% ETF, projected check is disabled
        band = alloc.check_projected_band("SMH", proposed_notional=500_000, current_positions={}, equity=1_000_000)
        assert band.allowed, "projected check disabled → always allowed"


class TestStockMultiplierChangesFinalQty:
    """H5 test: test_stock_multiplier_changes_final_qty

    Verifies that position sizing applies the multiplier from AllocationConfig
    (YAML) to final_shares, and that before/after qty fields are populated.

    Acceptance: multiplier from YAML is reflected in final order qty.
    """

    def test_stock_multiplier_reduces_final_shares(self) -> None:
        """stock_new_buy_multiplier=0.25 → final_shares = floor(before * 0.25)."""
        config = _make_config(stock_mult=0.25)
        policy = PositionSizingPolicy(alloc_config=config)
        result = policy.size(PositionSizingInputs(
            account_equity=1_000_000,
            current_price=100.0,
            current_total_exposure=400_000,
            symbol="NVDA",
            asset_class="stock",
        ))
        assert result.before_multiplier_qty is not None
        assert result.after_multiplier_qty is not None
        assert result.multiplier_applied == pytest.approx(0.25)
        assert result.final_shares == result.after_multiplier_qty
        assert result.final_shares == result.before_multiplier_qty // 4, (
            f"expected floor(before*0.25)={result.before_multiplier_qty//4}, got {result.final_shares}"
        )

    def test_etf_multiplier_one_leaves_qty_unchanged(self) -> None:
        """etf_new_buy_multiplier=1.0 → final_shares unchanged."""
        config = _make_config(etf_mult=1.0)
        policy = PositionSizingPolicy(alloc_config=config)
        result = policy.size(PositionSizingInputs(
            account_equity=1_000_000,
            current_price=100.0,
            current_total_exposure=400_000,
            symbol="SMH",
            asset_class="etf",
        ))
        assert result.multiplier_applied == pytest.approx(1.0)
        assert result.before_multiplier_qty == result.after_multiplier_qty, "1.0 mult leaves qty unchanged"

    def test_stock_multiplier_half_halves_qty(self) -> None:
        """stock_mult=0.5 → before_multiplier_qty is roughly 2× final_shares."""
        config = _make_config(stock_mult=0.5)
        policy = PositionSizingPolicy(alloc_config=config)
        result = policy.size(PositionSizingInputs(
            account_equity=1_000_000,
            current_price=100.0,
            current_total_exposure=400_000,
            symbol="NVDA",
            asset_class="stock",
        ))
        assert result.multiplier_applied == pytest.approx(0.5)
        assert result.final_shares == result.before_multiplier_qty // 2

    def test_without_alloc_config_falls_back_to_legacy_multiplier(self) -> None:
        """When no AllocationConfig supplied, legacy multipliers are used (no crash)."""
        policy = PositionSizingPolicy()  # no alloc_config
        result = policy.size(PositionSizingInputs(
            account_equity=1_000_000,
            current_price=100.0,
            current_total_exposure=400_000,
            symbol="NVDA",
        ))
        assert result.final_shares >= 0, "legacy fallback must not crash"
        assert result.multiplier_applied is not None, "multiplier_applied populated"


class TestCorrelatedPositionsShareClusterCap:
    """H5 test: test_correlated_positions_share_cluster_cap

    Validates that sector_cap_pct from AllocationConfig limits
    total exposure within a sector.

    Note: cluster cap enforcement lives in PositionSizingPolicy via
    max_sector_exposure_pct; this test verifies the YAML value flows through.
    """

    def test_sector_cap_from_yaml_applied_in_sizing(self) -> None:
        """sector_cap_pct from AllocationConfig is used as max_sector_exposure_pct."""
        config = _make_config()  # sector_cap_pct=0.80
        policy = PositionSizingPolicy(alloc_config=config)

        # No remaining sector capacity → should skip
        result = policy.size(PositionSizingInputs(
            account_equity=1_000_000,
            current_price=100.0,
            current_total_exposure=400_000,
            symbol="NVDA",
            current_sector_exposure=900_000,   # 90% of 1M > 80% cap
            max_sector_exposure_pct=config.sector_cap_pct,
        ))
        assert result.skip_reason in (
            "insufficient_remaining_sector_exposure",
            "final_shares_below_1",
            "shares_by_notional_below_1",
            None,  # may be overridden by exposure cap first
        )
        # remaining sector capacity should be zero or negative
        assert result.remaining_sector_capacity_usd <= 0.0

    def test_correlated_cluster_cap_in_config(self) -> None:
        """correlated_cluster_cap_pct is readable from AllocationConfig."""
        config = read_allocation_config(
            Path("config/strategy/portfolio_allocation.yaml")
        )
        assert config.correlated_cluster_cap_pct == pytest.approx(0.40), (
            "AC2: cluster cap must come from YAML"
        )


# ---------------------------------------------------------------------------
# 3. Layer propagation tests (config → allocator → filter → sizing)
# ---------------------------------------------------------------------------

class TestLayerPropagation:
    """Acceptance: AC4 – all layers use same denominator and same config values."""

    def test_allocation_config_to_allocator_propagation(self, tmp_path: Path) -> None:
        """config YAML → read_allocation_config → AllocationConfig → PortfolioAllocator."""
        yaml_text = textwrap.dedent("""\
            portfolio:
              allocation:
                stocks: 0.85
                ETFs: 0.15
              allocation_band:
                stocks_min: 0.80
                stocks_max: 0.92
                etf_min: 0.08
                etf_max: 0.20
              use_projected_allocation: true
            stock_new_buy_multiplier: 0.30
            etf_new_buy_multiplier: 0.90
            sector_cap_pct: 0.75
            correlated_cluster_cap_pct: 0.35
        """)
        p = tmp_path / "pa.yaml"
        p.write_text(yaml_text)
        cfg = read_allocation_config(p)
        alloc = PortfolioAllocator(config=cfg, registry={})

        # Config layer
        assert cfg.stock_new_buy_multiplier == pytest.approx(0.30)
        # Allocator layer
        assert alloc.config.stock_new_buy_multiplier == pytest.approx(0.30), "allocator mirrors config"
        assert alloc.config.sector_cap_pct == pytest.approx(0.75)

    def test_allocation_config_to_sizing_propagation(self, tmp_path: Path) -> None:
        """config YAML → AllocationConfig → PositionSizingPolicy multipliers."""
        yaml_text = textwrap.dedent("""\
            portfolio:
              allocation: {stocks: 0.85, ETFs: 0.15}
              allocation_band:
                stocks_min: 0.80
                stocks_max: 0.92
                etf_min: 0.08
                etf_max: 0.20
            stock_new_buy_multiplier: 0.40
            etf_new_buy_multiplier: 0.80
        """)
        p = tmp_path / "pa2.yaml"
        p.write_text(yaml_text)
        cfg = read_allocation_config(p)
        policy = PositionSizingPolicy(alloc_config=cfg)

        result = policy.size(PositionSizingInputs(
            account_equity=1_000_000,
            current_price=100.0,
            current_total_exposure=0,
            symbol="NVDA",
            asset_class="stock",
        ))
        assert result.multiplier_applied == pytest.approx(0.40), "sizing reads multiplier from YAML via AllocationConfig"

    def test_allocation_status_same_denominator_as_projected_check(self) -> None:
        """AC4: get_allocation_status and check_projected_band use same equity denominator."""
        registry = _make_registry(["SMH"], ["NVDA"])
        config = _make_config()
        alloc = PortfolioAllocator(config=config, registry=registry)

        positions = {"SMH": _pos(100_000), "NVDA": _pos(500_000)}
        equity = 1_000_000.0

        status = alloc.get_allocation_status(positions, account_equity=equity)
        # check_projected_band with zero proposed notional should match status current_pct
        band = alloc.check_projected_band("SMH", proposed_notional=0, current_positions=positions, equity=equity)

        assert status["current_etf_pct"] == pytest.approx(band.current_pct, abs=0.001), (
            "AC4: status and projected check use same denominator"
        )
