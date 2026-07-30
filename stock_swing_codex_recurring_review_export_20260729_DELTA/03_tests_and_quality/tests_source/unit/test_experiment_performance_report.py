import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from report_experiment_performance import summarize


def test_summarize_groups_and_computes_pf() -> None:
    rows = [
        {"experiment_id": "exp-1", "experiment_bucket": "control", "strategy_version": "s1", "prompt_version": "p1", "realized_pnl": "100"},
        {"experiment_id": "exp-1", "experiment_bucket": "control", "strategy_version": "s1", "prompt_version": "p1", "realized_pnl": "-50"},
        {"experiment_id": "exp-1", "experiment_bucket": "test", "strategy_version": "s2", "prompt_version": "p1", "realized_pnl": "200"},
    ]
    summary = summarize(rows, ["experiment_id", "experiment_bucket", "strategy_version", "prompt_version"])
    assert len(summary) == 2
    control = next(r for r in summary if r["experiment_bucket"] == "control")
    assert control["profit_factor"] == pytest.approx(2.0)
    assert control["trades"] == 2


def test_summarize_empty_rows() -> None:
    result = summarize([], ["experiment_id"])
    assert result == []
