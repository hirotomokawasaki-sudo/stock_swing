"""Acceptance tests for prospective PF-stop review; no trading unlock exists."""
from __future__ import annotations

import copy
import fcntl
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from stock_swing.core.types import CanonicalRecord
from stock_swing.risk.entry_filter import EntryFilterConfig, EntryFilterEngine
from stock_swing.risk.entry_restriction_review import (
    STORE, format_review_candidates, observe_restricted_entries,
)
from stock_swing.reporting.console_renderer import ConsoleRenderer
from stock_swing.reporting.console_summary import ConsoleSummary

ET = ZoneInfo("America/New_York")
START = datetime(2026, 10, 23, 19, 55, tzinfo=timezone.utc)


def decision(now=START, *, symbol="IBM", action="buy", strategy="breakout_momentum_v1"):
    return SimpleNamespace(symbol=symbol, action=action, decision_id=f"{symbol}-{now.isoformat()}",
                           generated_at=now, strategy_id=strategy, strategy_version_id="breakout-v1")


def bar(day, now, *, close=102.0, low=99.0, symbol="IBM"):
    stamp = datetime.combine(day, time(9, 30), ET)
    return CanonicalRecord(
        record_id=f"bar-{symbol}-{day}", schema_version="v1", source="massive",
        source_type="price", symbol=symbol, event_type="bar_daily", event_time=stamp,
        as_of=stamp.isoformat(), ingested_at=now, timezone="UTC", payload_version="v1",
        payload={"open": 100.0, "high": max(103.0, close), "low": low,
                 "close": close, "volume": 2_000_000},
    )


def run(root, now=START, *, decisions=None, records=None, stop=True, config=None, **kwargs):
    return observe_restricted_entries(
        root=root, observed_at=now, decisions=decisions if decisions is not None else [decision(now)],
        blocked=[("IBM", "rolling_pf_gate: symbol_pf=0 (n=5) < threshold=0.70")],
        stop_list=[{"symbol": "IBM"}] if stop else [],
        records_by_symbol={"IBM": records or []}, entry_config=config or EntryFilterConfig(),
        run_id=f"run-{now.isoformat()}", config_hash="fixed-config", **kwargs,
    )


def state(root):
    return json.loads((root / STORE).read_text())["state"]


def mature(root, *, count=30, returns=None, low=99.0):
    """Feed sequential prospective market sessions, not fabricated ledger PnL."""
    now = START
    result = run(root, now)
    for index in range(count):
        pending = state(root)["observations"][-1]
        days = [date.fromisoformat(value) for value in pending["sessions"]]
        now = datetime.combine(days[-1], time(16, 6), ET).astimezone(timezone.utc)
        change = returns[index] if returns is not None else .02
        records = [bar(day, now, close=100 * (1 + change), low=low) for day in days]
        result = run(root, now, records=records, decisions=[decision(now)] if index < count - 1 else [])
    return result, now, records


def test_actual_entry_filter_boundary_preserves_decisions_and_restrictions(tmp_path):
    config = EntryFilterConfig(min_volume=0, min_adr_pct=0)
    candidate = decision()
    original = copy.deepcopy(candidate)
    trades = [{"symbol": "IBM", "status": "closed", "pnl": -10} for _ in range(5)]
    engine = EntryFilterEngine(config)
    filtered = engine.filter([candidate], {"IBM": []}, trades)
    assert filtered.passed == [] and filtered.blocked[0][1].startswith("rolling_pf_gate:")
    summary = observe_restricted_entries(
        root=tmp_path, decisions=[candidate], blocked=filtered.blocked, stop_list=[{"symbol": "IBM"}],
        records_by_symbol={}, entry_config=config, run_id="actual-boundary", config_hash="cfg", observed_at=START,
    )
    assert summary["observations"] == 1 and summary["candidates"] == []
    assert candidate == original and config.pf_gate_skip_symbols == []
    assert engine.filter([candidate], {"IBM": []}, trades).passed == []
    captured = state(tmp_path)["observations"][0]
    assert captured["decision_id"] == candidate.decision_id and captured["run_id"] == "actual-boundary"
    assert captured["sessions"] == ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"]
    assert captured["outcome"] is None and summary["eligible_to_trade"] is False


def test_duplicate_runs_and_strategies_do_not_inflate_count(tmp_path):
    candidates = [decision(), decision(strategy="event_swing_v1")]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: run(tmp_path, decisions=candidates), range(4)))
    assert any(result["status"] == "observing" for result in results)
    assert all(result["status"] == "observing" or result.get("reason") == "BlockingIOError" for result in results)
    assert len(state(tmp_path)["observations"]) == 1
    later = START + timedelta(days=3)
    assert run(tmp_path, later)["observations"] == 1, "Overlapping 5-day opportunities are not independent"


def test_lock_contention_defers_without_blocking_trading_workflow(tmp_path):
    run(tmp_path)
    before = (tmp_path / STORE).read_bytes()
    with (tmp_path / STORE).with_suffix(".lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result = run(tmp_path)
        assert result["status"] == "error" and result["reason"] == "BlockingIOError"
        assert result["candidates"] == []
    assert (tmp_path / STORE).read_bytes() == before


@pytest.mark.parametrize("kwargs,status", [({"dry_run": True}, "dry_run"), ({"mode": "live"}, "unsupported_mode")])
def test_nonwriting_modes(tmp_path, kwargs, status):
    assert run(tmp_path, **kwargs)["status"] == status
    assert not (tmp_path / STORE).exists()


def test_disabled_never_initializes_store(tmp_path, monkeypatch):
    monkeypatch.setenv("ENTRY_RESTRICTION_REVIEW_ENABLED", "false")
    assert run(tmp_path)["status"] == "disabled"
    assert not (tmp_path / STORE).exists()


def test_explicit_purchase_prohibition_and_sell_are_not_release_candidates(tmp_path):
    result = run(tmp_path, config=EntryFilterConfig(purchase_restricted_symbols=["IBM"]))
    assert result["observations"] == 0
    result = run(tmp_path / "sell", decisions=[decision(action="sell")])
    assert result["observations"] == 0


@pytest.mark.parametrize("which", ["missing", "invalid_price", "nan", "quality", "conflict", "future_ingest", "naive", "wrong_symbol"])
def test_missing_or_invalid_outcome_never_completes(tmp_path, which):
    run(tmp_path)
    now = datetime(2026, 10, 30, 20, 6, tzinfo=timezone.utc)
    days = [date(2026, 10, 26) + timedelta(days=n) for n in range(5)]
    records = [bar(day, now) for day in days]
    if which == "missing":
        records.pop(2)
    elif which == "invalid_price":
        records[2].payload["open"] = 0
    elif which == "nan":
        records[2].payload["close"] = float("nan")
    elif which == "quality":
        records[2].quality_flags = ["stale_data"]
    elif which == "conflict":
        records.append(bar(days[2], now, close=101))
    elif which == "future_ingest":
        records[2].ingested_at = now + timedelta(seconds=1)
    elif which == "naive":
        records[2].event_time = records[2].event_time.replace(tzinfo=None)
    else:
        records[2].symbol = "NOW"
    result = run(tmp_path, now, records=records, decisions=[])
    assert result["candidates"] == []
    item = state(tmp_path)["observations"][0]
    assert item["outcome"] is None
    assert result["status"] == "error" or "due_outcome_missing_or_invalid" in result["rows"][0]["reasons"]


def test_partial_current_session_not_used_and_gap_can_recover(tmp_path):
    run(tmp_path)
    now = datetime(2026, 10, 30, 19, 55, tzinfo=timezone.utc)
    records = [bar(date(2026, 10, 26) + timedelta(days=n), now) for n in range(5)]
    assert run(tmp_path, now, records=records, decisions=[])["rows"][0]["completed"] == 0
    now += timedelta(minutes=11)
    result = run(tmp_path, now, records=records[:-1], decisions=[])
    assert result["rows"][0]["completed"] == 0
    result = run(tmp_path, now, records=records, decisions=[])
    assert result["rows"][0]["completed"] == 1
    outcome = state(tmp_path)["observations"][0]["outcome"]
    assert outcome["base_return"] == pytest.approx(.018)
    assert outcome["stress_return"] == pytest.approx(.017)
    assert len(outcome["inputs"]) == 5 and all(row["input_hash"] for row in outcome["inputs"])
    revised = [bar(date(2026, 10, 26) + timedelta(days=n), now, close=200) for n in range(5)]
    run(tmp_path, now, records=revised, decisions=[])
    assert state(tmp_path)["observations"][0]["outcome"] == outcome, "Never improve frozen results with revised history"


def test_us_friday_jst_saturday_dst_and_holiday_sessions(tmp_path):
    # Incident 2026-10-24: JST Saturday is still Friday afternoon in New York.
    jst = START.astimezone(ZoneInfo("Asia/Tokyo"))
    assert jst.weekday() == 5
    run(tmp_path, jst)
    assert state(tmp_path)["observations"][0]["capture_session"] == "2026-10-23"
    other = tmp_path / "dst"
    now = datetime(2026, 10, 30, 19, 55, tzinfo=timezone.utc)
    run(other, now)
    assert state(other)["observations"][0]["sessions"][-1] == "2026-11-06"
    holiday = tmp_path / "thanksgiving"
    run(holiday, datetime(2026, 11, 25, 20, 55, tzinfo=timezone.utc))
    assert state(holiday)["observations"][0]["sessions"] == ["2026-11-27", "2026-11-30", "2026-12-01", "2026-12-02", "2026-12-03"]


def test_time_passage_alone_never_creates_recovery_evidence(tmp_path):
    run(tmp_path)
    result = run(tmp_path, START + timedelta(days=180), decisions=[])
    assert result["rows"][0]["completed"] == 0 and not result["candidates"]


def test_twenty_nine_favorable_results_are_still_insufficient(tmp_path):
    result, _, _ = mature(tmp_path, count=29)
    assert result["rows"][0]["completed"] == 29 and result["candidates"] == []
    assert "insufficient_nonoverlapping_observations" in result["rows"][0]["reasons"]


@pytest.mark.parametrize("delta", [timedelta(seconds=1), -timedelta(days=1)])
def test_future_or_stale_candidate_not_recorded(tmp_path, delta):
    result = run(tmp_path, decisions=[decision(START + delta)])
    assert result["status"] == "error" and not result["candidates"]
    assert not (tmp_path / STORE).exists()


@pytest.mark.parametrize("variant", ["cost", "loss", "halves", "pf"])
def test_thirty_observations_still_need_cost_loss_and_consistency(tmp_path, variant):
    changes = {
        "cost": [.002] * 30,
        "loss": [.02] * 30,
        "halves": [.06] * 15 + [-.01] * 15,
        "pf": [.014] * 15 + [-.007] * 15,
    }[variant]
    result, _, _ = mature(tmp_path, returns=changes, low=90 if variant == "loss" else 98)
    assert result["rows"][0]["completed"] == 30
    assert not result["candidates"] and result["rows"][0]["status"] == "deferred"


def test_candidate_is_reversible_and_never_eligible_to_trade(tmp_path):
    result, now, records = mature(tmp_path)
    assert result["candidates"] == ["IBM"]
    assert result["rows"][0]["completed"] == 30 and result["eligible_to_trade"] is False
    assert result["rows"][0]["requires_strategy_exit_validation"] is True
    assert result["rows"][0]["requires_operator_approval"] is True
    assert not run(tmp_path, now, decisions=[], records=records, stop=False)["candidates"]
    assert not run(tmp_path, now + timedelta(days=3), decisions=[])["candidates"], "A stale candidate must be withdrawn"


def test_config_and_provenance_changes_do_not_pool_favorable_samples(tmp_path):
    result, now, records = mature(tmp_path)
    assert result["candidates"]
    result = run(tmp_path, now, decisions=[], records=records, signal_config={"min_momentum": .01})
    assert not result["candidates"]
    assert "different_current_config" in result["rows"][0]["reasons"]
    result = run(tmp_path, now, config=EntryFilterConfig(rolling_pf_gate=.8), decisions=[])
    assert result["status"] == "observing" and not result["candidates"]
    assert "different_current_config" in result["rows"][0]["reasons"]
    assert state(tmp_path)["observations"][0]["effective_config"]["entry_config"]["rolling_pf_gate"] == .7


def test_scheduled_open_and_close_pf_modes_share_store_without_pooling(tmp_path):
    # Actual scheduler: market_open reduced=false, market_close reduced=true.
    assert run(tmp_path)["observations"] == 1
    close_config = EntryFilterConfig(stock_reduced_mode=True)
    result = run(tmp_path, START + timedelta(minutes=1), config=close_config)
    assert result["status"] == "observing" and result["observations"] == 1
    assert "different_current_config" in result["rows"][0]["reasons"]
    now = datetime(2026, 10, 30, 20, 6, tzinfo=timezone.utc)
    records = [bar(date(2026, 10, 26) + timedelta(days=n), now) for n in range(5)]
    result = run(tmp_path, now, config=close_config, records=records)
    assert result["status"] == "observing" and result["observations"] == 2
    assert len(result["rows"]) == 2, "Different PF regimes must remain separate cohorts"
    assert sorted(row["completed"] for row in result["rows"]) == [0, 1]


def test_changed_protocol_definition_is_not_silently_overwritten(tmp_path):
    # Mutate persisted filesystem input, not application logic. A valid checksum
    # of an old/different study must still require explicit version migration.
    import hashlib
    run(tmp_path)
    path = tmp_path / STORE
    envelope = json.loads(path.read_text())
    envelope["state"]["definition"]["protocol"]["version"] = "old-study"
    encoded = json.dumps(envelope["state"], sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    envelope["checksum"] = hashlib.sha256(encoded.encode()).hexdigest()
    path.write_text(json.dumps(envelope))
    before = path.read_bytes()
    assert run(tmp_path)["status"] == "error"
    assert path.read_bytes() == before


@pytest.mark.parametrize("kind", ["truncated", "checksum", "bad_schema", "nonfinite"])
def test_corrupt_store_never_silently_resets(tmp_path, kind):
    run(tmp_path)
    path = tmp_path / STORE
    envelope = json.loads(path.read_text())
    if kind == "truncated":
        raw = "{"
    elif kind == "bad_schema":
        raw = '{}'
    elif kind == "nonfinite":
        raw = '{"state":NaN}'
    else:
        envelope["state"]["observations"] = []
        raw = json.dumps(envelope)
    path.write_text(raw)
    assert run(tmp_path)["status"] == "error"
    assert path.read_text() == raw


def test_atomic_write_failure_retains_previous_observations(tmp_path, monkeypatch):
    run(tmp_path)
    before = (tmp_path / STORE).read_bytes()
    def fail_replace(*args):
        raise OSError("synthetic disk failure")
    monkeypatch.setattr("os.replace", fail_replace)  # External filesystem I/O only.
    result = run(tmp_path, START + timedelta(minutes=1))
    assert result["status"] == "error" and not result["candidates"]
    assert (tmp_path / STORE).read_bytes() == before


@pytest.mark.parametrize("stamp", [START.replace(tzinfo=None), START - timedelta(seconds=1)])
def test_ambiguous_or_backwards_clock_is_not_recovery(tmp_path, stamp):
    run(tmp_path)
    before = (tmp_path / STORE).read_bytes()
    assert run(tmp_path, stamp)["status"] == "error"
    assert (tmp_path / STORE).read_bytes() == before


def test_service_summary_renderer_and_actual_notification_path(tmp_path, monkeypatch):
    review, _, _ = mature(tmp_path)
    summary = ConsoleSummary.build(run_id="review", equity=100000, open_position_count=0,
                                   entry_filter_stats={"entry_restriction_review": review})
    assert summary.to_dict()["decision_funnel"]["entry_restriction_review"]["candidates"] == ["IBM"]
    alert = next(a for a in summary.to_dict()["alerts"] if a["code"] == "entry_restriction_review_candidate")
    assert alert["severity"] == "info" and alert["details"]["symbols"] == ["IBM"]
    assert summary.run_status == "OK", "Research notices must not degrade trading health"
    rendered = ConsoleRenderer().render(summary)
    assert "[INFO] entry_restriction_review_candidate" in rendered
    assert "自動解除なし" in rendered and "30/30件" in rendered and "解除は要承認" in rendered
    from stock_swing.cli.paper_demo import _send_telegram_summary
    messages = []
    monkeypatch.setattr("stock_swing.utils.telegram_notifier.send_notification", lambda message, **kw: messages.append(message) or True)
    _send_telegram_summary(["IBM"], [], [], 100000, False, True,
                           breaker_state=SimpleNamespace(status="ok"), entry_restriction_review=review)
    assert len(messages) == 1 and "購入停止の再検証候補: IBM" in messages[0]
    assert "購入制限は維持" in messages[0] and messages[0].index("再検証候補") < 1000
    assert not format_review_candidates({"status": "error", "candidates": ["IBM"]})
    escaped = format_review_candidates({"status": "observing", "candidates": ["<X>"]}, telegram=True)
    assert "&lt;X&gt;" in escaped and "<X>" not in escaped
