"""R13-C roadmap item 7: tests for stock_swing.research.trial_registry.

Acceptance: R13-C item 7 ("全trial registry: パラメータ探索の過適合リスクを評価
可能にする") -- verifies trials are durably recorded (survive re-instantiation),
queryable by roadmap_item/script/segment, and that count_trials() gives an
honest multiple-comparisons count.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from stock_swing.research.trial_registry import TrialRecord, TrialRegistry


def _make_trial(**overrides) -> TrialRecord:
    defaults = dict(
        script="r11b_param_search.py",
        roadmap_item="R11-B",
        params={"min_momentum": 0.05, "min_signal_strength": 0.40},
        data_window={"start": "2024-08-15", "end": "2026-08-14"},
        segment="train",
        n_trades=100,
        profit_factor=1.5,
        win_rate=0.6,
        net_pnl=1000.0,
    )
    defaults.update(overrides)
    return TrialRecord(**defaults)


class TestRecordAndListRoundTrip:
    def test_record_then_list_returns_the_trial(self, tmp_path):
        registry = TrialRegistry(path=tmp_path / "trials.jsonl")
        registry.record(_make_trial())

        rows = registry.list_trials()
        assert len(rows) == 1
        assert rows[0]["script"] == "r11b_param_search.py"
        assert rows[0]["params"] == {"min_momentum": 0.05, "min_signal_strength": 0.40}
        assert "recorded_at" in rows[0], "each trial must be timestamped"

    def test_multiple_trials_persist_in_append_order(self, tmp_path):
        registry = TrialRegistry(path=tmp_path / "trials.jsonl")
        for mm in (0.03, 0.05, 0.08):
            registry.record(_make_trial(params={"min_momentum": mm, "min_signal_strength": 0.40}))

        rows = registry.list_trials()
        assert [r["params"]["min_momentum"] for r in rows] == [0.03, 0.05, 0.08]

    def test_registry_reinstantiated_on_same_path_sees_prior_trials(self, tmp_path):
        """Persistence check (testing_standards.md 1-B): a new TrialRegistry
        instance pointed at the same file must see everything a prior
        instance wrote -- the ledger is durable, not in-memory only.
        """
        path = tmp_path / "trials.jsonl"
        TrialRegistry(path=path).record(_make_trial())

        reloaded = TrialRegistry(path=path)
        assert reloaded.count_trials() == 1


class TestMissingLedgerFileFallback:
    def test_list_trials_on_nonexistent_ledger_returns_empty_list(self, tmp_path):
        registry = TrialRegistry(path=tmp_path / "does_not_exist.jsonl")
        assert registry.list_trials() == []

    def test_count_trials_on_nonexistent_ledger_returns_zero(self, tmp_path):
        registry = TrialRegistry(path=tmp_path / "does_not_exist.jsonl")
        assert registry.count_trials() == 0

    def test_constructor_creates_parent_directory(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c" / "trials.jsonl"
        TrialRegistry(path=nested)  # should not raise
        assert nested.parent.is_dir()


class TestFilteringByRoadmapItemScriptSegment:
    def test_list_trials_filters_by_roadmap_item(self, tmp_path):
        registry = TrialRegistry(path=tmp_path / "trials.jsonl")
        registry.record(_make_trial(roadmap_item="R11-B"))
        registry.record(_make_trial(roadmap_item="R13-D-phase1"))

        r11b_only = registry.list_trials(roadmap_item="R11-B")
        assert len(r11b_only) == 1
        assert r11b_only[0]["roadmap_item"] == "R11-B"

    def test_list_trials_filters_by_script(self, tmp_path):
        registry = TrialRegistry(path=tmp_path / "trials.jsonl")
        registry.record(_make_trial(script="r11b_param_search.py"))
        registry.record(_make_trial(script="r11c_candidate_backtest.py"))

        filtered = registry.list_trials(script="r11c_candidate_backtest.py")
        assert len(filtered) == 1
        assert filtered[0]["script"] == "r11c_candidate_backtest.py"

    def test_list_trials_filters_by_segment(self, tmp_path):
        registry = TrialRegistry(path=tmp_path / "trials.jsonl")
        registry.record(_make_trial(segment="train"))
        registry.record(_make_trial(segment="validation"))
        registry.record(_make_trial(segment="holdout"))

        holdout_only = registry.list_trials(segment="holdout")
        assert len(holdout_only) == 1
        assert holdout_only[0]["segment"] == "holdout"

    def test_filters_compose_with_logical_and(self, tmp_path):
        registry = TrialRegistry(path=tmp_path / "trials.jsonl")
        registry.record(_make_trial(roadmap_item="R11-B", segment="train"))
        registry.record(_make_trial(roadmap_item="R11-B", segment="validation"))
        registry.record(_make_trial(roadmap_item="R13-D-phase1", segment="train"))

        matched = registry.list_trials(roadmap_item="R11-B", segment="train")
        assert len(matched) == 1


class TestCountTrialsMultipleComparisonsDisclosure:
    def test_count_trials_reflects_full_grid_search_size(self, tmp_path):
        """This is the core acceptance behavior: after a 4x4=16-point grid
        search (mirroring r11b_param_search.py's actual MOMENTUM_GRID x
        STRENGTH_GRID), count_trials() must report 16, so a reader of the
        eventual "winner" result can see how many combinations were tried
        (the honest multiple-comparisons count the module docstring
        motivates).
        """
        registry = TrialRegistry(path=tmp_path / "trials.jsonl")
        momentum_grid = [0.03, 0.05, 0.08, 0.12]
        strength_grid = [0.30, 0.40, 0.50, 0.60]
        for mm in momentum_grid:
            for ss in strength_grid:
                registry.record(_make_trial(params={"min_momentum": mm, "min_signal_strength": ss}))

        assert registry.count_trials(roadmap_item="R11-B") == 16

    def test_count_trials_zero_for_unknown_roadmap_item(self, tmp_path):
        registry = TrialRegistry(path=tmp_path / "trials.jsonl")
        registry.record(_make_trial(roadmap_item="R11-B"))
        assert registry.count_trials(roadmap_item="R99-nonexistent") == 0


class TestWinnersQuery:
    def test_winners_returns_only_selected_as_winner_true(self, tmp_path):
        registry = TrialRegistry(path=tmp_path / "trials.jsonl")
        registry.record(_make_trial(params={"min_momentum": 0.03}, selected_as_winner=False))
        registry.record(_make_trial(params={"min_momentum": 0.05}, selected_as_winner=True))
        registry.record(_make_trial(params={"min_momentum": 0.08}, selected_as_winner=False))

        winners = registry.winners(roadmap_item="R11-B")
        assert len(winners) == 1
        assert winners[0]["params"]["min_momentum"] == 0.05

    def test_winners_empty_when_no_trial_marked(self, tmp_path):
        registry = TrialRegistry(path=tmp_path / "trials.jsonl")
        registry.record(_make_trial(selected_as_winner=False))
        assert registry.winners() == []


class TestOptionalFieldsAndSerialization:
    def test_extra_field_included_when_provided(self, tmp_path):
        registry = TrialRegistry(path=tmp_path / "trials.jsonl")
        registry.record(_make_trial(extra={"walk_forward_split": "2025-10-08"}))
        rows = registry.list_trials()
        assert rows[0]["extra"] == {"walk_forward_split": "2025-10-08"}

    def test_extra_field_omitted_when_empty(self, tmp_path):
        registry = TrialRegistry(path=tmp_path / "trials.jsonl")
        registry.record(_make_trial())
        rows = registry.list_trials()
        assert "extra" not in rows[0], (
            "empty extra dict should not bloat every ledger line with a "
            "redundant empty object"
        )

    def test_profit_factor_can_be_the_string_inf(self, tmp_path):
        """profit_factor is float | str because summarize()-style helpers
        elsewhere in this codebase (r11_backtest_engine.summarize) report
        "inf" as a string when gross_loss == 0 -- the registry must accept
        that without coercion or crashing.
        """
        registry = TrialRegistry(path=tmp_path / "trials.jsonl")
        registry.record(_make_trial(profit_factor="inf"))
        rows = registry.list_trials()
        assert rows[0]["profit_factor"] == "inf"

    def test_default_segment_is_full(self, tmp_path):
        registry = TrialRegistry(path=tmp_path / "trials.jsonl")
        trial = TrialRecord(
            script="x.py", roadmap_item="R13-D-phase1",
            params={}, data_window={"start": "2024-01-01", "end": "2024-12-31"},
        )
        registry.record(trial)
        assert registry.list_trials()[0]["segment"] == "full"
