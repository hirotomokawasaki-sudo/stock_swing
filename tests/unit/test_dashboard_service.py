from datetime import datetime, timedelta, timezone

from console.services.dashboard_service import DashboardService


def _make_trade(symbol: str, hours_ago: float) -> dict:
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return {
        "symbol": symbol,
        "status": "closed",
        "entry_time": ts,
        "exit_time": ts,
        "qty": 1,
        "entry_price": 100.0,
        "exit_price": 101.0,
        "pnl": 1.0,
        "return_pct": 0.01,
    }


def test_select_recent_closed_trades_prefers_last_48_hours():
    trades = [_make_trade(f"RECENT{i}", i % 24) for i in range(60)]
    trades += [_make_trade(f"OLD{i}", 72 + i) for i in range(10)]

    selected = DashboardService._select_recent_closed_trades(trades)

    assert len(selected) == 60
    assert all(t["symbol"].startswith("RECENT") for t in selected)


def test_select_recent_closed_trades_falls_back_to_minimum_count():
    trades = [_make_trade(f"RECENT{i}", i % 12) for i in range(5)]
    trades += [_make_trade(f"OLD{i}", 72 + i) for i in range(60)]

    selected = DashboardService._select_recent_closed_trades(trades)

    assert len(selected) == DashboardService.RECENT_TRADES_MIN_COUNT
    assert sum(1 for t in selected if t["symbol"].startswith("RECENT")) == 5
