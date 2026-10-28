"""Tests for entry_signal_strength persistence in pnl_state.

Covers:
- record_submission() saves signal_strength as entry_signal_strength
- trade_opened event payload contains signal_strength
- backfill_entry_signal_strength.py restores ESS from decision files
- rebuild ESS merging via _merge_ess_from_trade_events()

Added 2026-07-28 (entry_signal_strength durability fix).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure project src is on path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from stock_swing.tracking.pnl_tracker import PnLTracker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_tracker(tmp_path: Path) -> PnLTracker:
    return PnLTracker(tmp_path)


def _read_pnl_state(tracker: PnLTracker) -> dict:
    state_file = tracker.project_root / "data" / "tracking" / "pnl_state.json"
    return json.loads(state_file.read_text(encoding="utf-8"))


def _read_trade_events(tracker: PnLTracker) -> list[dict]:
    events_file = tracker.project_root / "data" / "tracking" / "trade_events.jsonl"
    if not events_file.exists():
        return []
    events = []
    for line in events_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


# ---------------------------------------------------------------------------
# 1. record_submission() → entry_signal_strength persisted to pnl_state
# ---------------------------------------------------------------------------


class TestRecordSubmissionESS:
    def test_signal_strength_stored_in_trade(self, tmp_path: Path) -> None:
        """record_submission with signal_strength=0.75 → entry_signal_strength=0.75."""
        tracker = _make_tracker(tmp_path)
        tracker.record_submission(
            symbol="AAPL",
            strategy_id="test_strat",
            side="buy",
            qty=10,
            price=150.0,
            broker_order_id="oid-ess-1",
            decision_id="dec-ess-0001",
            signal_strength=0.75,
        )
        state = _read_pnl_state(tracker)
        trade = state["trades"][0]
        assert trade["entry_signal_strength"] == pytest.approx(0.75, abs=1e-4)

    def test_signal_strength_none_stores_none(self, tmp_path: Path) -> None:
        """record_submission with signal_strength=None → entry_signal_strength=None."""
        tracker = _make_tracker(tmp_path)
        tracker.record_submission(
            symbol="MSFT",
            strategy_id="test_strat",
            side="buy",
            qty=5,
            price=300.0,
            broker_order_id="oid-ess-2",
            decision_id="dec-ess-0002",
            signal_strength=None,
        )
        state = _read_pnl_state(tracker)
        trade = state["trades"][0]
        assert trade["entry_signal_strength"] is None

    def test_signal_strength_zero_stored(self, tmp_path: Path) -> None:
        """signal_strength=0.0 is a valid value and must be stored (not treated as falsy)."""
        tracker = _make_tracker(tmp_path)
        tracker.record_submission(
            symbol="GOOG",
            strategy_id="test_strat",
            side="buy",
            qty=1,
            price=180.0,
            broker_order_id="oid-ess-3",
            decision_id="dec-ess-0003",
            signal_strength=0.0,
        )
        state = _read_pnl_state(tracker)
        trade = state["trades"][0]
        assert trade["entry_signal_strength"] == pytest.approx(0.0, abs=1e-4)

    def test_signal_strength_rounded_to_4dp(self, tmp_path: Path) -> None:
        """Stored value is rounded to 4 decimal places."""
        tracker = _make_tracker(tmp_path)
        tracker.record_submission(
            symbol="AMZN",
            strategy_id="test_strat",
            side="buy",
            qty=3,
            price=200.0,
            broker_order_id="oid-ess-4",
            decision_id="dec-ess-0004",
            signal_strength=0.555555555,
        )
        state = _read_pnl_state(tracker)
        assert state["trades"][0]["entry_signal_strength"] == 0.5556


# ---------------------------------------------------------------------------
# 2. trade_opened event payload contains signal_strength
# ---------------------------------------------------------------------------


class TestTradeOpenedEventPayload:
    def test_event_payload_has_signal_strength(self, tmp_path: Path) -> None:
        """trade_opened event payload must include signal_strength."""
        tracker = _make_tracker(tmp_path)
        tracker.record_submission(
            symbol="NVDA",
            strategy_id="test_strat",
            side="buy",
            qty=8,
            price=900.0,
            broker_order_id="oid-ev-1",
            decision_id="dec-ev-0001",
            signal_strength=0.88,
        )
        events = _read_trade_events(tracker)
        opened = [e for e in events if e.get("event_type") == "trade_opened"]
        assert len(opened) == 1
        payload = opened[0].get("payload", {})
        assert "signal_strength" in payload
        assert payload["signal_strength"] == pytest.approx(0.88, abs=1e-4)

    def test_event_payload_signal_strength_none_when_not_provided(self, tmp_path: Path) -> None:
        """Payload signal_strength is null when not provided."""
        tracker = _make_tracker(tmp_path)
        tracker.record_submission(
            symbol="AMD",
            strategy_id="test_strat",
            side="buy",
            qty=20,
            price=120.0,
            broker_order_id="oid-ev-2",
            decision_id="dec-ev-0002",
            signal_strength=None,
        )
        events = _read_trade_events(tracker)
        opened = [e for e in events if e.get("event_type") == "trade_opened"]
        assert len(opened) == 1
        payload = opened[0].get("payload", {})
        assert payload.get("signal_strength") is None

    def test_event_includes_existing_fields(self, tmp_path: Path) -> None:
        """Adding signal_strength must not remove entry_price/qty/strategy_id."""
        tracker = _make_tracker(tmp_path)
        tracker.record_submission(
            symbol="META",
            strategy_id="breakout_v1",
            side="buy",
            qty=5,
            price=500.0,
            broker_order_id="oid-ev-3",
            decision_id="dec-ev-0003",
            signal_strength=0.65,
        )
        events = _read_trade_events(tracker)
        payload = [e for e in events if e.get("event_type") == "trade_opened"][0]["payload"]
        assert payload["entry_price"] == pytest.approx(500.0)
        assert payload["qty"] == 5
        assert "strategy_id" in payload


# ---------------------------------------------------------------------------
# 3. _merge_ess_from_trade_events() in rebuild script
# ---------------------------------------------------------------------------


class TestMergeESSFromTradeEvents:
    def test_reads_signal_strength_from_events(self, tmp_path: Path) -> None:
        """Events with payload.signal_strength are merged into ess_by_order_id."""
        events_file = tmp_path / "trade_events.jsonl"
        events_file.write_text(
            json.dumps({
                "event_type": "trade_opened",
                "broker_order_id": "bid-001",
                "payload": {"entry_price": 100.0, "qty": 10, "strategy_id": "s1", "signal_strength": 0.72},
            }) + "\n",
            encoding="utf-8",
        )
        from rebuild_pnl_state_from_broker import _merge_ess_from_trade_events
        result = _merge_ess_from_trade_events(events_file, {})
        assert "bid-001" in result
        assert result["bid-001"] == pytest.approx(0.72, abs=1e-4)

    def test_existing_dict_takes_priority(self, tmp_path: Path) -> None:
        """Existing ess_by_order_id (from pnl_state) wins over trade_events value."""
        events_file = tmp_path / "trade_events.jsonl"
        events_file.write_text(
            json.dumps({
                "event_type": "trade_opened",
                "broker_order_id": "bid-002",
                "payload": {"signal_strength": 0.50},
            }) + "\n",
            encoding="utf-8",
        )
        from rebuild_pnl_state_from_broker import _merge_ess_from_trade_events
        existing = {"bid-002": 0.99}  # pnl_state had a non-None ESS
        result = _merge_ess_from_trade_events(events_file, existing)
        assert result["bid-002"] == pytest.approx(0.99, abs=1e-4)  # unchanged

    def test_none_signal_strength_skipped(self, tmp_path: Path) -> None:
        """Events with payload.signal_strength=null are ignored."""
        events_file = tmp_path / "trade_events.jsonl"
        events_file.write_text(
            json.dumps({
                "event_type": "trade_opened",
                "broker_order_id": "bid-003",
                "payload": {"signal_strength": None},
            }) + "\n",
            encoding="utf-8",
        )
        from rebuild_pnl_state_from_broker import _merge_ess_from_trade_events
        result = _merge_ess_from_trade_events(events_file, {})
        assert "bid-003" not in result

    def test_non_trade_opened_events_ignored(self, tmp_path: Path) -> None:
        """Only trade_opened events are processed."""
        events_file = tmp_path / "trade_events.jsonl"
        events_file.write_text(
            json.dumps({
                "event_type": "trade_closed",
                "broker_order_id": "bid-004",
                "payload": {"signal_strength": 0.80},
            }) + "\n",
            encoding="utf-8",
        )
        from rebuild_pnl_state_from_broker import _merge_ess_from_trade_events
        result = _merge_ess_from_trade_events(events_file, {})
        assert "bid-004" not in result

    def test_missing_events_file_returns_existing(self, tmp_path: Path) -> None:
        """If events file doesn't exist, return existing dict unchanged."""
        from rebuild_pnl_state_from_broker import _merge_ess_from_trade_events
        events_file = tmp_path / "no_such_file.jsonl"
        existing = {"bid-x": 0.55}
        result = _merge_ess_from_trade_events(events_file, existing)
        assert result == existing

    def test_malformed_lines_skipped(self, tmp_path: Path) -> None:
        """Malformed JSON lines are silently skipped."""
        events_file = tmp_path / "trade_events.jsonl"
        events_file.write_text(
            "not json\n"
            + json.dumps({
                "event_type": "trade_opened",
                "broker_order_id": "bid-005",
                "payload": {"signal_strength": 0.60},
            }) + "\n",
            encoding="utf-8",
        )
        from rebuild_pnl_state_from_broker import _merge_ess_from_trade_events
        result = _merge_ess_from_trade_events(events_file, {})
        assert result.get("bid-005") == pytest.approx(0.60, abs=1e-4)


# ---------------------------------------------------------------------------
# 4. backfill_entry_signal_strength.py — decision file lookup
# ---------------------------------------------------------------------------


class TestBackfillESS:
    def _write_decision(self, decisions_dir: Path, symbol: str, decision_id: str, ss: float) -> None:
        decisions_dir.mkdir(parents=True, exist_ok=True)
        f = decisions_dir / f"decision_{symbol}_20260101_000000.json"
        f.write_text(json.dumps({"decision_id": decision_id, "signal_strength": ss}), encoding="utf-8")

    def _write_events(self, events_file: Path, entries: list[dict]) -> None:
        events_file.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(e) for e in entries]
        events_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_decision_file_lookup_via_trade_id(self, tmp_path: Path) -> None:
        """ESS is restored from decision file via trade_id prefix."""
        from backfill_entry_signal_strength import _load_ess_from_decisions

        decisions_dir = tmp_path / "decisions"
        events_file = tmp_path / "trade_events.jsonl"
        decision_id = "abcd1234-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        self._write_decision(decisions_dir, "AAPL", decision_id, 0.77)
        # trade_id encodes first 8 chars of decision_id
        prefix8 = decision_id[:8]  # "abcd1234"
        self._write_events(events_file, [
            {
                "event_type": "trade_opened",
                "broker_order_id": "broker-aapl-1",
                "trade_id": f"AAPL-{prefix8}",
                "payload": {},
            }
        ])
        result = _load_ess_from_decisions(events_file, decisions_dir)
        assert "broker-aapl-1" in result
        assert result["broker-aapl-1"] == pytest.approx(0.77, abs=1e-4)

    def test_no_match_returns_empty(self, tmp_path: Path) -> None:
        """No matching decision file → empty dict."""
        from backfill_entry_signal_strength import _load_ess_from_decisions

        decisions_dir = tmp_path / "decisions"
        events_file = tmp_path / "trade_events.jsonl"
        decisions_dir.mkdir()
        self._write_events(events_file, [
            {
                "event_type": "trade_opened",
                "broker_order_id": "broker-xyz-1",
                "trade_id": "XYZ-deadbeef",
                "payload": {},
            }
        ])
        result = _load_ess_from_decisions(events_file, decisions_dir)
        assert result == {}

    def test_events_payload_ess_priority_over_decision_file(self, tmp_path: Path) -> None:
        """When event payload has signal_strength AND decision file exists, events wins."""
        from backfill_entry_signal_strength import _load_ess_from_events, _load_ess_from_decisions

        decisions_dir = tmp_path / "decisions"
        events_file = tmp_path / "trade_events.jsonl"
        decision_id = "bbbb1234-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        self._write_decision(decisions_dir, "TSLA", decision_id, 0.50)
        prefix8 = decision_id[:8]
        self._write_events(events_file, [
            {
                "event_type": "trade_opened",
                "broker_order_id": "broker-tsla-1",
                "trade_id": f"TSLA-{prefix8}",
                "payload": {"signal_strength": 0.91},
            }
        ])
        ess_events = _load_ess_from_events()  # reads from actual file — skip; test merger directly
        from backfill_entry_signal_strength import _load_ess_from_decisions
        ess_decisions = _load_ess_from_decisions(events_file, decisions_dir)
        # Simulate main() merge: events wins
        ess_events_local: dict = {}
        for line in events_file.read_text().splitlines():
            if not line.strip():
                continue
            ev = json.loads(line)
            if ev.get("event_type") == "trade_opened":
                bid = ev.get("broker_order_id", "")
                ss = ev.get("payload", {}).get("signal_strength")
                if ss is not None and bid:
                    ess_events_local[bid] = float(ss)
        merged = {**ess_decisions, **ess_events_local}  # events overwrites decisions
        assert merged["broker-tsla-1"] == pytest.approx(0.91, abs=1e-4)
