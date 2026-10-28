from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from stock_swing.sources.massive_client import MassiveBar
from stock_swing.tracking.pnl_tracker import PnLTracker

from scripts.backfill_open_trade_peak_prices import (
    backfill_trade_peak,
    compute_effective_peak_price,
    main,
)


def minute_bar(ts: str, high: float) -> MassiveBar:
    return MassiveBar(
        timestamp=datetime.fromisoformat(ts).replace(tzinfo=UTC),
        open=high - 1,
        high=high,
        low=high - 2,
        close=high - 1,
        volume=100,
    )


def daily_bar(ts: str, high: float) -> MassiveBar:
    return MassiveBar(
        timestamp=datetime.fromisoformat(ts).replace(tzinfo=UTC),
        open=high - 1,
        high=high,
        low=high - 2,
        close=high - 1,
        volume=100,
    )


class FakeClient:
    def __init__(self, minute_map=None, daily_map=None):
        self.minute_map = minute_map or {}
        self.daily_map = daily_map or {}
        self.minute_calls = []
        self.daily_calls = []

    def fetch_minute_bars(self, symbol, from_date, to_date, multiplier=1, limit=50000):
        self.minute_calls.append((symbol, from_date, to_date, multiplier))
        return self.minute_map.get((symbol, from_date, to_date, multiplier), [])

    def fetch_daily_bars(self, symbol, from_date, to_date, limit=5000):
        self.daily_calls.append((symbol, from_date, to_date))
        return self.daily_map.get((symbol, from_date, to_date), [])


def test_compute_effective_peak_price_prefers_highest_component():
    result = compute_effective_peak_price(
        entry_price=100.0,
        prior_peak=103.0,
        entry_day_peak=106.0,
        intermediate_daily_peak=110.0,
        today_intraday_peak=108.0,
    )
    assert result.new_peak == 110.0


def test_backfill_trade_peak_ignores_pre_entry_intraday_bar():
    client = FakeClient(
        minute_map={
            ("AAPL", "2026-05-20", "2026-05-20", 5): [
                minute_bar("2026-05-20T14:00:00", 110.0),
                minute_bar("2026-05-20T14:35:00", 105.0),
                minute_bar("2026-05-20T14:40:00", 108.0),
            ],
            ("AAPL", "2026-05-22", "2026-05-22", 5): [minute_bar("2026-05-22T10:00:00", 107.0)],
        },
        daily_map={
            ("AAPL", "2026-05-21", "2026-05-21"): [daily_bar("2026-05-21T00:00:00", 104.0)]
        },
    )
    trade = {
        "symbol": "AAPL",
        "trade_id": "t1",
        "entry_time": "2026-05-20T14:30:00+00:00",
        "entry_price": 100.0,
        "peak_price": 101.0,
    }

    result = backfill_trade_peak(
        client=client,
        minute_cache={},
        daily_cache={},
        trade=trade,
        now_utc=datetime(2026, 5, 22, 12, 0, tzinfo=UTC),
        minute_multiplier=5,
        use_intraday_entry=True,
        use_intraday_today=True,
    )

    assert result.components.entry_day_peak == 108.0
    assert result.components.intermediate_daily_peak == 104.0
    assert result.components.today_intraday_peak == 107.0
    assert result.new_peak == 108.0


def test_backfill_trade_peak_today_entry_only_uses_post_entry_intraday():
    client = FakeClient(
        minute_map={
            ("AAPL", "2026-05-22", "2026-05-22", 5): [
                minute_bar("2026-05-22T08:00:00", 120.0),
                minute_bar("2026-05-22T09:35:00", 105.0),
                minute_bar("2026-05-22T09:40:00", 107.0),
            ]
        }
    )
    trade = {
        "symbol": "AAPL",
        "trade_id": "t1",
        "entry_time": "2026-05-22T09:30:00+00:00",
        "entry_price": 100.0,
        "peak_price": 100.0,
    }

    result = backfill_trade_peak(
        client=client,
        minute_cache={},
        daily_cache={},
        trade=trade,
        now_utc=datetime(2026, 5, 22, 12, 0, tzinfo=UTC),
        minute_multiplier=5,
        use_intraday_entry=True,
        use_intraday_today=True,
    )

    assert result.components.entry_day_peak == 107.0
    assert result.components.today_intraday_peak is None
    assert result.new_peak == 107.0


def test_backfill_trade_peak_uses_today_intraday_for_older_position():
    client = FakeClient(
        minute_map={
            ("AAPL", "2026-05-20", "2026-05-20", 5): [minute_bar("2026-05-20T14:35:00", 106.0)],
            ("AAPL", "2026-05-22", "2026-05-22", 5): [minute_bar("2026-05-22T10:00:00", 115.0)],
        },
        daily_map={
            ("AAPL", "2026-05-21", "2026-05-21"): [daily_bar("2026-05-21T00:00:00", 112.0)]
        },
    )
    trade = {
        "symbol": "AAPL",
        "trade_id": "t1",
        "entry_time": "2026-05-20T14:30:00+00:00",
        "entry_price": 100.0,
        "peak_price": 101.0,
    }

    result = backfill_trade_peak(
        client=client,
        minute_cache={},
        daily_cache={},
        trade=trade,
        now_utc=datetime(2026, 5, 22, 12, 0, tzinfo=UTC),
        minute_multiplier=5,
        use_intraday_entry=True,
        use_intraday_today=True,
    )

    assert result.new_peak == 115.0


def test_backfill_trade_peak_uses_trade_specific_entry_time_with_cache():
    client = FakeClient(
        minute_map={
            ("AAPL", "2026-05-20", "2026-05-20", 5): [
                minute_bar("2026-05-20T14:10:00", 104.0),
                minute_bar("2026-05-20T14:40:00", 109.0),
            ],
            ("AAPL", "2026-05-22", "2026-05-22", 5): [minute_bar("2026-05-22T10:00:00", 108.0)],
        },
        daily_map={
            ("AAPL", "2026-05-21", "2026-05-21"): [daily_bar("2026-05-21T00:00:00", 107.0)]
        },
    )
    minute_cache = {}
    daily_cache = {}
    trade1 = {
        "symbol": "AAPL",
        "trade_id": "t1",
        "entry_time": "2026-05-20T14:00:00+00:00",
        "entry_price": 100.0,
        "peak_price": 100.0,
    }
    trade2 = {
        "symbol": "AAPL",
        "trade_id": "t2",
        "entry_time": "2026-05-20T14:30:00+00:00",
        "entry_price": 100.0,
        "peak_price": 100.0,
    }

    result1 = backfill_trade_peak(
        client=client,
        minute_cache=minute_cache,
        daily_cache=daily_cache,
        trade=trade1,
        now_utc=datetime(2026, 5, 22, 12, 0, tzinfo=UTC),
        minute_multiplier=5,
        use_intraday_entry=True,
        use_intraday_today=True,
    )
    result2 = backfill_trade_peak(
        client=client,
        minute_cache=minute_cache,
        daily_cache=daily_cache,
        trade=trade2,
        now_utc=datetime(2026, 5, 22, 12, 0, tzinfo=UTC),
        minute_multiplier=5,
        use_intraday_entry=True,
        use_intraday_today=True,
    )

    assert result1.components.entry_day_peak == 109.0
    assert result2.components.entry_day_peak == 109.0
    assert client.minute_calls.count(("AAPL", "2026-05-20", "2026-05-20", 5)) == 1
    assert client.daily_calls.count(("AAPL", "2026-05-21", "2026-05-21")) == 1


def test_main_dry_run_does_not_persist(tmp_path: Path):
    tracker = PnLTracker(tmp_path)
    tracker.record_submission(
        symbol="AAPL",
        strategy_id="test_strategy",
        side="buy",
        qty=10,
        price=100.0,
        broker_order_id="buy-1",
        decision_id="decision-1",
    )
    trade = tracker.get_open_positions()[0]
    trade["entry_time"] = "2026-05-20T14:30:00+00:00"
    trade["peak_price"] = 100.0
    tracker._save_state()

    fake_client = FakeClient(
        minute_map={
            ("AAPL", "2026-05-20", "2026-05-20", 5): [minute_bar("2026-05-20T14:35:00", 106.0)],
            ("AAPL", "2026-05-22", "2026-05-22", 5): [minute_bar("2026-05-22T10:00:00", 107.0)],
        },
        daily_map={
            ("AAPL", "2026-05-21", "2026-05-21"): [daily_bar("2026-05-21T00:00:00", 104.0)]
        },
    )

    with patch("scripts.backfill_open_trade_peak_prices.project_root", tmp_path), patch(
        "scripts.backfill_open_trade_peak_prices.MassiveClient", return_value=fake_client
    ), patch("sys.argv", ["backfill_open_trade_peak_prices.py", "--dry-run", "--as-of", "2026-05-22T12:00:00Z"]):
        rc = main()

    assert rc == 0
    refreshed = PnLTracker(tmp_path).get_open_positions()[0]
    assert refreshed["peak_price"] == 100.0


def test_main_symbols_filter_only_updates_target_symbol(tmp_path: Path):
    tracker = PnLTracker(tmp_path)
    for symbol in ["AAPL", "MSFT"]:
        tracker.record_submission(
            symbol=symbol,
            strategy_id="test_strategy",
            side="buy",
            qty=10,
            price=100.0,
            broker_order_id=f"buy-{symbol}",
            decision_id=f"decision-{symbol}",
        )
    open_trades = tracker.get_open_positions()
    for trade in open_trades:
        trade["entry_time"] = "2026-05-20T14:30:00+00:00"
        trade["peak_price"] = 100.0
    tracker._save_state()

    fake_client = FakeClient(
        minute_map={
            ("AAPL", "2026-05-20", "2026-05-20", 5): [minute_bar("2026-05-20T14:35:00", 106.0)],
            ("AAPL", "2026-05-22", "2026-05-22", 5): [minute_bar("2026-05-22T10:00:00", 107.0)],
        },
        daily_map={
            ("AAPL", "2026-05-21", "2026-05-21"): [daily_bar("2026-05-21T00:00:00", 104.0)]
        },
    )

    with patch("scripts.backfill_open_trade_peak_prices.project_root", tmp_path), patch(
        "scripts.backfill_open_trade_peak_prices.MassiveClient", return_value=fake_client
    ), patch("sys.argv", ["backfill_open_trade_peak_prices.py", "--symbols", "AAPL", "--as-of", "2026-05-22T12:00:00Z"]):
        rc = main()

    assert rc == 0
    refreshed = {t["symbol"]: t for t in PnLTracker(tmp_path).get_open_positions()}
    assert refreshed["AAPL"]["peak_price"] == 107.0
    assert refreshed["MSFT"]["peak_price"] == 100.0


def test_main_as_of_makes_backfill_deterministic(tmp_path: Path):
    tracker = PnLTracker(tmp_path)
    tracker.record_submission(
        symbol="AAPL",
        strategy_id="test_strategy",
        side="buy",
        qty=10,
        price=100.0,
        broker_order_id="buy-AAPL",
        decision_id="decision-AAPL",
    )
    trade = tracker.get_open_positions()[0]
    trade["entry_time"] = "2026-05-20T14:30:00+00:00"
    trade["peak_price"] = 100.0
    tracker._save_state()

    fake_client = FakeClient(
        minute_map={
            ("AAPL", "2026-05-20", "2026-05-20", 5): [minute_bar("2026-05-20T14:35:00", 106.0)],
            ("AAPL", "2026-05-22", "2026-05-22", 5): [minute_bar("2026-05-22T10:00:00", 107.0)],
        }
    )

    with patch("scripts.backfill_open_trade_peak_prices.project_root", tmp_path), patch(
        "scripts.backfill_open_trade_peak_prices.MassiveClient", return_value=fake_client
    ), patch(
        "sys.argv",
        ["backfill_open_trade_peak_prices.py", "--as-of", "2026-05-22T12:00:00Z"],
    ):
        rc = main()

    assert rc == 0
    refreshed = PnLTracker(tmp_path).get_open_positions()[0]
    assert refreshed["peak_price"] == 107.0
