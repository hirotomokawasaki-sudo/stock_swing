from stock_swing.cli import daily_report


def test_next_report_schedule_text_for_saturday_jst() -> None:
    text = daily_report._next_report_schedule_text(today_utc=daily_report.date(2026, 5, 15))
    assert text == "次回レポート予定: 2026-05-16 09:00 JST"


def test_next_report_schedule_text_for_sunday_jst_rolls_to_tuesday() -> None:
    text = daily_report._next_report_schedule_text(today_utc=daily_report.date(2026, 5, 16))
    assert text == "次回レポート予定: 2026-05-19 09:00 JST"


def test_build_report_uses_japanese_mode_labels_and_new_footer(monkeypatch) -> None:
    monkeypatch.setattr(daily_report, "_next_report_schedule_text", lambda: "次回レポート予定: 2026-05-16 09:00 JST")

    lines = daily_report._build_report(
        today="2026-05-15",
        runtime_mode="paper",
        account_status="ACTIVE",
        equity=1_000_000.0,
        buying_power=250_000.0,
        summary={
            "cumulative_realized_pnl": -4710.27,
            "closed_trades": 67,
            "winning_trades": 35,
            "losing_trades": 31,
            "win_rate": 0.5224,
            "avg_return_per_trade": 0.0027,
            "avg_pnl_per_trade": -70.3,
            "max_drawdown_pct": 0.0017,
            "trading_days": 1,
        },
        unrealized_pnl=-1516.60,
        total_pnl=-6226.87,
        open_pos=[],
        recent=[],
        current_prices={},
        latest_sizing=[],
        account_summaries=None,
        positions_source="broker",
    )

    assert "🕒  集計時刻:" in lines[2]
    assert "💰 口座情報 (ペーパー)" in lines
    assert "次回レポート予定: 2026-05-16 09:00 JST" == lines[-1]
    assert all("22:30" not in line for line in lines)
