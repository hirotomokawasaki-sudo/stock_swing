from pathlib import Path
from unittest.mock import patch

from scripts.fix_stale_broker_prices import build_overrides, main


class FakeEnvelope:
    def __init__(self, payload):
        self.payload = payload


class FakeBroker:
    def __init__(self, positions):
        self.positions = positions

    def fetch_positions(self):
        return FakeEnvelope(self.positions)


class FakeMassive:
    def __init__(self, closes=None, failures=None):
        self.closes = closes or {}
        self.failures = failures or set()

    def fetch_daily_bars(self, symbol, from_date, to_date, limit=7):
        if symbol in self.failures:
            raise RuntimeError(f"boom:{symbol}")
        close = self.closes.get(symbol)
        if close is None:
            return []
        from stock_swing.sources.massive_client import MassiveBar
        from datetime import datetime
        return [
            MassiveBar(
                timestamp=datetime.fromisoformat("2026-05-21T13:00:00"),
                open=close - 1,
                high=close + 1,
                low=close - 2,
                close=close,
                volume=100,
            )
        ]


def test_build_overrides_detects_stale_symbols():
    broker = FakeBroker([
        {"symbol": "CHPX", "current_price": "56.4"},
        {"symbol": "QTEC", "current_price": "259.55"},
        {"symbol": "OK", "current_price": "100.0"},
    ])
    massive = FakeMassive({"CHPX": 93.07, "QTEC": 299.49, "OK": 102.0})

    overrides, logs, errors = build_overrides(
        broker=broker,
        massive=massive,
        min_deviation_pct=5.0,
        previous_overrides={},
    )

    assert set(overrides) == {"CHPX", "QTEC"}
    assert errors == []
    assert any("CHPX" in line for line in logs)


def test_build_overrides_preserves_previous_on_fetch_failure():
    broker = FakeBroker([
        {"symbol": "CHPX", "current_price": "56.4"},
    ])
    massive = FakeMassive(failures={"CHPX"})
    prev = {"CHPX": {"fresh_price": 90.0, "source": "previous"}}

    overrides, logs, errors = build_overrides(
        broker=broker,
        massive=massive,
        min_deviation_pct=5.0,
        previous_overrides=prev,
    )

    assert overrides["CHPX"]["fresh_price"] == 90.0
    assert len(errors) == 1
    assert "preserved previous override" in logs[0]


def test_main_dry_run_does_not_write(tmp_path: Path):
    output_path = tmp_path / "data" / "price_overrides.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text('{"overrides": {"OLD": {"fresh_price": 1}}}', encoding="utf-8")

    with patch("scripts.fix_stale_broker_prices.PROJECT_ROOT", tmp_path), \
         patch("scripts.fix_stale_broker_prices.load_env"), \
         patch("scripts.fix_stale_broker_prices.BrokerClient", return_value=FakeBroker([{"symbol": "CHPX", "current_price": "56.4"}])), \
         patch("scripts.fix_stale_broker_prices.MassiveClient", return_value=FakeMassive({"CHPX": 93.07})), \
         patch("sys.argv", ["fix_stale_broker_prices.py", "--dry-run"]):
        rc = main()

    assert rc == 0
    assert 'OLD' in output_path.read_text(encoding="utf-8")


def test_main_first_empty_run_preserves_previous_overrides(tmp_path: Path):
    output_path = tmp_path / "data" / "price_overrides.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text('{"overrides": {"CHPX": {"fresh_price": 93.07}}}', encoding="utf-8")

    with patch("scripts.fix_stale_broker_prices.PROJECT_ROOT", tmp_path), \
         patch("scripts.fix_stale_broker_prices.load_env"), \
         patch("scripts.fix_stale_broker_prices.BrokerClient", return_value=FakeBroker([{"symbol": "CHPX", "current_price": "93.0"}])), \
         patch("scripts.fix_stale_broker_prices.MassiveClient", return_value=FakeMassive({"CHPX": 93.07})), \
         patch("sys.argv", ["fix_stale_broker_prices.py"]):
        rc = main()

    assert rc == 0
    payload = output_path.read_text(encoding="utf-8")
    assert '"clear_pending": true' in payload
    assert '"CHPX"' in payload
