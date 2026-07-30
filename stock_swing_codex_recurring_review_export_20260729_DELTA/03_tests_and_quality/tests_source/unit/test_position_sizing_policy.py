import pytest

from stock_swing.risk.position_sizing import (
    DEFAULT_MAX_POSITION_NOTIONAL_PCT,
    DEFAULT_MAX_SECTOR_EXPOSURE_PCT,
    ETF_POSITION_SIZE_MULTIPLIER,
    STOCK_POSITION_SIZE_MULTIPLIER,
    PositionSizingInputs,
    PositionSizingPolicy,
    effective_position_notional_pct,
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

    assert stock_result.max_position_notional_usd == 30000.0
    assert etf_result.max_position_notional_usd == 42000.0
    assert etf_result.shares_by_notional == 420
    assert stock_result.shares_by_notional == 300
    assert stock_result.final_shares <= etf_result.final_shares
