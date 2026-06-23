from scripts.backfill_daily_snapshots import build_daily_snapshot, build_strategy_rows


def test_build_daily_snapshot_reconstructs_equity_for_date():
    trades = [
        {
            "symbol": "AAA",
            "qty": 10,
            "entry_price": 100.0,
            "entry_time": "2026-06-10T10:00:00+00:00",
            "exit_time": None,
            "status": "open",
            "pnl": None,
        },
        {
            "symbol": "BBB",
            "qty": 5,
            "entry_price": 50.0,
            "entry_time": "2026-06-09T10:00:00+00:00",
            "exit_time": "2026-06-16T15:00:00+00:00",
            "status": "closed",
            "pnl": 25.0,
        },
    ]
    price_map = {"AAA": {"2026-06-16": 110.0}}
    snapshot, current_prices = build_daily_snapshot(trades, "2026-06-16", 1000.0, price_map)
    assert current_prices == {"AAA": 110.0}
    assert snapshot["realized_pnl"] == 25.0
    assert snapshot["unrealized_pnl"] == 100.0
    assert snapshot["equity"] == 1125.0


def test_build_strategy_rows_uses_prior_row_for_equity_index():
    trades = [
        {
            "symbol": "AAA",
            "qty": 10,
            "entry_price": 100.0,
            "entry_time": "2026-06-10T10:00:00+00:00",
            "exit_time": None,
            "status": "open",
            "strategy_version_id": "strat-a",
        }
    ]
    prior_rows = [
        {
            "date": "2026-06-15",
            "strategy_version_id": "strat-a",
            "equity_index": 100.0,
            "unrealized_pnl": 0.0,
            "gross_exposure": 1000.0,
        }
    ]
    rows = build_strategy_rows(
        trades,
        "2026-06-16",
        current_prices={"AAA": 110.0},
        prior_rows=prior_rows,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["strategy_version_id"] == "strat-a"
    assert row["unrealized_pnl"] == 100.0
    assert row["equity_index"] == 109.0909
