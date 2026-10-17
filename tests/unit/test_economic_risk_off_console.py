"""Layer-propagation tests for economic risk-off observability."""

from stock_swing.reporting.console_renderer import ConsoleRenderer
from stock_swing.reporting.console_summary import ConsoleSummary


_RISK_OFF = {
    "enabled": True,
    "mode": "shadow",
    "enforced": False,
    "status": "block_buys",
    "action": "block_buys",
    "observed_pct": -6.1043,
    "metric_name": "rolling_session_total_loss_pct",
    "lookback_sessions": 5,
    "window_start_date": "2026-10-12",
    "window_end_date": "2026-10-16",
    "data_status": "ready",
    "recovery_sessions": 0,
    "recovery_sessions_required": 2,
}


def _summary() -> ConsoleSummary:
    return ConsoleSummary.build(
        run_id="risk-off-test",
        equity=938_957,
        open_position_count=1,
        guardrail_status="ok",
        market_regime="neutral",
        economic_risk_off=_RISK_OFF,
    )


def test_economic_risk_off_propagates_to_health_contract() -> None:
    health = _summary().to_dict()["health"]
    assert health["economic_risk_off"] == _RISK_OFF


def test_economic_risk_off_renderer_labels_shadow_as_non_enforcing() -> None:
    rendered = ConsoleRenderer().render(_summary())
    assert "ECONOMIC RISK-OFF  BLOCK_BUYS  [SHADOW]" in rendered
    assert "-6.10%" in rendered
    assert "observation only; orders unchanged" in rendered


def test_disabled_economic_risk_off_is_not_rendered() -> None:
    summary = ConsoleSummary.build(
        run_id="risk-off-disabled",
        equity=1_000_000,
        open_position_count=0,
        guardrail_status="ok",
        market_regime="neutral",
        economic_risk_off={"enabled": False},
    )
    assert "ECONOMIC RISK-OFF" not in ConsoleRenderer().render(summary)
