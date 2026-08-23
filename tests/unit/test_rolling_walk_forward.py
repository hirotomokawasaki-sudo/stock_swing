"""R13-C roadmap item 6: tests for stock_swing.research.rolling_walk_forward.

Acceptance: R13-C item 6 ("rolling walk-forward + embargo") -- verifies
multiple non-overlapping test windows are generated across the date range,
embargo gaps exclude trades from both train and test, and boundary/invalid
inputs fail closed with clear errors rather than silently returning
misleading splits.
"""
from __future__ import annotations

import pytest

from stock_swing.research.rolling_walk_forward import (
    RollSplit,
    generate_rolling_splits,
    partition_trades_by_roll,
)


def _make_dates(n: int, start_year: int = 2024) -> list[str]:
    """Simple sequential YYYY-MM-DD date strings (not calendar-accurate
    across month boundaries beyond ~28 days, but string-sortable and
    unique, which is all generate_rolling_splits()/partition_trades_by_roll()
    require -- consistent with r11_backtest_engine's own use of raw date
    strings rather than datetime objects for trade partitioning).
    """
    dates = []
    day = 1
    month = 1
    year = start_year
    for _ in range(n):
        dates.append(f"{year:04d}-{month:02d}-{day:02d}")
        day += 1
        if day > 28:
            day = 1
            month += 1
            if month > 12:
                month = 1
                year += 1
    return dates


class TestGenerateRollingSplitsBasicShape:
    def test_returns_n_rolls_splits_for_sufficient_history(self):
        dates = _make_dates(1000)
        splits = generate_rolling_splits(dates, n_rolls=4, train_frac=0.5, test_frac=0.15, embargo_days=20)
        assert len(splits) == 4
        assert all(isinstance(s, RollSplit) for s in splits)

    def test_roll_indices_are_sequential_starting_at_zero(self):
        dates = _make_dates(1000)
        splits = generate_rolling_splits(dates, n_rolls=3, train_frac=0.5, test_frac=0.15, embargo_days=20)
        assert [s.roll_index for s in splits] == [0, 1, 2]

    def test_train_window_precedes_test_window_within_each_roll(self):
        dates = _make_dates(1000)
        splits = generate_rolling_splits(dates, n_rolls=4, train_frac=0.5, test_frac=0.15, embargo_days=20)
        for s in splits:
            assert s.train[1] < s.test[0], (
                f"roll {s.roll_index}: train end {s.train[1]} must precede "
                f"test start {s.test[0]}"
            )

    def test_test_windows_advance_across_rolls(self):
        """Later rolls' test windows should start later in the date range
        (rolling-origin behavior) -- not all rolls testing the same window.
        """
        dates = _make_dates(1000)
        splits = generate_rolling_splits(dates, n_rolls=4, train_frac=0.5, test_frac=0.15, embargo_days=20)
        test_starts = [s.test[0] for s in splits]
        assert test_starts == sorted(test_starts)
        assert len(set(test_starts)) == len(test_starts), "each roll should test a distinct window"


class TestEmbargoGapExcludesLeakage:
    def test_embargo_range_sits_strictly_between_train_and_test(self):
        dates = _make_dates(1000)
        splits = generate_rolling_splits(dates, n_rolls=2, train_frac=0.5, test_frac=0.15, embargo_days=20)
        for s in splits:
            assert s.embargo is not None
            assert s.train[1] < s.embargo[0]
            assert s.embargo[1] < s.test[0]

    def test_embargo_is_none_when_embargo_days_is_zero(self):
        dates = _make_dates(1000)
        splits = generate_rolling_splits(dates, n_rolls=2, train_frac=0.5, test_frac=0.15, embargo_days=0)
        assert splits
        for s in splits:
            assert s.embargo is None

    def test_zero_embargo_leaves_no_gap_between_train_and_test(self):
        """With embargo_days=0, test should start immediately after train
        (no dropped dates), confirming embargo_days=0 is a true no-op.
        """
        dates = _make_dates(200)
        splits = generate_rolling_splits(dates, n_rolls=1, train_frac=0.5, test_frac=0.15, embargo_days=0)
        assert len(splits) == 1
        s = splits[0]
        train_end_idx = dates.index(s.train[1])
        test_start_idx = dates.index(s.test[0])
        assert test_start_idx == train_end_idx + 1


class TestPartitionTradesByRollExcludesEmbargoFromBothSides:
    def test_trade_entered_during_embargo_excluded_from_train_and_test(self):
        dates = _make_dates(200)
        splits = generate_rolling_splits(dates, n_rolls=1, train_frac=0.5, test_frac=0.15, embargo_days=20)
        roll = splits[0]

        embargo_date = roll.embargo[0]
        trades = [
            {"entry_date": roll.train[0], "pnl": 100},
            {"entry_date": embargo_date, "pnl": 999},
            {"entry_date": roll.test[0], "pnl": -50},
        ]
        parts = partition_trades_by_roll(trades, roll)
        assert len(parts["train"]) == 1
        assert len(parts["test"]) == 1
        assert len(parts["embargo"]) == 1
        assert parts["embargo"][0]["pnl"] == 999
        # Critically: the embargoed trade must not leak into train or test.
        assert all(t["pnl"] != 999 for t in parts["train"])
        assert all(t["pnl"] != 999 for t in parts["test"])

    def test_partition_uses_custom_date_key(self):
        dates = _make_dates(200)
        splits = generate_rolling_splits(dates, n_rolls=1, train_frac=0.5, test_frac=0.15, embargo_days=0)
        roll = splits[0]
        trades = [{"signal_date": roll.train[0], "pnl": 1}]
        parts = partition_trades_by_roll(trades, roll, date_key="signal_date")
        assert len(parts["train"]) == 1

    def test_trade_missing_date_key_is_silently_skipped(self):
        dates = _make_dates(200)
        splits = generate_rolling_splits(dates, n_rolls=1, train_frac=0.5, test_frac=0.15, embargo_days=0)
        roll = splits[0]
        trades = [{"pnl": 1}]  # no entry_date at all
        parts = partition_trades_by_roll(trades, roll)
        assert parts["train"] == []
        assert parts["test"] == []

    def test_trade_outside_all_windows_not_counted_anywhere(self):
        dates = _make_dates(1000)
        splits = generate_rolling_splits(dates, n_rolls=4, train_frac=0.3, test_frac=0.1, embargo_days=20)
        roll = splits[0]  # earliest roll; a trade near the very end of history is outside it
        far_future_trade = {"entry_date": dates[-1], "pnl": 1}
        parts = partition_trades_by_roll([far_future_trade], roll)
        assert parts["train"] == []
        assert parts["test"] == []
        assert parts["embargo"] == []


class TestInvalidInputsFailFast:
    def test_n_rolls_less_than_one_raises(self):
        with pytest.raises(ValueError, match="n_rolls"):
            generate_rolling_splits(_make_dates(500), n_rolls=0)

    def test_train_frac_out_of_range_raises(self):
        with pytest.raises(ValueError, match="train_frac"):
            generate_rolling_splits(_make_dates(500), train_frac=1.5)

    def test_train_frac_zero_raises(self):
        with pytest.raises(ValueError, match="train_frac"):
            generate_rolling_splits(_make_dates(500), train_frac=0.0)

    def test_test_frac_out_of_range_raises(self):
        with pytest.raises(ValueError, match="test_frac"):
            generate_rolling_splits(_make_dates(500), test_frac=0.0)


class TestInsufficientHistoryReturnsEmptyNotCrash:
    def test_too_short_date_range_returns_empty_list(self):
        dates = _make_dates(10)
        splits = generate_rolling_splits(dates, n_rolls=4, train_frac=0.5, test_frac=0.15, embargo_days=20)
        assert splits == []

    def test_exactly_one_full_block_fits_returns_single_roll(self):
        # train_frac=0.5, test_frac=0.15, embargo=0 -> block needs 65% of n
        dates = _make_dates(100)
        splits = generate_rolling_splits(dates, n_rolls=1, train_frac=0.5, test_frac=0.15, embargo_days=0)
        assert len(splits) == 1
