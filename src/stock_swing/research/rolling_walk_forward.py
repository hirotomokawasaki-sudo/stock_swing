"""R13-C roadmap item 6: rolling walk-forward + embargo split generator.

Context (docs/console_improvement_tasks.md R13-C, item 6, previously
unimplemented): every walk-forward evaluation done so far in this codebase
(r11_backtest_engine.py's single midpoint split, r11b_param_search.py's
one-shot 60/20/20 train/validation/holdout) uses exactly ONE fixed split of
the 2-year history. The 2026-08-15 R11-B follow-up review (see
console_improvement_tasks.md's "R11-B付鍘" section) found that a single
split can accidentally hide a real regime-dependent weakness inside one of
its windows (the original front/back-half split averaged over a sharp
mid-2025 correction that a 3-way split later exposed) -- i.e. a single
split's conclusion depends heavily on WHERE the cut happens to land.
Rolling walk-forward with multiple overlapping-window rolls (instead of one
fixed cut) tests whether a result is a stable property of the strategy or
an artifact of one particular split point.

Embargo (the second half of this module's purpose): a naive rolling split
that puts day t in "train" and day t+1 in "test" can leak information when
a strategy holds positions for multiple days (e.g. SimpleExitV2Strategy's
max_hold_days=20) -- a position opened near the end of a train window and
closed early in the immediately-following test window was effectively
"trained on" data adjacent to its own outcome. This module drops an
embargo_days-wide buffer immediately after each train window (before the
paired test window begins) so no trade whose ENTRY falls in the embargo gap
is counted in either window, following the standard purged/embargoed
walk-forward technique (see Marcos Lopez de Prado, "Advances in Financial
Machine Learning", ch. 7 -- cited here for terminology only, this module
does not implement the full "purged k-fold" combinatorial variant, only
the simpler single-embargo-gap rolling-window form appropriate for this
codebase's existing tooling).

Design (deliberately a plain, dependency-light function over date lists --
no pandas, no numpy, matching every other module in scripts/r11_*):
  - Input: a sorted list of trading-day date strings (as already produced
    by every r11_backtest_engine* script's `all_dates`).
  - Output: a list of RollSplit(train, test) tuples of (start, end) date
    string pairs, one per roll, with `embargo_days` calendar positions
    dropped between each train/test pair.
  - Callers partition their OWN trade list by entry_date against each
    roll's train/test date ranges (see partition_trades_by_roll below),
    reusing the exact same "entry_date string comparison" idiom already
    used by r11b_param_search.py's partition_trades().

Usage::

    from stock_swing.research.rolling_walk_forward import (
        generate_rolling_splits, partition_trades_by_roll,
    )

    splits = generate_rolling_splits(all_dates, n_rolls=4, train_frac=0.5,
                                      test_frac=0.15, embargo_days=20)
    for i, roll in enumerate(splits):
        parts = partition_trades_by_roll(trades, roll)
        train_summary = summarize(parts["train"], f"roll{i}_train")
        test_summary = summarize(parts["test"], f"roll{i}_test")
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RollSplit:
    """One rolling walk-forward window pair.

    train/test are each (start_date, end_date) INCLUSIVE date-string pairs.
    embargo is the (start_date, end_date) inclusive range of dates dropped
    between train and test (may be empty when embargo_days == 0).
    """
    roll_index: int
    train: tuple[str, str]
    embargo: tuple[str, str] | None
    test: tuple[str, str]


def generate_rolling_splits(
    all_dates: list[str],
    n_rolls: int = 4,
    train_frac: float = 0.5,
    test_frac: float = 0.15,
    embargo_days: int = 20,
) -> list[RollSplit]:
    """Generate n_rolls overlapping-train, non-overlapping-test rolling
    walk-forward windows with an embargo gap between each train/test pair.

    Each roll's train window is a fixed-length (train_frac * len(all_dates))
    span; successive rolls slide the whole train+embargo+test block forward
    so that the test windows tile the back portion of the date range without
    overlapping each other (standard rolling-origin walk-forward).

    Args:
        all_dates: Sorted ascending list of trading-day date strings
            (e.g. r11_backtest_engine.load_price_data()'s union of dates).
        n_rolls: Number of rolling windows to generate.
        train_frac: Fraction of total dates used for each roll's train
            window (0.0-1.0).
        test_frac: Fraction of total dates used for each roll's test
            window (0.0-1.0).
        embargo_days: Number of trading days immediately after each train
            window to exclude from both train and test (leakage buffer for
            multi-day-hold strategies -- see module docstring).

    Returns:
        List of RollSplit, ordered by roll_index ascending. Returns an
        empty list if all_dates is too short to fit even one full
        train+embargo+test window.

    Raises:
        ValueError: if train_frac or test_frac is not in (0, 1), or if
            n_rolls < 1.
    """
    if n_rolls < 1:
        raise ValueError(f"n_rolls must be >= 1, got {n_rolls}")
    if not (0.0 < train_frac < 1.0):
        raise ValueError(f"train_frac must be in (0, 1), got {train_frac}")
    if not (0.0 < test_frac < 1.0):
        raise ValueError(f"test_frac must be in (0, 1), got {test_frac}")

    n = len(all_dates)
    train_len = int(n * train_frac)
    test_len = int(n * test_frac)

    if train_len < 1 or test_len < 1:
        return []

    block_len = train_len + embargo_days + test_len
    if block_len > n:
        # Not enough history for even one full roll at these fractions.
        return []

    # Slide the test window across the remaining space after the first
    # train+embargo block, spacing rolls evenly across the available range
    # so test windows tile the back portion without overlapping.
    max_start = n - block_len
    if n_rolls == 1:
        starts = [0]
    else:
        step = max_start / (n_rolls - 1) if max_start > 0 else 0
        starts = [round(i * step) for i in range(n_rolls)]

    splits: list[RollSplit] = []
    for roll_index, start in enumerate(starts):
        train_start_idx = start
        train_end_idx = start + train_len - 1
        embargo_start_idx = train_end_idx + 1
        embargo_end_idx = embargo_start_idx + embargo_days - 1
        test_start_idx = embargo_end_idx + 1
        test_end_idx = test_start_idx + test_len - 1

        if test_end_idx >= n:
            continue  # guard against rounding pushing the last roll out of range

        embargo_range: tuple[str, str] | None = None
        if embargo_days > 0:
            embargo_range = (all_dates[embargo_start_idx], all_dates[embargo_end_idx])

        splits.append(RollSplit(
            roll_index=roll_index,
            train=(all_dates[train_start_idx], all_dates[train_end_idx]),
            embargo=embargo_range,
            test=(all_dates[test_start_idx], all_dates[test_end_idx]),
        ))

    return splits


def partition_trades_by_roll(
    trades: list[dict[str, Any]],
    roll: RollSplit,
    date_key: str = "entry_date",
) -> dict[str, list[dict[str, Any]]]:
    """Split trades into {"train": [...], "embargo": [...], "test": [...]}
    for one RollSplit, keyed on each trade's entry_date.

    Trades whose entry_date falls in the embargo gap are placed in their
    own "embargo" bucket (returned for visibility/debugging) -- they must
    NOT be counted in either train or test PF, since they are exactly the
    trades this module's embargo exists to exclude.

    Args:
        trades: List of trade dicts (as produced by any r11_backtest_engine*
            run_backtest*()'s "trades" list), each with a date_key field.
        roll: One RollSplit from generate_rolling_splits().
        date_key: Trade dict key holding the comparable date string
            (default "entry_date", matching every existing backtest
            engine's trade dict shape).

    Returns:
        Dict with "train", "embargo", "test" keys, each a list of trades
        (embargo list is empty when roll.embargo is None).
    """
    train_start, train_end = roll.train
    test_start, test_end = roll.test
    embargo_start, embargo_end = roll.embargo if roll.embargo else (None, None)

    out: dict[str, list[dict[str, Any]]] = {"train": [], "embargo": [], "test": []}
    for t in trades:
        d = t.get(date_key)
        if d is None:
            continue
        if train_start <= d <= train_end:
            out["train"].append(t)
        elif embargo_start is not None and embargo_start <= d <= embargo_end:
            out["embargo"].append(t)
        elif test_start <= d <= test_end:
            out["test"].append(t)
        # trades outside all three ranges (e.g. before train_start or after
        # test_end, when a roll doesn't span the full history) are simply
        # not counted for this roll -- expected for rolls that only cover
        # part of the date range.
    return out
