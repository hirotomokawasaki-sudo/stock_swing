"""R13-C roadmap item 7: full parameter-trial registry.

Context (docs/console_improvement_tasks.md R13-C, item 7, previously
unimplemented): every ad-hoc backtest/grid-search script in scripts/
(r11b_param_search.py, r11c_candidate_backtest.py, r11c2_regime_filter_
backtest.py, r13d_etf_sector_rotation_phase1.py, etc.) has printed its
results to stdout and optionally saved a single JSON snapshot, but there
has been no durable, queryable record of EVERY trial ever run -- which
parameter combinations were tried, on what data window, with what result,
and whether a human ever acted on it. That makes it impossible to answer
"how many parameter combinations did we search before finding this one"
(the standard multiple-comparisons/overfitting question), or to notice if
the same negative result is being re-discovered by a different script
months later.

This module is a minimal, dependency-light trial ledger, modeled directly
on stock_swing.experiments.experiment_registry.ExperimentRegistry's
existing pattern (atomic JSON write + append-only JSONL index) so it reuses
an already-reviewed persistence idiom rather than inventing a new one.

Design (deliberately narrow scope, matching R13-C's "research-only, no
production impact" framing):
  - Append-only JSONL ledger (data/research/trial_registry.jsonl) -- one
    line per trial. Never mutated after write (immutable audit trail).
  - A trial is any single backtest/grid-search RUN with a specific
    parameter set, NOT a whole grid search (a grid search calling this
    registry once per grid point is the intended usage -- see
    scripts/r11b_param_search.py's MOMENTUM_GRID x STRENGTH_GRID loop for
    an existing example of the granularity this should be called at).
  - Deliberately does NOT try to auto-detect p-hacking or auto-reject
    trials; it is observability, not a gate (same "recommendation-only"
    posture already used elsewhere in R13 -- see
    docs/console_improvement_tasks.md's R13 "やらないこと" section).
  - No I/O coupling to production trading state (pnl_state.json,
    circuit_breaker.json, etc.) -- reads/writes only its own ledger file.

Usage (typical call site, e.g. inside a grid-search loop)::

    from stock_swing.research.trial_registry import TrialRecord, TrialRegistry

    registry = TrialRegistry()
    registry.record(TrialRecord(
        script="r11b_param_search.py",
        roadmap_item="R11-B",
        params={"min_momentum": 0.05, "min_signal_strength": 0.40},
        data_window={"start": "2024-08-15", "end": "2026-08-14"},
        segment="train",
        n_trades=732,
        profit_factor=1.776,
        win_rate=0.624,
        net_pnl=160953.0,
        notes="production default",
    ))

Querying::

    registry.count_trials(roadmap_item="R11-B")   # -> int
    registry.list_trials(roadmap_item="R11-B")     # -> list[dict]
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_LEDGER_PATH = Path("data/research/trial_registry.jsonl")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class TrialRecord:
    """One parameter-search trial (a single backtest run with fixed params).

    Fields are deliberately generic (not tied to any one strategy's
    parameter names) so the SAME registry can log R11-B momentum/strength
    grid points, R11-C candidate-filter variants, R13-D sector-rotation
    parameter sweeps, etc., without a new schema per script.
    """
    script: str                      # e.g. "r11b_param_search.py"
    roadmap_item: str                # e.g. "R11-B", "R13-D-phase1"
    params: dict[str, Any]           # the parameter combination tried
    data_window: dict[str, str]      # {"start": ..., "end": ...}
    segment: str = "full"            # "train" | "validation" | "holdout" | "full"
    n_trades: int | None = None
    profit_factor: float | str | None = None   # float, or "inf"
    win_rate: float | None = None
    net_pnl: float | None = None
    sharpe: float | None = None
    max_drawdown_pct: float | None = None
    selected_as_winner: bool = False  # True if this trial was the one a
                                       # human/script ultimately acted on
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "recorded_at": _utc_now_iso(),
            "script": self.script,
            "roadmap_item": self.roadmap_item,
            "params": self.params,
            "data_window": self.data_window,
            "segment": self.segment,
            "n_trades": self.n_trades,
            "profit_factor": self.profit_factor,
            "win_rate": self.win_rate,
            "net_pnl": self.net_pnl,
            "sharpe": self.sharpe,
            "max_drawdown_pct": self.max_drawdown_pct,
            "selected_as_winner": self.selected_as_winner,
            "notes": self.notes,
        }
        if self.extra:
            payload["extra"] = self.extra
        return payload


class TrialRegistry:
    """Append-only ledger of backtest/grid-search trials.

    Mirrors stock_swing.experiments.experiment_registry.ExperimentRegistry's
    atomic-write + append-only-JSONL pattern (same fsync-then-rename idiom
    for the (rarely-written) latest-count cache, plain append for the
    ledger itself since trials are never mutated after being recorded).
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else _DEFAULT_LEDGER_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, trial: TrialRecord) -> None:
        """Append one trial to the ledger. Never overwrites prior entries."""
        self._append_jsonl(self.path, trial.to_dict())

    def list_trials(
        self,
        roadmap_item: str | None = None,
        script: str | None = None,
        segment: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return all recorded trials, optionally filtered.

        Returns an empty list (not an error) if the ledger file does not
        exist yet -- a fresh registry with zero trials is a valid, expected
        state, not a failure.
        """
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if roadmap_item is not None and row.get("roadmap_item") != roadmap_item:
                continue
            if script is not None and row.get("script") != script:
                continue
            if segment is not None and row.get("segment") != segment:
                continue
            rows.append(row)
        return rows

    def count_trials(
        self,
        roadmap_item: str | None = None,
        script: str | None = None,
        segment: str | None = None,
    ) -> int:
        """Total trial count matching the given filters.

        This is the number that answers "how many parameter combinations
        were searched before this result was picked" -- the standard
        multiple-comparisons disclosure this module exists to make
        possible (see module docstring).
        """
        return len(self.list_trials(roadmap_item=roadmap_item, script=script, segment=segment))

    def winners(self, roadmap_item: str | None = None) -> list[dict[str, Any]]:
        """Return only trials marked selected_as_winner=True."""
        return [
            row for row in self.list_trials(roadmap_item=roadmap_item)
            if row.get("selected_as_winner")
        ]

    @staticmethod
    def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
