"""Tests for P3-E: trade attribution dataset."""
from __future__ import annotations

from pathlib import Path


def test_outcome_label_logic() -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
    from build_trade_attribution_dataset import outcome_label

    assert outcome_label(0.06) == "good"
    assert outcome_label(-0.06) == "bad"
    assert outcome_label(0.01) == "neutral"
    assert outcome_label(None) == "unknown"


def test_enrich_from_decision_uses_trade_fields_when_no_decision() -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
    from build_trade_attribution_dataset import enrich_from_decision

    trade = {
        "strategy_id": "breakout_v1",
        "entry_signal_strength": 0.85,
        "strategy_version_id": "bm-v1",
    }
    result = enrich_from_decision(trade, None)
    assert result["entry_strategy_id"] == "breakout_v1"
    assert result["entry_signal_strength"] == 0.85
