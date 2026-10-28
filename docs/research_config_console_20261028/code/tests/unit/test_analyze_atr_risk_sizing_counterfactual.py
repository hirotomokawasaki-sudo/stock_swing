from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from analyze_atr_risk_sizing_counterfactual import (  # noqa: E402
    Variant,
    compute_atr_pct_at_entry,
    load_cached_bars,
    load_state,
    rescale_trade,
    summarize,
)


def _bars(n: int = 20) -> dict[str, dict[str, float]]:
    rows = {}
    for i in range(1, n + 1):
        rows[f"2026-01-{i:02d}"] = {
            "open": 100.0,
            "high": 102.0,
            "low": 98.0,
            "close": 100.0,
        }
    return rows


def test_compute_atr_pct_uses_only_completed_pre_entry_bars():
    bars = _bars()
    bars["2026-01-20"] = {"open": 100, "high": 200, "low": 1, "close": 100}
    atr_pct = compute_atr_pct_at_entry(bars, "2026-01-20", window=14)
    assert atr_pct == pytest.approx(0.04), "entry-day range must not leak into ATR"


def test_compute_atr_pct_returns_none_when_history_is_insufficient():
    assert compute_atr_pct_at_entry(_bars(10), "2026-01-20", window=14) is None


def test_rescale_trade_reduces_only_and_scales_pnl_linearly():
    trade = {"symbol": "NVDA", "qty": 100, "entry_price": 100.0, "pnl": -1000.0,
             "exit_time": "2026-08-20T00:00:00Z", "return_pct": -0.10}
    row = rescale_trade(trade, atr_pct=0.04, baseline_equity=1_000_000,
                        variant=Variant("P0", 0.003, 2.0, True))
    assert row["target_qty"] == 375
    assert row["counterfactual_qty"] == 100, "reduce-only mode must never increase size"
    assert row["counterfactual_pnl"] == pytest.approx(-1000.0)


def test_rescale_trade_caps_high_risk_position():
    trade = {"symbol": "LRCX", "qty": 1000, "entry_price": 100.0, "pnl": -10000.0,
             "exit_time": "2026-08-20T00:00:00Z", "return_pct": -0.10}
    row = rescale_trade(trade, atr_pct=0.04, baseline_equity=1_000_000,
                        variant=Variant("P0", 0.003, 2.0, True))
    assert row["counterfactual_qty"] == 375
    assert row["counterfactual_pnl"] == pytest.approx(-3750.0)
    assert row["pnl_diff"] == pytest.approx(6250.0)


def test_summarize_reports_pf_tail_and_drawdown():
    rows = [
        {"exit_time": "2026-01-01", "actual_pnl": -100.0, "counterfactual_pnl": -50.0,
         "affected": True, "gap_through": True, "pnl_diff": 50.0},
        {"exit_time": "2026-01-02", "actual_pnl": 100.0, "counterfactual_pnl": 100.0,
         "affected": False, "gap_through": False, "pnl_diff": 0.0},
    ]
    summary = summarize(rows)
    assert summary["actual_pf"] == pytest.approx(1.0)
    assert summary["counterfactual_pf"] == pytest.approx(2.0)
    assert summary["counterfactual_loss_cvar_5"] == pytest.approx(-50.0)


def test_load_state_missing_equity_fails_closed(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"trades": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="baseline_equity"):
        load_state(path)


def test_load_cached_bars_corrupt_file_returns_empty(tmp_path):
    (tmp_path / "NVDA.json").write_text("not json", encoding="utf-8")
    assert load_cached_bars("NVDA", tmp_path) == {}
