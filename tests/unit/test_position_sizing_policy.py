import pytest

from stock_swing.risk.position_sizing import (
    DEFAULT_MAX_POSITION_NOTIONAL_PCT,
    DEFAULT_MAX_SECTOR_EXPOSURE_PCT,
    ETF_POSITION_SIZE_MULTIPLIER,
    JP_TRADING_UNIT,
    STOCK_POSITION_SIZE_MULTIPLIER,
    PositionSizingInputs,
    PositionSizingPolicy,
    effective_position_notional_pct,
    is_jp_symbol,
    round_to_jp_trading_unit,
)


def test_effective_position_notional_pct_uses_tighter_cap_for_etfs():
    stock_pct = effective_position_notional_pct('AVGO')
    etf_pct = effective_position_notional_pct('SOXX')

    assert stock_pct == pytest.approx(
        DEFAULT_MAX_POSITION_NOTIONAL_PCT * STOCK_POSITION_SIZE_MULTIPLIER
    )
    assert etf_pct == pytest.approx(DEFAULT_MAX_POSITION_NOTIONAL_PCT * ETF_POSITION_SIZE_MULTIPLIER)
    assert stock_pct < etf_pct


def test_position_sizing_defaults_reflect_tightened_risk_caps():
    inputs = PositionSizingInputs(
        account_equity=1_000_000,
        current_price=100,
        current_total_exposure=0,
        symbol='AVGO',
    )

    assert inputs.max_position_notional_pct == DEFAULT_MAX_POSITION_NOTIONAL_PCT
    assert inputs.max_sector_exposure_pct == DEFAULT_MAX_SECTOR_EXPOSURE_PCT


def test_position_sizing_applies_asset_class_multipliers():
    policy = PositionSizingPolicy()

    stock_result = policy.size(PositionSizingInputs(
        account_equity=1_000_000,
        current_price=100,
        current_total_exposure=0,
        symbol='AVGO',
        risk_per_share=1,
        confidence=0.7,
    ))
    etf_result = policy.size(PositionSizingInputs(
        account_equity=1_000_000,
        current_price=100,
        current_total_exposure=0,
        symbol='SOXX',
        risk_per_share=1,
        confidence=0.7,
    ))

    # 2026-07-30: DEFAULT_MAX_POSITION_NOTIONAL_PCT 0.06 → 0.08 (有効上限 80K対応)
    # legacy path: stock = 0.08 * STOCK_MULTIPLIER(0.5) * 1M = 40K
    #              etf   = 0.08 * ETF_MULTIPLIER(0.70) * 1M = 56K
    assert stock_result.max_position_notional_usd == 40000.0
    assert etf_result.max_position_notional_usd == 56000.0
    assert etf_result.shares_by_notional == 560
    assert stock_result.shares_by_notional == 400
    assert stock_result.final_shares <= etf_result.final_shares


# ===========================================================================
# JP trading unit (単元株) rounding — 2026-08-19, JP semiconductor/AI
# expansion Phase 2 (docs/jp_semiconductor_ai_expansion_phase2_design.md
# section 3-C). See also src/stock_swing/utils/jpx_market_calendar.py and
# src/stock_swing/risk/entry_filter.py's purchase_restricted_symbols for the
# other Phase 2 additions from the same roadmap.
# ===========================================================================

class TestIsJpSymbol:
    def test_dot_t_suffix_is_jp_symbol(self):
        assert is_jp_symbol("8035.T") is True
        assert is_jp_symbol("8035.t") is True  # case-insensitive

    def test_us_symbols_are_not_jp(self):
        assert is_jp_symbol("AVGO") is False
        assert is_jp_symbol("NVDA") is False

    def test_none_or_empty_is_not_jp(self):
        assert is_jp_symbol(None) is False
        assert is_jp_symbol("") is False


class TestRoundToJpTradingUnit:
    def test_rounds_down_to_nearest_100(self):
        assert round_to_jp_trading_unit(250) == 200
        assert round_to_jp_trading_unit(399) == 300

    def test_exact_multiple_unchanged(self):
        assert round_to_jp_trading_unit(500) == 500

    def test_below_one_unit_rounds_to_zero(self):
        """Boundary: fewer than JP_TRADING_UNIT shares cannot be bought at
        all under standard JPX round-lot rules."""
        assert round_to_jp_trading_unit(99) == 0

    def test_zero_or_negative_returns_zero(self):
        assert round_to_jp_trading_unit(0) == 0
        assert round_to_jp_trading_unit(-50) == 0

    def test_custom_unit_size(self):
        assert round_to_jp_trading_unit(1250, unit=1000) == 1000

    def test_default_unit_is_100(self):
        assert JP_TRADING_UNIT == 100


class TestPositionSizingPolicyAppliesJpRounding:
    """Acceptance: PositionSizingPolicy.size() must round final_shares down
    to the nearest JP trading unit for ".T"-suffixed symbols, and must be a
    strict no-op for every US symbol (regression guard for existing
    behavior).
    """

    def test_jp_symbol_final_shares_is_multiple_of_100(self):
        policy = PositionSizingPolicy()
        result = policy.size(PositionSizingInputs(
            account_equity=1_000_000,
            current_price=100,
            current_total_exposure=0,
            symbol="8035.T",  # Tokyo Electron
            risk_per_share=1,
        ))

        assert result.final_shares % JP_TRADING_UNIT == 0

    def test_us_symbol_final_shares_unaffected_by_jp_rounding(self):
        """Regression guard: a US symbol whose computed final_shares is NOT
        a multiple of 100 must be left untouched (no accidental rounding
        applied to non-JP symbols).
        """
        policy = PositionSizingPolicy()
        result = policy.size(PositionSizingInputs(
            account_equity=1_000_000,
            current_price=137,  # deliberately awkward price to avoid a
                                  # coincidental multiple of 100
            current_total_exposure=0,
            symbol="AVGO",
            risk_per_share=1,
        ))

        # Sanity: this test is only meaningful if the raw (pre-JP-rounding)
        # result is NOT already a multiple of 100.
        assert result.final_shares % JP_TRADING_UNIT != 0

    def test_jp_symbol_small_allocation_rounds_to_zero_with_skip_reason(self):
        """Boundary: if a JP symbol's raw sizing produces fewer than one
        trading unit (100) after JP-lot rounding — even though
        shares_by_risk/notional/exposure were all individually >= 1 —
        final_shares must become 0 and skip_reason must reflect it, rather
        than silently submitting an invalid odd-lot order.
        """
        policy = PositionSizingPolicy()
        result = policy.size(PositionSizingInputs(
            account_equity=1_000_000,
            current_price=800,
            current_total_exposure=0,
            symbol="6857.T",  # Advantest (risk_per_share=1000 -> shares_by_risk=5,
                               # well under 100, but still >= 1 on its own)
            risk_per_share=1000,
        ))

        assert result.shares_by_risk >= 1  # sanity: not blocked by an earlier gate
        assert result.final_shares == 0
        assert result.skip_reason == "final_shares_below_1"
