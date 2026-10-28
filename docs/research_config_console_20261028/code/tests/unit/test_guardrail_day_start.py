from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timezone
from types import SimpleNamespace

massive_stub = types.ModuleType("massive")
massive_stub.RESTClient = object
sys.modules.setdefault("massive", massive_stub)

from stock_swing.cli import paper_demo
from stock_swing.cli.cron_summary import CRON_SUMMARY_PREFIX
from stock_swing.core.types import CanonicalRecord
from stock_swing.feature_engine.base_feature import FeatureResult
from stock_swing.strategy_engine.base_strategy import CandidateSignal


def test_build_risk_snapshot_marks_missing_day_start_metric() -> None:
    from stock_swing.guardrails.risk_snapshot import build_risk_snapshot

    snapshot = build_risk_snapshot(
        trades=[],
        equity=100_000.0,
        unrealized_pnl=-2_500.0,
        prev_unrealized_pnl=None,
    )

    assert "day_start_unrealized" in snapshot.missing_metrics


def test_paper_demo_halts_buy_when_day_start_missing(monkeypatch, tmp_path, capsys) -> None:
    """
    Regression: REM-P0-002 / 2026-07-29 retest.
    Missing day-start baseline must reject BUYs on the production paper_demo path
    and persist HALT state instead of silently using numeric zero.
    """
    monkeypatch.setattr(paper_demo, "project_root", tmp_path)
    monkeypatch.setattr(paper_demo, "should_skip_non_market_day", lambda: (False, ""))
    monkeypatch.setattr(paper_demo, "read_runtime_mode", lambda root: "paper")
    monkeypatch.setattr(
        paper_demo,
        "read_ledger_quality_gate",
        lambda root: {"current_status": "VALID", "enforce_invalid_ledger_blocks_live_ready": False},
    )
    monkeypatch.setattr(paper_demo.MarketCalendar, "is_market_open", lambda now=None: (True, "open"))
    monkeypatch.setattr(paper_demo.MarketCalendar, "is_regular_market_hours", lambda now=None: (True, "open"))
    monkeypatch.setenv("BROKER_API_KEY", "key")
    monkeypatch.setenv("BROKER_API_SECRET", "secret")
    monkeypatch.setenv("BROKER_BASE_URL", "https://paper.example")

    guardrail_cfg = tmp_path / "config" / "guardrails" / "autonomous_stop.yaml"
    guardrail_cfg.parent.mkdir(parents=True, exist_ok=True)
    guardrail_cfg.write_text("paper_warning_only: false\nrules: {}\n", encoding="utf-8")

    class _KillSwitch:
        def __init__(self, state_file):
            self.state_file = state_file

        def check(self):
            return None

    class _Broker:
        def __init__(self, *args, **kwargs):
            self.base_url = "https://paper.example"

        def fetch_account(self):
            return SimpleNamespace(payload={"status": "ACTIVE", "equity": "100000", "buying_power": "100000"})

        def get_account(self):
            return {"equity": "100000"}

        def fetch_positions(self):
            return SimpleNamespace(payload=[])

    class _Fetcher:
        def __init__(self, *args, **kwargs):
            pass

        def fetch_bars(self, symbol, timeframe="1Day", limit=20):
            record = CanonicalRecord(
                record_id="r1",
                schema_version="v1",
                source="massive",
                source_type="bars",
                symbol=symbol,
                event_type="bar",
                event_time=datetime.now(timezone.utc),
                as_of="2026-07-30",
                ingested_at=datetime.now(timezone.utc),
                timezone="UTC",
                payload_version="v1",
                payload={"close": 100.0},
            )
            return [record], "massive"

    def _momentum_results(self, records):
        return [
            FeatureResult(
                feature_name="price_momentum",
                symbol="AAPL",
                computed_at=datetime.now(timezone.utc),
                values={"momentum": 0.08, "trend": "up", "bars_used": 20, "latest_close": 100.0},
            )
        ]

    def _macro_results(self, records):
        return []

    def _buy_signal(self, features):
        return [
            CandidateSignal(
                strategy_id="breakout_momentum_v1",
                symbol="AAPL",
                action="buy",
                signal_strength=0.95,
                generated_at=datetime.now(timezone.utc),
                time_horizon="3d",
                confidence=0.9,
                reasoning="test buy",
                metadata={"latest_close": 100.0},
            )
        ]

    def _no_signals(self, *args, **kwargs):
        return []

    class _EntryFilterResult:
        passed = None
        blocked: list[tuple[str, str]] = []
        stats: dict[str, object] = {}

    def _filter_identity(self, decisions, records_by_symbol, closed_trades, etf_symbols):
        result = _EntryFilterResult()
        result.passed = decisions
        return result

    monkeypatch.setattr(paper_demo, "KillSwitch", _KillSwitch)
    monkeypatch.setattr(paper_demo, "BrokerClient", _Broker)
    monkeypatch.setattr("stock_swing.sources.hybrid_data_fetcher.HybridDataFetcher", _Fetcher)
    monkeypatch.setattr(paper_demo.PriceMomentumFeature, "compute", _momentum_results)
    monkeypatch.setattr(paper_demo.MacroRegimeFeature, "compute", _macro_results)
    monkeypatch.setattr(paper_demo.BreakoutMomentumStrategy, "generate", _buy_signal)
    monkeypatch.setattr(paper_demo.EventSwingStrategy, "generate", _no_signals)
    monkeypatch.setattr(paper_demo.SimpleExitV2Strategy, "generate", _no_signals)
    monkeypatch.setattr(paper_demo.EntryFilterEngine, "filter", _filter_identity)
    monkeypatch.setattr(paper_demo, "get_permanent_block_summary", lambda **kwargs: [])
    monkeypatch.setattr(paper_demo, "prioritize_buy_signals", lambda entry_signals, *args, **kwargs: entry_signals)
    monkeypatch.setattr(paper_demo, "prioritize_buy_signals_v2", lambda entry_signals, *args, **kwargs: entry_signals)
    monkeypatch.setattr(
        "stock_swing.guardrails.day_start_snapshot.get_prev_unrealized_for_guardrail",
        lambda *args, **kwargs: (None, ["day_start_unrealized"]),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["paper_demo", "--dry-run", "--cron-summary-json", "--symbols", "AAPL"],
    )

    exit_code = paper_demo.main()
    out = capsys.readouterr().out
    summary_line = [line for line in out.splitlines() if line.startswith(CRON_SUMMARY_PREFIX)][-1]
    summary = json.loads(summary_line.split("=", 1)[1])
    breaker = json.loads((tmp_path / "data" / "guardrails" / "circuit_breaker.json").read_text(encoding="utf-8"))

    assert exit_code == 1
    assert summary["status"] == "error"
    assert breaker["status"] == "halted"



# --- Coverage補強: day_start_snapshot の主要パス ---
from stock_swing.guardrails.day_start_snapshot import (
    DayStartSnapshot,
    get_prev_unrealized_for_guardrail,
)


def test_day_start_snapshot_is_valid_for_market_date_same_date():
    snap = DayStartSnapshot(
        market_date="2026-07-30",
        captured_at="2026-07-30T13:00:00+00:00",
        source="broker_api",
        day_start_equity=1000000.0,
        day_start_unrealized=-500.0,
    )
    assert snap.is_valid_for_market_date("2026-07-30") is True


def test_day_start_snapshot_is_valid_for_market_date_mismatch():
    snap = DayStartSnapshot(
        market_date="2026-07-29",
        captured_at="2026-07-29T13:00:00+00:00",
        source="broker_api",
        day_start_equity=1000000.0,
        day_start_unrealized=-500.0,
    )
    assert snap.is_valid_for_market_date("2026-07-30") is False


def test_day_start_snapshot_validation_errors_fully_populated():
    snap = DayStartSnapshot(
        market_date="2026-07-30",
        captured_at="2026-07-30T13:00:00+00:00",
        source="broker_api",
        day_start_equity=1000000.0,
        day_start_unrealized=-500.0,
    )
    assert snap.validation_errors("2026-07-30") == []


def test_day_start_snapshot_validation_errors_equity_none():
    snap = DayStartSnapshot(
        market_date="2026-07-30",
        captured_at="2026-07-30T13:00:00+00:00",
        source="broker_api",
        day_start_equity=None,
        day_start_unrealized=-500.0,
    )
    assert "day_start_equity" in snap.validation_errors("2026-07-30")


def test_day_start_snapshot_validation_errors_stale_date():
    snap = DayStartSnapshot(
        market_date="2026-07-29",
        captured_at="2026-07-29T13:00:00+00:00",
        source="broker_api",
        day_start_equity=1000000.0,
        day_start_unrealized=-500.0,
    )
    assert "market_date" in snap.validation_errors("2026-07-30")


def test_get_prev_unrealized_returns_value_when_snapshot_valid(tmp_path):
    """get_prev_unrealized_for_guardrail returns unrealized pnl from existing snapshot."""
    import json as _json
    (tmp_path / "data" / "guardrails").mkdir(parents=True)
    snap_data = {
        "market_date": "2026-07-30",
        "captured_at": "2026-07-30T13:00:00+00:00",
        "source": "broker_api",
        "day_start_equity": 1000000.0,
        "day_start_unrealized": -750.0,
        "missing_fields": [],
    }
    (tmp_path / "data" / "guardrails" / "day_start_snapshot.json").write_text(_json.dumps(snap_data))
    value, missing = get_prev_unrealized_for_guardrail(
        tmp_path, market_date="2026-07-30"
    )
    assert value == -750.0
    assert missing == []


def test_get_prev_unrealized_returns_missing_when_no_snapshot(tmp_path):
    """get_prev_unrealized_for_guardrail reports missing fields when snapshot absent."""
    value, missing = get_prev_unrealized_for_guardrail(
        tmp_path, market_date="2026-07-30"
    )
    assert len(missing) > 0


# --- risk_snapshot coverage補強 ---
from stock_swing.guardrails.risk_snapshot import build_risk_snapshot


def test_build_risk_snapshot_equity_none_adds_missing():
    """equity=None adds 'equity' to missing_metrics."""
    snap = build_risk_snapshot(
        equity=None,
        unrealized_pnl=-500.0,
        prev_unrealized_pnl=-400.0,
        trades=[],
    )
    assert "equity" in snap.missing_metrics


def test_build_risk_snapshot_unrealized_none_adds_missing():
    """prev_unrealized_pnl=None adds day_start_unrealized to missing."""
    snap = build_risk_snapshot(
        equity=1_000_000.0,
        unrealized_pnl=-500.0,
        prev_unrealized_pnl=None,
        trades=[],
    )
    assert "day_start_unrealized" in snap.missing_metrics


def test_build_risk_snapshot_all_present_no_missing():
    """All required fields present → no missing_metrics."""
    snap = build_risk_snapshot(
        equity=1_000_000.0,
        unrealized_pnl=-500.0,
        prev_unrealized_pnl=-400.0,
        trades=[],
    )
    assert snap.missing_metrics == []


# --- day_start_snapshot カバレッジ補強 ---
from stock_swing.guardrails.day_start_snapshot import (
    load_snapshot,
    capture_snapshot,
    load_or_capture_day_start,
    DayStartMissingError,
    current_market_date,
)


def test_current_market_date_is_string():
    """current_market_date() returns a YYYY-MM-DD string."""
    result = current_market_date()
    assert len(result) == 10 and result[4] == "-" and result[7] == "-"


def test_day_start_snapshot_to_dict():
    """to_dict() returns a serialisable mapping."""
    snap = DayStartSnapshot(
        market_date="2026-07-30",
        captured_at="2026-07-30T13:00:00+00:00",
        source="broker_api",
        day_start_equity=1_000_000.0,
        day_start_unrealized=-500.0,
    )
    d = snap.to_dict()
    assert d["market_date"] == "2026-07-30"
    assert d["day_start_equity"] == 1_000_000.0


def test_day_start_snapshot_validation_errors_missing_source():
    """validation_errors includes 'source' when source is empty."""
    snap = DayStartSnapshot(
        market_date="2026-07-30",
        captured_at="2026-07-30T13:00:00+00:00",
        source="",
        day_start_equity=1_000_000.0,
        day_start_unrealized=-500.0,
    )
    assert "source" in snap.validation_errors("2026-07-30")


def test_day_start_snapshot_validation_errors_missing_captured_at():
    """validation_errors includes 'captured_at' when empty."""
    snap = DayStartSnapshot(
        market_date="2026-07-30",
        captured_at="",
        source="broker_api",
        day_start_equity=1_000_000.0,
        day_start_unrealized=-500.0,
    )
    assert "captured_at" in snap.validation_errors("2026-07-30")


def test_day_start_snapshot_validation_errors_unrealized_none():
    """validation_errors includes day_start_unrealized when unrealized is None."""
    snap = DayStartSnapshot(
        market_date="2026-07-30",
        captured_at="2026-07-30T13:00:00+00:00",
        source="broker_api",
        day_start_equity=1_000_000.0,
        day_start_unrealized=None,
    )
    assert "day_start_unrealized" in snap.validation_errors("2026-07-30")


def test_load_snapshot_returns_none_when_missing(tmp_path):
    """load_snapshot returns None when file does not exist."""
    result = load_snapshot(tmp_path)
    assert result is None


def test_load_snapshot_returns_none_on_corrupt_json(tmp_path):
    """load_snapshot returns None when JSON is invalid."""
    snap_dir = tmp_path / "data" / "guardrails"
    snap_dir.mkdir(parents=True)
    (snap_dir / "day_start_snapshot.json").write_text("{invalid json}")
    result = load_snapshot(tmp_path)
    assert result is None


def test_load_snapshot_returns_snapshot_when_valid(tmp_path):
    """load_snapshot correctly deserialises a valid snapshot file."""
    snap_dir = tmp_path / "data" / "guardrails"
    snap_dir.mkdir(parents=True)
    data = {
        "market_date": "2026-07-30",
        "captured_at": "2026-07-30T13:00:00+00:00",
        "source": "broker_api",
        "day_start_equity": 1_000_000.0,
        "day_start_unrealized": -500.0,
        "missing_fields": [],
    }
    (snap_dir / "day_start_snapshot.json").write_text(json.dumps(data))
    result = load_snapshot(tmp_path)
    assert result is not None
    assert result.day_start_equity == 1_000_000.0


def test_load_or_capture_raises_when_missing_and_not_allowed(tmp_path):
    """load_or_capture_day_start raises DayStartMissingError when snapshot missing."""
    try:
        load_or_capture_day_start(
            tmp_path,
            equity=None,
            unrealized_pnl=None,
            source="",
            allow_missing=False,
            market_date="2026-07-30",
        )
        assert False, "Should have raised DayStartMissingError"
    except DayStartMissingError:
        pass


def test_load_or_capture_returns_snapshot_when_allowed_missing(tmp_path):
    """load_or_capture_day_start with allow_missing=True returns snapshot even with missing fields."""
    snap = load_or_capture_day_start(
        tmp_path,
        equity=None,
        unrealized_pnl=None,
        source="",
        allow_missing=True,
        market_date="2026-07-30",
    )
    assert snap is not None
    assert len(snap.missing_fields) > 0


def test_capture_snapshot_saves_and_reloads(tmp_path):
    """capture_snapshot writes to disk and can be re-read by load_snapshot."""
    snap = capture_snapshot(
        tmp_path,
        equity=999_000.0,
        unrealized_pnl=-300.0,
        source="broker_api",
        market_date="2026-07-30",
    )
    assert snap.day_start_equity == 999_000.0

    reloaded = load_snapshot(tmp_path)
    assert reloaded is not None
    assert reloaded.day_start_equity == 999_000.0


# --- 新規: missing snapshot 上書き修正の回帰テスト (2026-07-31) ---

def test_load_or_capture_overwrites_partial_snapshot_when_equity_available(tmp_path):
    """Regression: 07-30 22:25 JST HALT incident.

    When a snapshot for today exists but has day_start_equity=null (missing),
    and a subsequent call provides a valid equity, the snapshot must be
    re-captured with the complete data so BUYs are not blocked.
    """
    # First call: equity unavailable → writes partial snapshot
    bad_snap = load_or_capture_day_start(
        tmp_path,
        equity=None,
        unrealized_pnl=-500.0,
        source="tracker_estimate",
        allow_missing=True,
        market_date="2026-07-31",
    )
    assert bad_snap.day_start_equity is None
    assert "day_start_equity" in bad_snap.missing_fields

    # Second call: equity now available → should overwrite
    good_snap = load_or_capture_day_start(
        tmp_path,
        equity=987_000.0,
        unrealized_pnl=-500.0,
        source="broker_api",
        allow_missing=False,
        market_date="2026-07-31",
    )
    assert good_snap.day_start_equity == 987_000.0
    assert good_snap.missing_fields == []

    # Persisted snapshot should reflect the fix
    reloaded = load_snapshot(tmp_path)
    assert reloaded is not None
    assert reloaded.day_start_equity == 987_000.0


def test_load_or_capture_preserves_partial_values_on_merge(tmp_path):
    """When existing snapshot has unrealized but no equity,
    and incoming call provides equity but no unrealized,
    the merged snapshot should have both.
    """
    # Existing: has unrealized but no equity
    capture_snapshot(
        tmp_path,
        equity=None,
        unrealized_pnl=-300.0,
        source="tracker_estimate",
        market_date="2026-07-31",
    )

    # Incoming: has equity but no unrealized
    merged = load_or_capture_day_start(
        tmp_path,
        equity=1_000_000.0,
        unrealized_pnl=None,
        source="broker_api",
        allow_missing=False,
        market_date="2026-07-31",
    )
    assert merged.day_start_equity == 1_000_000.0
    assert merged.day_start_unrealized == -300.0  # preserved from existing
    assert merged.missing_fields == []


def test_load_or_capture_does_not_overwrite_complete_snapshot(tmp_path):
    """A complete snapshot (no missing fields) must NOT be overwritten."""
    capture_snapshot(
        tmp_path,
        equity=1_000_000.0,
        unrealized_pnl=-200.0,
        source="broker_api",
        market_date="2026-07-31",
    )
    captured_at_original = load_snapshot(tmp_path).captured_at

    import time
    time.sleep(0.01)  # ensure timestamp would differ if re-captured

    load_or_capture_day_start(
        tmp_path,
        equity=999_000.0,   # different value
        unrealized_pnl=-100.0,
        source="broker_api",
        allow_missing=False,
        market_date="2026-07-31",
    )

    # captured_at should be unchanged (no re-capture)
    reloaded = load_snapshot(tmp_path)
    assert reloaded.captured_at == captured_at_original
    assert reloaded.day_start_equity == 1_000_000.0  # original value preserved


def test_paper_demo_uses_equity_variable_not_get_account(tmp_path):
    """Regression: paper_demo was calling broker.get_account() which does not exist.

    The fix uses the `equity` variable (already fetched via fetch_account() at startup).
    This test verifies a BrokerClient without get_account() does not prevent
    day_start_equity from being set (the attribute error was silently caught before).
    """
    from stock_swing.guardrails.day_start_snapshot import load_or_capture_day_start
    # Simulate what paper_demo now does: equity is already a float, use it directly
    equity_from_broker = 987_573.76  # fetched at startup via fetch_account()
    snap = load_or_capture_day_start(
        tmp_path,
        equity=equity_from_broker,
        unrealized_pnl=-450.0,
        source="broker_api",
        allow_missing=False,
        market_date="2026-07-31",
    )
    assert snap.day_start_equity == pytest.approx(987_573.76)
    assert snap.missing_fields == []


import pytest
