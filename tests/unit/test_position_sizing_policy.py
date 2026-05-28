import pytest

from stock_swing.risk.position_sizing import (
    DEFAULT_MAX_POSITION_NOTIONAL_PCT,
    DEFAULT_MAX_SECTOR_EXPOSURE_PCT,
    ETF_POSITION_SIZE_MULTIPLIER,
    PositionSizingInputs,
    PositionSizingPolicy,
    effective_position_notional_pct,
)


def test_effective_position_notional_pct_uses_tighter_cap_for_etfs():
    stock_pct = effective_position_notional_pct('AVGO')
    etf_pct = effective_position_notional_pct('SOXX')

    assert stock_pct == DEFAULT_MAX_POSITION_NOTIONAL_PCT
    assert etf_pct == pytest.approx(DEFAULT_MAX_POSITION_NOTIONAL_PCT * ETF_POSITION_SIZE_MULTIPLIER)
    assert etf_pct < stock_pct


def test_position_sizing_defaults_reflect_tightened_risk_caps():
    inputs = PositionSizingInputs(
        account_equity=1_000_000,
        current_price=100,
        current_total_exposure=0,
        symbol='AVGO',
    )

    assert inputs.max_position_notional_pct == DEFAULT_MAX_POSITION_NOTIONAL_PCT
    assert inputs.max_sector_exposure_pct == DEFAULT_MAX_SECTOR_EXPOSURE_PCT


def test_position_sizing_applies_smaller_notional_cap_to_etfs():
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

    assert stock_result.max_position_notional_usd == 60000.0
    # P0: ETF_POSITION_SIZE_MULTIPLIER reduced 0.70 -> 0.35 (ETF PF was 0.168)
    assert etf_result.max_position_notional_usd == 21000.0
    assert etf_result.shares_by_notional == 210
    assert stock_result.shares_by_notional == 600
    assert etf_result.final_shares <= stock_result.final_shares
