"""R13-D Phase 3: persistent rebalance-cadence state manager for
SectorRotationStrategy.

Background (docs/console_improvement_tasks.md R13-D Phase 2 design
decision, explicitly deferred to Phase 3): SectorRotationStrategy.generate()
is stateless -- every call emits fresh buy signals for whatever the
CURRENT top-N sectors happen to be, with no memory of when the strategy
last rebalanced. Phase 1's validated backtest (scripts/
r13d_etf_sector_rotation_phase1.py, Sharpe=1.370) only re-evaluated
holdings every `hold_days` (default 21) trading days -- wiring the
stateless strategy directly into paper_demo.py's daily/multiple-per-day
cron cadence would cause it to needlessly reshuffle positions on every run
merely because SectorMomentumFeature recomputed a fresh top-N ranking each
time it is called, which is NOT what was backtested and NOT what Phase 1's
Sharpe number reflects.

This module is a standalone, dependency-light state machine that answers
exactly one question each time it is asked: "is a rebalance due today, and
if so, what changed?" -- following the exact same architectural pattern
already used elsewhere in this codebase for durable cross-run state:
  - CircuitBreakerStore (guardrails/circuit_breaker.py): dataclass +
    JSON-file-backed load()/save() with an atomic tempfile+os.replace write.
  - day_start_snapshot.py: same atomic-write helper shape, one JSON file
    per "current state", overwritten (not appended) each update.

Design (deliberately narrow, matching the "Phase 3 = wiring, not new
research" framing in console_improvement_tasks.md):
  - RebalanceState is a plain dataclass: {last_rebalance_date,
    current_holdings (list of symbols), current_sectors (the top-N sector
    names that produced current_holdings)}.
  - SectorRotationStateStore.load()/save() persist it to a single JSON
    file (overwritten each rebalance, not appended -- unlike the
    append-only shadow-log pattern used by overnight_spillover_shadow.py,
    since this is CURRENT state, not a historical log).
  - is_rebalance_due(state, today, hold_days) is a pure function (no I/O)
    so it is directly unit-testable: returns True when state is None (no
    prior rebalance recorded -- first run always rebalances) or when
    (today - last_rebalance_date) >= hold_days trading-day-equivalent
    calendar days.
  - compute_rebalance_diff(current_holdings, new_holdings) is a pure
    function returning {enter: [...], exit: [...], hold: [...]} so a
    caller (e.g. a future paper_demo.py wiring step, explicitly NOT part
    of this change) can turn the diff into buy/sell CandidateSignals
    without SectorRotationStrategy itself needing to know about state.

NOT wired into paper_demo.py or any production execution path. This module
and SectorRotationStrategy remain safe to import and use standalone (e.g.
from a research/backtest script) without any effect on existing
strategies -- matching the same "safe to import, not wired" boundary
already documented in sector_rotation_strategy.py and
sector_momentum_feature.py's module docstrings. Actually wiring this state
machine into a live cron path is a SEPARATE decision requiring explicit
user approval (same promotion process breakout_momentum_v1/event_swing_v1
went through), not implied by this module's existence.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_HOLD_DAYS = 21  # matches SectorRotationStrategy's Phase 1-validated default
_DEFAULT_STATE_PATH = Path("data/sector_rotation_state.json")


@dataclass(frozen=True)
class RebalanceState:
    """Current sector-rotation holdings state, as of the last rebalance."""
    last_rebalance_date: str          # ISO date string, e.g. "2026-08-24"
    current_sectors: list[str] = field(default_factory=list)   # top-N sector names as of last rebalance
    current_holdings: list[str] = field(default_factory=list)  # member ETF symbols held
    rebalance_count: int = 0          # total rebalances since state was first created

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RebalanceState":
        return cls(
            last_rebalance_date=str(data.get("last_rebalance_date") or ""),
            current_sectors=list(data.get("current_sectors") or []),
            current_holdings=list(data.get("current_holdings") or []),
            rebalance_count=int(data.get("rebalance_count") or 0),
        )


@dataclass(frozen=True)
class RebalanceDiff:
    """Result of comparing current holdings against a freshly computed
    top-N holdings set."""
    enter: list[str] = field(default_factory=list)   # symbols to newly buy
    exit: list[str] = field(default_factory=list)    # symbols to sell (no longer in top-N)
    hold: list[str] = field(default_factory=list)    # symbols unchanged (already held, still in top-N)

    @property
    def is_noop(self) -> bool:
        return not self.enter and not self.exit


def _write_atomic(path: Path, data: dict[str, Any]) -> None:
    """Same atomic tempfile+os.replace idiom as guardrails/day_start_
    snapshot.py's _write_atomic() -- reused here rather than imported
    since that helper is private (underscore-prefixed) to its own module.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


class SectorRotationStateStore:
    """Loads/saves RebalanceState to a single JSON file (overwritten each
    rebalance -- current-state semantics, not an append-only log).
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else _DEFAULT_STATE_PATH

    def load(self) -> RebalanceState | None:
        """Return the persisted state, or None if no state file exists yet
        (first-ever run) or the file is corrupt/unreadable (fail-safe: a
        missing/corrupt state file is treated identically to "no prior
        rebalance", which is the SAFE direction -- it forces a fresh
        rebalance rather than silently trusting stale/garbage state).
        """
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return RebalanceState.from_dict(data)

    def save(self, state: RebalanceState) -> None:
        _write_atomic(self.path, state.to_dict())


def is_rebalance_due(
    state: RebalanceState | None,
    today: date,
    hold_days: int = DEFAULT_HOLD_DAYS,
) -> bool:
    """Return True if a rebalance should run today.

    Args:
        state: Persisted state from SectorRotationStateStore.load(), or
            None if this is the first-ever evaluation (always due).
        today: The calendar date to evaluate against (caller-supplied so
            this stays a pure function -- no datetime.now() inside, unlike
            most of this codebase's other modules that freeze datetime.now
            for backtesting; this function takes the date explicitly
            instead so it needs no monkeypatching at all to test).
        hold_days: Minimum CALENDAR days between rebalances (documented
            simplification: Phase 1's backtest used 21 TRADING days;
            approximating with 21 calendar days is deliberately slightly
            more frequent than a strict trading-day count would be, which
            is the conservative direction for a state gate whose failure
            mode is "rebalances a bit too often" rather than "misses a
            scheduled rebalance entirely" -- documented limitation, exact
            trading-day-calendar accounting would need a market calendar
            dependency this module deliberately avoids per its
            "dependency-light" design goal).

    Returns:
        True if state is None (no prior rebalance recorded) or if
        (today - last_rebalance_date) >= hold_days. False otherwise.
    """
    if state is None or not state.last_rebalance_date:
        return True
    try:
        last_date = date.fromisoformat(state.last_rebalance_date)
    except ValueError:
        # Corrupt/unparseable date string: fail toward rebalancing (same
        # fail-safe direction as SectorRotationStateStore.load()'s corrupt-
        # file handling above) rather than silently never rebalancing again.
        return True
    return (today - last_date).days >= hold_days


def compute_rebalance_diff(
    current_holdings: list[str],
    new_holdings: list[str],
) -> RebalanceDiff:
    """Compare current vs. newly computed top-N holdings.

    Pure function: no I/O, no state mutation. A caller wiring this into an
    execution path (NOT this module's responsibility -- see module
    docstring) would turn `enter` into buy CandidateSignals and `exit`
    into sell CandidateSignals for the affected symbols.

    Args:
        current_holdings: Symbols held as of the last rebalance (from
            RebalanceState.current_holdings).
        new_holdings: Symbols SectorRotationStrategy.generate() would
            select right now (deduplicated member ETFs of the current
            top-N sectors).

    Returns:
        RebalanceDiff with enter/exit/hold partitions. Order within each
        list is not guaranteed -- callers needing stable ordering should
        sort explicitly.
    """
    current_set = set(current_holdings)
    new_set = set(new_holdings)
    return RebalanceDiff(
        enter=sorted(new_set - current_set),
        exit=sorted(current_set - new_set),
        hold=sorted(current_set & new_set),
    )


def advance_rebalance_state(
    prior_state: RebalanceState | None,
    today: date,
    new_sectors: list[str],
    new_holdings: list[str],
) -> RebalanceState:
    """Build the next RebalanceState after a rebalance has been decided and
    executed (or, for research/dry-run use, simulated).

    This function does NOT check is_rebalance_due() itself -- callers must
    call that first and only invoke this when a rebalance is actually due,
    so the "was a rebalance due" decision and "what does post-rebalance
    state look like" concerns stay separated and independently testable.

    Args:
        prior_state: The state before this rebalance (None on first run).
        today: The date this rebalance is being recorded for.
        new_sectors: The top-N sector names selected this rebalance.
        new_holdings: The member ETF symbols now held.

    Returns:
        A new RebalanceState with rebalance_count incremented from
        prior_state (starting at 1 for the first-ever rebalance).
    """
    prior_count = prior_state.rebalance_count if prior_state is not None else 0
    return RebalanceState(
        last_rebalance_date=today.isoformat(),
        current_sectors=list(new_sectors),
        current_holdings=list(new_holdings),
        rebalance_count=prior_count + 1,
    )


def current_market_date() -> date:
    """UTC calendar date "today", for production call sites. Kept as a
    thin, separately-mockable wrapper (rather than inlining
    datetime.now(timezone.utc).date() at every call site) so tests can
    patch this one function instead of monkeypatching the datetime module,
    matching the plain-function testability goal already used by
    is_rebalance_due()/compute_rebalance_diff() elsewhere in this module.
    """
    return datetime.now(timezone.utc).date()
