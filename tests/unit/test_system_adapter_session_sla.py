"""R7-v2-A (2026-08-14): per-source-type session SLA tests.

Covers the three previously-unimplemented SLA checks from
docs/console_improvement_tasks.md R7-v2:
  - intraday quote: market open中 <=2分
  - daily bar: 前営業日 close確定後
  - sector benchmark: exit判断時点と同as-of

Exercised via SystemAdapter._evaluate_intraday_quote_sla(),
_evaluate_daily_bar_sla(), and _evaluate_sector_benchmark_sla().
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from console.adapters.system_adapter import SystemAdapter, _SECTOR_BENCHMARK_SYMBOLS


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# intraday_quote SLA
# ---------------------------------------------------------------------------

class TestIntradayQuoteSla:
    def test_not_applicable_when_market_closed(self, tmp_path):
        adapter = SystemAdapter(tmp_path)
        with patch("console.adapters.system_adapter.MarketCalendar") as mc:
            mc.is_market_open.return_value = (False, "Market closed: Weekend")
            result = adapter._evaluate_intraday_quote_sla()
        assert result["ok"] is True
        assert result["applicable"] is False
        assert result["reason"] == "market_closed"

    def test_fresh_quote_ok_when_market_open(self, tmp_path):
        status_path = tmp_path / "data" / "audits" / "broker_quotes_status.json"
        _write_json(status_path, {
            "time": datetime.now(timezone.utc).isoformat(),
            "status": "ok",
        })
        adapter = SystemAdapter(tmp_path)
        with patch("console.adapters.system_adapter.MarketCalendar") as mc:
            mc.is_market_open.return_value = (True, "Market open: Regular hours")
            result = adapter._evaluate_intraday_quote_sla()
        assert result["ok"] is True
        assert result["applicable"] is True
        assert result["stale"] is False

    def test_stale_quote_fails_when_market_open(self, tmp_path):
        status_path = tmp_path / "data" / "audits" / "broker_quotes_status.json"
        old_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        _write_json(status_path, {"time": old_time, "status": "ok"})
        adapter = SystemAdapter(tmp_path)
        with patch("console.adapters.system_adapter.MarketCalendar") as mc:
            mc.is_market_open.return_value = (True, "Market open: Regular hours")
            result = adapter._evaluate_intraday_quote_sla()
        assert result["ok"] is False
        assert result["stale"] is True

    def test_missing_status_fails_when_market_open(self, tmp_path):
        adapter = SystemAdapter(tmp_path)
        with patch("console.adapters.system_adapter.MarketCalendar") as mc:
            mc.is_market_open.return_value = (True, "Market open: Regular hours")
            result = adapter._evaluate_intraday_quote_sla()
        assert result["ok"] is False
        assert result["reason"] == "missing_status"

    def test_corrupt_status_json_does_not_crash(self, tmp_path):
        status_path = tmp_path / "data" / "audits" / "broker_quotes_status.json"
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text("{not valid json", encoding="utf-8")
        adapter = SystemAdapter(tmp_path)
        with patch("console.adapters.system_adapter.MarketCalendar") as mc:
            mc.is_market_open.return_value = (True, "Market open: Regular hours")
            result = adapter._evaluate_intraday_quote_sla()
        assert result["ok"] is False
        assert "error" in result

    def test_boundary_exactly_at_sla_seconds_is_stale(self, tmp_path):
        """age == sla_seconds should be treated as stale (strict >)."""
        status_path = tmp_path / "data" / "audits" / "broker_quotes_status.json"
        old_time = (datetime.now(timezone.utc) - timedelta(seconds=121)).isoformat()
        _write_json(status_path, {"time": old_time, "status": "ok"})
        adapter = SystemAdapter(tmp_path)
        with patch("console.adapters.system_adapter.MarketCalendar") as mc:
            mc.is_market_open.return_value = (True, "Market open: Regular hours")
            result = adapter._evaluate_intraday_quote_sla()
        assert result["stale"] is True


# ---------------------------------------------------------------------------
# daily_bar SLA
# ---------------------------------------------------------------------------

class TestDailyBarSla:
    def test_fresh_snapshot_ok(self, tmp_path):
        status_path = tmp_path / "data" / "audits" / "broker_bars_status.json"
        _write_json(status_path, {
            "time": datetime.now(timezone.utc).isoformat(),
            "status": "ok",
        })
        adapter = SystemAdapter(tmp_path)
        with patch("console.adapters.system_adapter.MarketCalendar") as mc:
            mc.previous_trading_close_utc.return_value = datetime.now(timezone.utc) - timedelta(hours=2)
            result = adapter._evaluate_daily_bar_sla()
        assert result["ok"] is True
        assert result["applicable"] is True

    def test_missing_status_fails(self, tmp_path):
        adapter = SystemAdapter(tmp_path)
        with patch("console.adapters.system_adapter.MarketCalendar") as mc:
            mc.previous_trading_close_utc.return_value = datetime.now(timezone.utc)
            result = adapter._evaluate_daily_bar_sla()
        assert result["ok"] is False
        assert result["reason"] == "missing_status"

    def test_snapshot_older_than_last_close_plus_slack_is_stale(self, tmp_path):
        status_path = tmp_path / "data" / "audits" / "broker_bars_status.json"
        very_old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        _write_json(status_path, {"time": very_old, "status": "ok"})
        adapter = SystemAdapter(tmp_path)
        with patch("console.adapters.system_adapter.MarketCalendar") as mc:
            mc.previous_trading_close_utc.return_value = datetime.now(timezone.utc) - timedelta(hours=2)
            result = adapter._evaluate_daily_bar_sla()
        assert result["ok"] is False
        assert result["stale"] is True

    def test_corrupt_json_does_not_crash(self, tmp_path):
        status_path = tmp_path / "data" / "audits" / "broker_bars_status.json"
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text("not json", encoding="utf-8")
        adapter = SystemAdapter(tmp_path)
        with patch("console.adapters.system_adapter.MarketCalendar") as mc:
            mc.previous_trading_close_utc.return_value = datetime.now(timezone.utc)
            result = adapter._evaluate_daily_bar_sla()
        assert result["ok"] is False
        assert "error" in result


# ---------------------------------------------------------------------------
# sector_benchmark SLA
# ---------------------------------------------------------------------------

class TestSectorBenchmarkSla:
    def _write_benchmark(self, tmp_path, symbol, latest_date):
        path = tmp_path / "data" / "benchmarks" / f"{symbol}_daily.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([{"date": latest_date, "close": 100.0}]), encoding="utf-8")

    def test_all_symbols_fresh_ok(self, tmp_path):
        expected_close = datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc)  # 16:00 ET
        for symbol in _SECTOR_BENCHMARK_SYMBOLS:
            self._write_benchmark(tmp_path, symbol, "2026-07-21")
        adapter = SystemAdapter(tmp_path)
        with patch("console.adapters.system_adapter.MarketCalendar") as mc:
            mc.previous_trading_close_utc.return_value = expected_close
            result = adapter._evaluate_sector_benchmark_sla()
        assert result["ok"] is True
        assert result["stale_symbols"] == []

    def test_one_stale_symbol_fails(self, tmp_path):
        expected_close = datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc)
        for symbol in _SECTOR_BENCHMARK_SYMBOLS:
            self._write_benchmark(tmp_path, symbol, "2026-07-21")
        # SPY is stale (older date)
        self._write_benchmark(tmp_path, "SPY", "2026-07-17")
        adapter = SystemAdapter(tmp_path)
        with patch("console.adapters.system_adapter.MarketCalendar") as mc:
            mc.previous_trading_close_utc.return_value = expected_close
            result = adapter._evaluate_sector_benchmark_sla()
        assert result["ok"] is False
        assert "SPY" in result["stale_symbols"]

    def test_missing_file_counts_as_stale(self, tmp_path):
        expected_close = datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc)
        # Only write 4 of 5 symbols
        for symbol in _SECTOR_BENCHMARK_SYMBOLS[:-1]:
            self._write_benchmark(tmp_path, symbol, "2026-07-21")
        adapter = SystemAdapter(tmp_path)
        with patch("console.adapters.system_adapter.MarketCalendar") as mc:
            mc.previous_trading_close_utc.return_value = expected_close
            result = adapter._evaluate_sector_benchmark_sla()
        assert result["ok"] is False
        missing_symbol = _SECTOR_BENCHMARK_SYMBOLS[-1]
        assert missing_symbol in result["stale_symbols"]

    def test_corrupt_benchmark_file_counts_as_stale_not_crash(self, tmp_path):
        expected_close = datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc)
        for symbol in _SECTOR_BENCHMARK_SYMBOLS:
            self._write_benchmark(tmp_path, symbol, "2026-07-21")
        bad_path = tmp_path / "data" / "benchmarks" / f"{_SECTOR_BENCHMARK_SYMBOLS[0]}_daily.json"
        bad_path.write_text("not json", encoding="utf-8")
        adapter = SystemAdapter(tmp_path)
        with patch("console.adapters.system_adapter.MarketCalendar") as mc:
            mc.previous_trading_close_utc.return_value = expected_close
            result = adapter._evaluate_sector_benchmark_sla()
        assert result["ok"] is False
        assert _SECTOR_BENCHMARK_SYMBOLS[0] in result["stale_symbols"]

    def test_newer_than_expected_date_still_ok(self, tmp_path):
        """A benchmark file newer than the expected close date must still pass."""
        expected_close = datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc)
        for symbol in _SECTOR_BENCHMARK_SYMBOLS:
            self._write_benchmark(tmp_path, symbol, "2026-07-22")  # newer
        adapter = SystemAdapter(tmp_path)
        with patch("console.adapters.system_adapter.MarketCalendar") as mc:
            mc.previous_trading_close_utc.return_value = expected_close
            result = adapter._evaluate_sector_benchmark_sla()
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# _check_source_sla wiring (session_sla key present, doesn't break required gate)
# ---------------------------------------------------------------------------

class TestCheckSourceSlaWiring:
    def test_session_sla_key_present_and_does_not_affect_required_ok(self, tmp_path):
        """session_sla is informational; a failing session_sla entry must not
        flip the top-level required-source ok/failing_sources result."""
        sources_dir = tmp_path / "config" / "sources"
        sources_dir.mkdir(parents=True, exist_ok=True)
        (sources_dir / "finnhub.yaml").write_text("required: true\n", encoding="utf-8")
        _write_json(
            tmp_path / "data" / "audits" / "news_collection_status.json",
            {
                "time": datetime.now(timezone.utc).isoformat(),
                "timed_out": False,
                "symbols": [{"symbol": "AAPL", "news_count": 1, "reason": "ok"}],
            },
        )
        adapter = SystemAdapter(tmp_path)
        with patch("console.adapters.system_adapter.MarketCalendar") as mc:
            mc.is_market_open.return_value = (False, "Market closed: Weekend")
            mc.previous_trading_close_utc.return_value = datetime.now(timezone.utc) - timedelta(days=5)
            result = adapter._check_source_sla()
        assert "session_sla" in result
        assert set(result["session_sla"].keys()) == {"intraday_quote", "daily_bar", "sector_benchmark"}
        # required-source gate is independent of session_sla ok/fail state
        assert result["ok"] is True
        assert result["failing_sources"] == []
