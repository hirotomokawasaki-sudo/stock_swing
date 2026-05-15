from stock_swing.cli import daily_report
from stock_swing.reporting.performance_snapshot import PerformanceSnapshot


def test_next_report_schedule_text_for_saturday_jst() -> None:
    text = daily_report._next_report_schedule_text(today_utc=daily_report.date(2026, 5, 15))
    assert text == "次回レポート予定: 2026-05-16 09:00 JST"


def test_next_report_schedule_text_for_sunday_jst_rolls_to_tuesday() -> None:
    text = daily_report._next_report_schedule_text(today_utc=daily_report.date(2026, 5, 16))
    assert text == "次回レポート予定: 2026-05-19 09:00 JST"


def test_build_report_uses_japanese_mode_labels_and_new_footer(monkeypatch) -> None:
    monkeypatch.setattr(daily_report, "_next_report_schedule_text", lambda: "次回レポート予定: 2026-05-16 09:00 JST")

    snapshot = PerformanceSnapshot(
        equity=1_000_000.0,
        buying_power=250_000.0,
        account_status="ACTIVE",
        baseline_equity=1_000_000.0,
        cumulative_realized_pnl=-4710.27,
        unrealized_pnl=-1516.60,
        total_pnl=-6226.87,
        closed_trades=67,
        winning_trades=35,
        losing_trades=31,
        win_rate=0.5224,
        avg_return_per_trade=0.0027,
        avg_pnl_per_trade=-70.3,
        max_drawdown_pct=0.0017,
        trading_days=1,
        open_positions=[],
        positions_source="broker",
        current_prices={},
        recent_trades=[],
        tracking_context={},
        alerts=[],
    )

    lines = daily_report._build_report(
        today="2026-05-15",
        runtime_mode="paper",
        snapshot=snapshot,
        latest_sizing=[],
        account_summaries=None,
    )

    assert "🕒  集計時刻:" in lines[2]
    assert "💰 口座情報 (ペーパー)" in lines
    assert "次回レポート予定: 2026-05-16 09:00 JST" == lines[-1]
    assert all("22:30" not in line for line in lines)


def test_build_report_brief_mode_omits_sizing_details() -> None:
    snapshot = PerformanceSnapshot(
        equity=1_000_000.0,
        buying_power=250_000.0,
        account_status="ACTIVE",
        baseline_equity=1_000_000.0,
        cumulative_realized_pnl=-4710.27,
        unrealized_pnl=-1516.60,
        total_pnl=-6226.87,
        closed_trades=67,
        winning_trades=35,
        losing_trades=31,
        win_rate=0.5224,
        avg_return_per_trade=0.0027,
        avg_pnl_per_trade=-70.3,
        max_drawdown_pct=0.0017,
        trading_days=1,
        open_positions=[
            {"symbol": "AMAT", "qty": 158, "entry_price": 421.06},
            {"symbol": "AMZN", "qty": 1, "entry_price": 267.73},
        ],
        positions_source="broker",
        current_prices={},
        recent_trades=[
            {"symbol": "TTEQ", "pnl": 273.36, "return_pct": 0.004},
            {"symbol": "SOXX", "pnl": -254.25, "return_pct": -0.015},
            {"symbol": "PTF", "pnl": 100.0, "return_pct": 0.008},
            {"symbol": "HPE", "pnl": 50.0, "return_pct": 0.003},
        ],
        tracking_context={},
        alerts=[],
    )

    lines = daily_report._build_report(
        today="2026-05-15",
        runtime_mode="paper",
        snapshot=snapshot,
        latest_sizing=[
            {"symbol": "CHPX", "sizing": {"final_shares": 0}},
        ],
        account_summaries=None,
        mode="brief",
    )

    report = "\n".join(lines)

    # Brief mode should omit sizing section entirely
    assert "📏 最新のポジションサイズ根拠" not in report

    # Brief mode should show only symbols for positions, no details
    assert "AMAT, AMZN" in report
    assert "取得=$" not in report
    assert "現在=$" not in report

    # Brief mode should limit recent trades to 3
    assert report.count("✅") + report.count("❌") == 3

    # Brief mode should show simplified performance
    assert "決済取引数" in report
    assert "勝率" in report
    assert "平均リターン" not in report  # excluded in brief
    assert "最大DD" not in report  # excluded in brief


def test_build_report_full_mode_includes_all_sections() -> None:
    snapshot = PerformanceSnapshot(
        equity=1_000_000.0,
        buying_power=250_000.0,
        account_status="ACTIVE",
        baseline_equity=1_000_000.0,
        cumulative_realized_pnl=-4710.27,
        unrealized_pnl=-1516.60,
        total_pnl=-6226.87,
        closed_trades=67,
        winning_trades=35,
        losing_trades=31,
        win_rate=0.5224,
        avg_return_per_trade=0.0027,
        avg_pnl_per_trade=-70.3,
        max_drawdown_pct=0.0017,
        trading_days=1,
        open_positions=[
            {"symbol": "AMAT", "qty": 158, "entry_price": 421.06, "current_price": 425.99},
        ],
        positions_source="broker",
        current_prices={"AMAT": 425.99},
        recent_trades=[
            {"symbol": "TTEQ", "pnl": 273.36, "return_pct": 0.004},
        ],
        tracking_context={},
        alerts=[],
    )

    lines = daily_report._build_report(
        today="2026-05-15",
        runtime_mode="paper",
        snapshot=snapshot,
        latest_sizing=[
            {"symbol": "CHPX", "sizing": {"final_shares": 0}},
        ],
        account_summaries=None,
        mode="full",
    )

    report = "\n".join(lines)

    # Full mode should include sizing section
    assert "📏 最新のポジションサイズ根拠" in report

    # Full mode should show position details
    assert "取得=$" in report
    assert "現在=$" in report
    assert "含損益=" in report

    # Full mode should show full performance
    assert "平均リターン" in report
    assert "最大DD" in report



def test_build_report_includes_alerts() -> None:
    """Test that alerts appear in report."""
    snapshot = PerformanceSnapshot(
        equity=1_000_000.0,
        buying_power=250_000.0,
        account_status="ACTIVE",
        baseline_equity=1_000_000.0,
        cumulative_realized_pnl=-4710.27,
        unrealized_pnl=-6000.0,
        total_pnl=-10710.27,
        closed_trades=67,
        winning_trades=35,
        losing_trades=31,
        win_rate=0.5224,
        avg_return_per_trade=0.0027,
        avg_pnl_per_trade=-70.3,
        max_drawdown_pct=0.0017,
        trading_days=1,
        open_positions=[],
        positions_source="broker",
        current_prices={},
        recent_trades=[],
        tracking_context={},
        alerts=[
            {"level": "warning", "type": "unrealized_pnl", "message": "含み損益が -6,000.00 USD に達しています"},
            {"level": "warning", "type": "total_pnl_pct", "message": "合計損益が baseline から -10.71% に達しています"},
        ],
    )

    lines = daily_report._build_report(
        today="2026-05-15",
        runtime_mode="paper",
        snapshot=snapshot,
        latest_sizing=[],
        account_summaries=None,
        mode="full",
    )

    report = "\n".join(lines)
    assert "⚠️  アラート" in report
    assert "含み損益が" in report
    assert "合計損益が" in report
