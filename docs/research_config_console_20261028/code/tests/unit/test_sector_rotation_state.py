"""R13-D Phase 3: tests for stock_swing.strategy_engine.sector_rotation_state.

Acceptance: R13-D Phase 3 ("リバランス状態管理の実装") -- verifies the
rebalance-due gate, holdings diff computation, and state persistence all
behave correctly, including fail-safe handling of missing/corrupt state
(testing_standards.md 1-A: ファイル欠損・破損入力のフォールバック).
"""
from __future__ import annotations

from datetime import date

import pytest

from stock_swing.strategy_engine.sector_rotation_state import (
    RebalanceState,
    SectorRotationStateStore,
    advance_rebalance_state,
    compute_rebalance_diff,
    is_rebalance_due,
)


class TestIsRebalanceDueFirstRunAndThresholds:
    def test_none_state_is_always_due(self):
        assert is_rebalance_due(None, today=date(2026, 8, 24), hold_days=21) is True

    def test_state_with_empty_last_rebalance_date_is_due(self):
        state = RebalanceState(last_rebalance_date="")
        assert is_rebalance_due(state, today=date(2026, 8, 24)) is True

    def test_not_due_before_hold_days_elapsed(self):
        state = RebalanceState(last_rebalance_date="2026-08-10")
        # 10 days elapsed, hold_days=21 -> not due yet
        assert is_rebalance_due(state, today=date(2026, 8, 20), hold_days=21) is False

    def test_due_exactly_at_hold_days_boundary(self):
        state = RebalanceState(last_rebalance_date="2026-08-01")
        # exactly 21 days elapsed
        assert is_rebalance_due(state, today=date(2026, 8, 22), hold_days=21) is True

    def test_due_well_past_hold_days(self):
        state = RebalanceState(last_rebalance_date="2026-01-01")
        assert is_rebalance_due(state, today=date(2026, 8, 24), hold_days=21) is True

    def test_one_day_short_of_boundary_not_due(self):
        state = RebalanceState(last_rebalance_date="2026-08-01")
        # 20 days elapsed, one short of the 21-day hold
        assert is_rebalance_due(state, today=date(2026, 8, 21), hold_days=21) is False


class TestIsRebalanceDueCorruptDateFailsSafe(object):
    def test_unparseable_date_string_fails_toward_rebalancing(self):
        """Corrupt state must fail SAFE (rebalance) not fail CLOSED (never
        rebalance again) -- see module docstring's fail-safe design note.
        """
        state = RebalanceState(last_rebalance_date="not-a-date")
        assert is_rebalance_due(state, today=date(2026, 8, 24), hold_days=21) is True


class TestComputeRebalanceDiff:
    def test_all_new_symbols_are_enter(self):
        diff = compute_rebalance_diff(current_holdings=[], new_holdings=["SOXX", "SMH"])
        assert diff.enter == ["SMH", "SOXX"]
        assert diff.exit == []
        assert diff.hold == []
        assert not diff.is_noop

    def test_all_dropped_symbols_are_exit(self):
        diff = compute_rebalance_diff(current_holdings=["SOXX", "SMH"], new_holdings=[])
        assert diff.enter == []
        assert diff.exit == ["SMH", "SOXX"]
        assert diff.hold == []

    def test_unchanged_symbols_are_hold(self):
        diff = compute_rebalance_diff(
            current_holdings=["SOXX", "SMH"], new_holdings=["SOXX", "SMH"],
        )
        assert diff.enter == []
        assert diff.exit == []
        assert diff.hold == ["SMH", "SOXX"]
        assert diff.is_noop

    def test_mixed_enter_exit_hold(self):
        diff = compute_rebalance_diff(
            current_holdings=["SOXX", "SMH", "CRM"],
            new_holdings=["SOXX", "SNOW", "MDB"],
        )
        assert diff.enter == ["MDB", "SNOW"]
        assert diff.exit == ["CRM", "SMH"]
        assert diff.hold == ["SOXX"]

    def test_result_lists_are_sorted_for_stable_ordering(self):
        diff = compute_rebalance_diff(
            current_holdings=["ZETA", "ALPHA"], new_holdings=["ZETA", "ALPHA", "MID"],
        )
        assert diff.enter == ["MID"]
        assert diff.hold == ["ALPHA", "ZETA"]


class TestAdvanceRebalanceState:
    def test_first_rebalance_starts_count_at_one(self):
        new_state = advance_rebalance_state(
            prior_state=None, today=date(2026, 8, 24),
            new_sectors=["semiconductor"], new_holdings=["SOXX", "SMH"],
        )
        assert new_state.rebalance_count == 1
        assert new_state.last_rebalance_date == "2026-08-24"
        assert new_state.current_sectors == ["semiconductor"]
        assert new_state.current_holdings == ["SOXX", "SMH"]

    def test_subsequent_rebalance_increments_count(self):
        prior = RebalanceState(
            last_rebalance_date="2026-08-03", current_sectors=["software"],
            current_holdings=["CRM", "MDB"], rebalance_count=3,
        )
        new_state = advance_rebalance_state(
            prior_state=prior, today=date(2026, 8, 24),
            new_sectors=["semiconductor"], new_holdings=["SOXX"],
        )
        assert new_state.rebalance_count == 4

    def test_new_state_fully_replaces_sectors_and_holdings(self):
        prior = RebalanceState(
            last_rebalance_date="2026-08-03", current_sectors=["software"],
            current_holdings=["CRM"], rebalance_count=1,
        )
        new_state = advance_rebalance_state(
            prior_state=prior, today=date(2026, 8, 24),
            new_sectors=["semiconductor", "robotics_ai"], new_holdings=["SOXX", "BOTZ"],
        )
        assert new_state.current_sectors == ["semiconductor", "robotics_ai"]
        assert new_state.current_holdings == ["SOXX", "BOTZ"]


class TestSectorRotationStateStorePersistence:
    def test_load_on_missing_file_returns_none(self, tmp_path):
        store = SectorRotationStateStore(path=tmp_path / "does_not_exist.json")
        assert store.load() is None

    def test_save_then_load_round_trips(self, tmp_path):
        store = SectorRotationStateStore(path=tmp_path / "state.json")
        state = RebalanceState(
            last_rebalance_date="2026-08-24", current_sectors=["semiconductor"],
            current_holdings=["SOXX", "SMH"], rebalance_count=2,
        )
        store.save(state)
        loaded = store.load()
        assert loaded == state

    def test_save_overwrites_prior_state_not_appends(self, tmp_path):
        path = tmp_path / "state.json"
        store = SectorRotationStateStore(path=path)
        store.save(RebalanceState(last_rebalance_date="2026-08-01", rebalance_count=1))
        store.save(RebalanceState(last_rebalance_date="2026-08-22", rebalance_count=2))

        loaded = store.load()
        assert loaded.rebalance_count == 2
        assert loaded.last_rebalance_date == "2026-08-22"
        # File contains exactly one JSON object, not an appended log.
        raw = path.read_text(encoding="utf-8")
        import json
        parsed = json.loads(raw)  # would raise if multiple concatenated objects
        assert parsed["rebalance_count"] == 2

    def test_load_on_corrupt_json_returns_none_not_raise(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text("{not valid json", encoding="utf-8")
        store = SectorRotationStateStore(path=path)
        assert store.load() is None

    def test_constructor_creates_no_file_until_first_save(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "state.json"
        store = SectorRotationStateStore(path=path)
        assert not path.exists()
        store.save(RebalanceState(last_rebalance_date="2026-08-24"))
        assert path.exists()

    def test_reinstantiated_store_on_same_path_sees_saved_state(self, tmp_path):
        """Persistence check (testing_standards.md 1-B): a new store
        instance pointed at the same file must see what a prior instance
        wrote.
        """
        path = tmp_path / "state.json"
        SectorRotationStateStore(path=path).save(
            RebalanceState(last_rebalance_date="2026-08-24", rebalance_count=5)
        )
        reloaded = SectorRotationStateStore(path=path).load()
        assert reloaded.rebalance_count == 5


class TestEndToEndRebalanceCycle:
    def test_full_cycle_not_due_then_due_then_state_updated(self, tmp_path):
        """Integration-style test walking through: first run (always due,
        no state) -> rebalance recorded -> immediately-following day (not
        due) -> hold_days later (due again, with a changed top-N).
        """
        store = SectorRotationStateStore(path=tmp_path / "state.json")

        # Day 1: no prior state, always due.
        state = store.load()
        assert is_rebalance_due(state, today=date(2026, 1, 1), hold_days=21) is True
        diff = compute_rebalance_diff(
            current_holdings=state.current_holdings if state else [],
            new_holdings=["SOXX", "SMH"],
        )
        assert diff.enter == ["SMH", "SOXX"]
        new_state = advance_rebalance_state(
            state, today=date(2026, 1, 1), new_sectors=["semiconductor"],
            new_holdings=["SOXX", "SMH"],
        )
        store.save(new_state)

        # Day 5: not due yet.
        state = store.load()
        assert is_rebalance_due(state, today=date(2026, 1, 5), hold_days=21) is False

        # Day 22 (21 days later): due again, top-N has shifted to software.
        state = store.load()
        assert is_rebalance_due(state, today=date(2026, 1, 22), hold_days=21) is True
        diff = compute_rebalance_diff(
            current_holdings=state.current_holdings, new_holdings=["CRM", "MDB"],
        )
        assert diff.enter == ["CRM", "MDB"]
        assert diff.exit == ["SMH", "SOXX"]
        assert diff.hold == []
        final_state = advance_rebalance_state(
            state, today=date(2026, 1, 22), new_sectors=["software"],
            new_holdings=["CRM", "MDB"],
        )
        store.save(final_state)

        confirmed = store.load()
        assert confirmed.rebalance_count == 2
        assert confirmed.current_holdings == ["CRM", "MDB"]
