"""Regression tests for scripts/verify_rebuild_integrity.py.

Incident (2026-08-24): a rebuild run printed "✅ Post-rebuild integrity
check passed" while 3 closed/quarantine overlap trades and 1 reversed-
chronology trade were still present in the written pnl_state.json. Root
causes (two independent bugs, both fixed same day):

1. check_closed_quarantine_overlap() keyed overlap detection on `trade_id`
   (a sequential index string re-assigned every rebuild run), so a
   coincidental trade_id string collision between an unrelated NEW trade
   and an OLD quarantined trade was reported as a "duplicate" even though
   their real identity -- (broker_order_id, exit_broker_order_id) -- was
   completely different. scripts/audit_trades_with_market_data.py's
   check_ledger_invariants() had already fixed this exact issue on
   2026-07-28 by keying on the broker order-ID pair instead; this script
   was never updated to match, so the bug regressed here specifically.

2. main()'s --fix path only auto-fixes daily_snapshots/peak_price, but
   reported "All checks passed" (exit 0) as soon as `total_fixed > 0`,
   even when OTHER issues (overlap, reversed chronology, pnl consistency)
   were still unresolved -- it never re-ran the checks after fixing to
   confirm they were actually gone.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from verify_rebuild_integrity import (  # noqa: E402
    check_closed_quarantine_overlap,
    check_reversed_chronology,
    main as verify_main,
)


def _closed_trade(**overrides) -> dict:
    base = {
        "trade_id": "broker_match_0001_ADBE",
        "symbol": "ADBE",
        "status": "closed",
        "broker_order_id": "buy-uuid-aaa",
        "exit_broker_order_id": "sell-uuid-bbb",
        "entry_time": "2026-06-02T13:30:14Z",
        "exit_time": "2026-06-03T17:01:33Z",
        "pnl": -1388.75,
    }
    base.update(overrides)
    return base


def _quarantined_trade(**overrides) -> dict:
    base = {
        "trade_id": "broker_match_0001_ADBE",  # deliberately SAME trade_id as above
        "symbol": "ADBE",
        "status": "quarantined",
        "broker_order_id": "buy-uuid-ZZZ",       # DIFFERENT real broker order
        "exit_broker_order_id": "sell-uuid-YYY",  # DIFFERENT real broker order
        "entry_time": "2026-07-07T19:55:50Z",
        "exit_time": "2026-06-03T17:01:33Z",
        "pnl": 3289.53,
    }
    base.update(overrides)
    return base


class TestClosedQuarantineOverlapUsesOrderIdNotTradeId:
    def test_coincidental_trade_id_collision_is_not_flagged_as_overlap(self):
        """Regression: 2026-08-24 false positive. Same trade_id string,
        completely different broker_order_id/exit_broker_order_id pairs ->
        must NOT be reported as an overlap.
        """
        state = {
            "trades": [_closed_trade()],
            "quarantined_trades": [_quarantined_trade()],
        }
        issues = check_closed_quarantine_overlap(state)
        assert issues == [], f"expected no overlap issues, got: {issues}"

    def test_genuine_overlap_by_order_id_pair_is_still_detected(self):
        """A real duplicate -- SAME (broker_order_id, exit_broker_order_id)
        pair present in both closed trades and quarantined_trades -- must
        still be caught (this is the actual invariant being protected).
        """
        shared_entry_oid = "buy-uuid-shared"
        shared_exit_oid = "sell-uuid-shared"
        state = {
            "trades": [_closed_trade(
                trade_id="broker_match_0099_XYZ",
                broker_order_id=shared_entry_oid,
                exit_broker_order_id=shared_exit_oid,
            )],
            "quarantined_trades": [_quarantined_trade(
                trade_id="broker_match_0001_ADBE",  # different trade_id on purpose
                broker_order_id=shared_entry_oid,
                exit_broker_order_id=shared_exit_oid,
            )],
        }
        issues = check_closed_quarantine_overlap(state)
        assert len(issues) == 1
        assert "overlap = 1" in issues[0]

    def test_two_trades_with_both_ids_empty_are_not_treated_as_matching(self):
        """Two malformed/legacy trades that both happen to have empty
        broker_order_id AND empty exit_broker_order_id must not collide on
        the key ("", "") -- that would be an even worse false positive
        than the trade_id bug this test suite otherwise guards against.
        """
        state = {
            "trades": [_closed_trade(broker_order_id="", exit_broker_order_id="")],
            "quarantined_trades": [_quarantined_trade(broker_order_id="", exit_broker_order_id="")],
        }
        issues = check_closed_quarantine_overlap(state)
        assert issues == []

    def test_no_overlap_returns_empty_list(self):
        state = {"trades": [], "quarantined_trades": []}
        assert check_closed_quarantine_overlap(state) == []

    def test_falls_back_to_entry_broker_order_id_field_name(self):
        """Some legacy quarantine records use 'entry_broker_order_id' instead
        of 'broker_order_id' -- the fallback must still work for a genuine
        overlap using that field name.
        """
        shared_exit = "sell-uuid-shared2"
        shared_entry = "buy-uuid-shared2"
        state = {
            "trades": [_closed_trade(broker_order_id=shared_entry, exit_broker_order_id=shared_exit)],
            "quarantined_trades": [{
                "trade_id": "legacy_1",
                "symbol": "XYZ",
                "entry_broker_order_id": shared_entry,  # legacy field name
                "exit_broker_order_id": shared_exit,
            }],
        }
        issues = check_closed_quarantine_overlap(state)
        assert len(issues) == 1


class TestReversedChronologyStillDetected:
    def test_entry_after_exit_is_flagged(self):
        state = {
            "trades": [_closed_trade(
                entry_time="2026-08-11T13:35:36Z",
                exit_time="2026-07-15T16:00:50Z",
            )],
        }
        issues = check_reversed_chronology(state)
        assert len(issues) == 1
        assert "reversed chronology" in issues[0]

    def test_normal_chronology_not_flagged(self):
        state = {"trades": [_closed_trade()]}
        assert check_reversed_chronology(state) == []


class TestMainReportsFailureWhenUnfixableIssuesRemain:
    """Regression: 2026-08-24. main() must not report success (exit 0) when
    --fix only resolved SOME of the detected issues.
    """

    def test_fix_with_unresolvable_overlap_exits_nonzero(self, tmp_path, monkeypatch):
        import verify_rebuild_integrity as vri

        state_file = tmp_path / "pnl_state.json"
        backup_file = tmp_path / "pnl_state_backup_20260824_000000.json"

        # A genuine overlap (same order-id pair in both lists) that --fix
        # cannot resolve (only daily_snapshots/peak_price are auto-fixable).
        shared_entry, shared_exit = "buy-real-dup", "sell-real-dup"
        state = {
            "trades": [_closed_trade(broker_order_id=shared_entry, exit_broker_order_id=shared_exit)],
            "quarantined_trades": [_quarantined_trade(broker_order_id=shared_entry, exit_broker_order_id=shared_exit)],
            "daily_snapshots": [{"date": "2026-08-01", "equity": 1000000}],
        }
        state_file.write_text(json.dumps(state), encoding="utf-8")
        backup_file.write_text(json.dumps(state), encoding="utf-8")

        monkeypatch.setattr(vri, "STATE_FILE", state_file)
        monkeypatch.setattr(sys, "argv", ["verify_rebuild_integrity.py", "--backup", str(backup_file), "--fix"])

        exit_code = verify_main()
        assert exit_code != 0, (
            "main() must exit non-zero when a genuine, non-auto-fixable "
            "issue (closed/quarantine overlap) remains after --fix"
        )

    def test_fix_with_only_auto_fixable_issues_exits_zero(self, tmp_path, monkeypatch):
        import verify_rebuild_integrity as vri

        state_file = tmp_path / "pnl_state.json"
        backup_file = tmp_path / "pnl_state_backup_20260824_000000.json"

        # daily_snapshots wiped in the "current" state, present in backup --
        # this IS auto-fixable, so main() should end up exiting 0.
        state = {
            "trades": [_closed_trade()],
            "quarantined_trades": [],
            "daily_snapshots": [],
            "cumulative_realized_pnl": -1388.75,
        }
        backup = {
            "trades": [_closed_trade()],
            "quarantined_trades": [],
            "daily_snapshots": [{"date": "2026-08-01", "equity": 1000000}],
            "cumulative_realized_pnl": -1388.75,
        }
        state_file.write_text(json.dumps(state), encoding="utf-8")
        backup_file.write_text(json.dumps(backup), encoding="utf-8")

        monkeypatch.setattr(vri, "STATE_FILE", state_file)
        monkeypatch.setattr(sys, "argv", ["verify_rebuild_integrity.py", "--backup", str(backup_file), "--fix"])

        exit_code = verify_main()
        assert exit_code == 0

        saved = json.loads(state_file.read_text(encoding="utf-8"))
        assert saved["daily_snapshots"] == [{"date": "2026-08-01", "equity": 1000000}]

    def test_no_issues_at_all_exits_zero_without_backup(self, tmp_path, monkeypatch):
        """With zero issues detected at all (including no holding_days
        warning -- holding_days explicitly set), main() must exit 0 even
        without --fix and without a backup (nothing needed fixing).
        """
        import verify_rebuild_integrity as vri

        state_file = tmp_path / "pnl_state.json"
        state = {
            "trades": [_closed_trade(holding_days=1.5)],
            "quarantined_trades": [],
            "daily_snapshots": [{"date": "2026-08-01", "equity": 1000000}],
            "cumulative_realized_pnl": -1388.75,
        }
        state_file.write_text(json.dumps(state), encoding="utf-8")

        monkeypatch.setattr(vri, "STATE_FILE", state_file)
        monkeypatch.setattr(vri, "_latest_backup", lambda: None)
        monkeypatch.setattr(sys, "argv", ["verify_rebuild_integrity.py"])

        assert verify_main() == 0

    def test_holding_days_warning_alone_does_not_fail_after_fix(self, tmp_path, monkeypatch):
        """A pure WARNING-level issue (holding_days missing) with nothing
        else wrong must still be treated as an overall pass -- only
        INVARIANT FAIL-level issues should force a non-zero exit.
        """
        import verify_rebuild_integrity as vri

        state_file = tmp_path / "pnl_state.json"
        backup_file = tmp_path / "pnl_state_backup_20260824_000000.json"

        state = {
            "trades": [_closed_trade(holding_days=None)],
            "quarantined_trades": [],
            "daily_snapshots": [{"date": "2026-08-01", "equity": 1000000}],
            "cumulative_realized_pnl": -1388.75,
        }
        state_file.write_text(json.dumps(state), encoding="utf-8")
        backup_file.write_text(json.dumps(state), encoding="utf-8")

        monkeypatch.setattr(vri, "STATE_FILE", state_file)
        monkeypatch.setattr(sys, "argv", ["verify_rebuild_integrity.py", "--backup", str(backup_file), "--fix"])

        assert verify_main() == 0
