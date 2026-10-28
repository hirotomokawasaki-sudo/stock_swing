"""Tests for P3-C: run_id and correlation_id."""
from __future__ import annotations

from types import SimpleNamespace

from stock_swing.core.run_context import RunContext, attach_run_context


def test_run_context_has_unique_traceable_id() -> None:
    a = RunContext.create("paper_demo")
    b = RunContext.create("paper_demo")
    assert a.run_id.startswith("paper_demo-")
    assert a.run_id != b.run_id
    assert a.as_dict()["command"] == "paper_demo"


def test_run_context_id_is_stable_within_instance() -> None:
    ctx = RunContext.create("reconcile_orders")
    assert ctx.run_id == ctx.run_id


def test_attach_run_context_sets_run_id_on_decisions() -> None:
    ctx = RunContext.create("paper_demo")
    decisions = [
        SimpleNamespace(evidence={"symbol": "AAPL"}),
        SimpleNamespace(evidence={"symbol": "MSFT"}),
    ]
    attach_run_context(decisions, ctx)
    for d in decisions:
        assert d.evidence.get("run_id") == ctx.run_id
        assert "run_started_at" in d.evidence


def test_attach_run_context_does_not_overwrite_existing() -> None:
    ctx = RunContext.create("paper_demo")
    decisions = [SimpleNamespace(evidence={"run_id": "existing-id"})]
    attach_run_context(decisions, ctx)
    assert decisions[0].evidence["run_id"] == "existing-id"
