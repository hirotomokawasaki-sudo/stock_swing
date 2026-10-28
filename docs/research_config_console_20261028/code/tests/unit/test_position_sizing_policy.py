import pytest

from stock_swing.risk import position_sizing as position_sizing_module
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
# R13-B confidence_multiplier no-op bug + default-off risk-budget fix
# (2026-08-26 discovery / 2026-08-27 fix, see
# docs/r13b_sizing_confidence_multiplier_fix_validation_20260826/README.md)
# ===========================================================================

def _risk_bound_inputs(confidence: float) -> PositionSizingInputs:
    """A sizing scenario where shares_by_risk is deliberately the tightest
    of the 4 caps (small max_risk_per_trade_pct, large notional/exposure
    room: shares_by_risk=100 vs shares_by_notional=400 at default caps),
    so a confidence-driven change to shares_by_risk is guaranteed to be
    visible in final_shares if (and only if) the fix is active."""
    return PositionSizingInputs(
        account_equity=1_000_000,
        current_price=100,
        current_total_exposure=0,
        symbol='AVGO',  # stock, not ETF -- keeps asset multiplier out of the way conceptually
        risk_per_share=1,
        max_risk_per_trade_pct=0.0001,  # max_loss_usd=100 -> shares_by_risk=100, tightest cap
        confidence=confidence,
    )


def test_confidence_boost_is_noop_by_default(monkeypatch):
    """Documents the ORIGINAL bug: with the fix flag off (default),
    confidence>=0.80 (1.2x) must have ZERO effect on final_shares, even
    when shares_by_risk is deliberately the binding constraint."""
    monkeypatch.setattr(
        position_sizing_module, "SIZING_CONFIDENCE_MULTIPLIER_RISK_BUDGET_FIX_ENABLED", False,
    )
    policy = PositionSizingPolicy()

    # confidence=0.7 is genuinely neutral (>=0.60 and <0.80 -> multiplier=1.0)
    neutral = policy.size(_risk_bound_inputs(confidence=0.7))
    boosted = policy.size(_risk_bound_inputs(confidence=0.90))

    assert boosted.confidence_multiplier == 1.2
    # Bug preserved: boost has no effect when default-off.
    assert boosted.final_shares == neutral.final_shares


def test_confidence_boost_increases_shares_when_fix_enabled(monkeypatch):
    """With the fix flag on, a >=0.80 confidence (1.2x) boost DOES increase
    final_shares when shares_by_risk is the binding constraint."""
    monkeypatch.setattr(
        position_sizing_module, "SIZING_CONFIDENCE_MULTIPLIER_RISK_BUDGET_FIX_ENABLED", True,
    )
    policy = PositionSizingPolicy()

    neutral = policy.size(_risk_bound_inputs(confidence=0.7))
    boosted = policy.size(_risk_bound_inputs(confidence=0.90))

    assert boosted.confidence_multiplier == 1.2
    assert boosted.final_shares > neutral.final_shares
    # Exact expected relationship: shares_by_risk scaled by 1.2, floored.
    from math import floor
    assert boosted.final_shares == min(
        floor(neutral.shares_by_risk * 1.2), boosted.shares_by_notional,
        boosted.shares_by_exposure,
    )


def test_confidence_cut_unaffected_by_fix_flag(monkeypatch):
    """The cut side (confidence<0.60, 0.7x) already worked correctly before
    the fix and must behave IDENTICALLY regardless of the flag (no
    regression to the one part of the mechanism that wasn't broken)."""
    policy = PositionSizingPolicy()

    monkeypatch.setattr(
        position_sizing_module, "SIZING_CONFIDENCE_MULTIPLIER_RISK_BUDGET_FIX_ENABLED", False,
    )
    cut_off = policy.size(_risk_bound_inputs(confidence=0.3))

    monkeypatch.setattr(
        position_sizing_module, "SIZING_CONFIDENCE_MULTIPLIER_RISK_BUDGET_FIX_ENABLED", True,
    )
    cut_on = policy.size(_risk_bound_inputs(confidence=0.3))

    assert cut_off.confidence_multiplier == 0.7
    assert cut_on.confidence_multiplier == 0.7
    assert cut_off.final_shares == cut_on.final_shares


def test_confidence_boost_still_noop_when_notional_is_binding(monkeypatch):
    """When the fix is enabled but risk is NOT the binding constraint
    (notional/exposure/sector already tighter), a boost must still have
    zero effect -- this is correct behavior (independent hard caps must
    not be overridden by confidence), not a regression of the fix."""
    monkeypatch.setattr(
        position_sizing_module, "SIZING_CONFIDENCE_MULTIPLIER_RISK_BUDGET_FIX_ENABLED", True,
    )
    policy = PositionSizingPolicy()

    # Large risk budget (risk is NOT binding) + default notional cap (IS binding).
    notional_bound = lambda confidence: PositionSizingInputs(  # noqa: E731
        account_equity=1_000_000,
        current_price=100,
        current_total_exposure=0,
        symbol='AVGO',
        risk_per_share=1,
        max_risk_per_trade_pct=0.5,  # huge risk budget -> notional cap binds instead
        confidence=confidence,
    )

    neutral = policy.size(notional_bound(0.7))
    boosted = policy.size(notional_bound(0.90))

    assert boosted.confidence_multiplier == 1.2
    assert boosted.final_shares == neutral.final_shares
    assert boosted.final_shares == boosted.shares_by_notional


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
