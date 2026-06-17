from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from stock_swing.cli.paper_demo import (
    _filter_sells_outside_regular_hours,
    _prefilter_actionable_buys_for_submission,
    _select_intraday_candidate_symbols,
)


def _signal(symbol: str, strength: float, confidence: float = 0.7):
    return SimpleNamespace(symbol=symbol, signal_strength=strength, confidence=confidence)


def test_select_intraday_candidates_sorts_by_strength_then_confidence():
    signals = [
        _signal('AMD', 0.70, 0.80),
        _signal('NVDA', 0.90, 0.60),
        _signal('AVGO', 0.90, 0.85),
    ]

    assert _select_intraday_candidate_symbols(signals) == ['AVGO', 'NVDA', 'AMD']


def test_select_intraday_candidates_deduplicates_symbols():
    signals = [
        _signal('AMD', 0.60),
        _signal('AMD', 0.95),
        _signal('NVDA', 0.80),
    ]

    assert _select_intraday_candidate_symbols(signals) == ['AMD', 'NVDA']


def test_select_intraday_candidates_respects_limit():
    signals = [
        _signal('AVGO', 0.95),
        _signal('NVDA', 0.90),
        _signal('AMD', 0.85),
    ]

    assert _select_intraday_candidate_symbols(signals, limit=2) == ['AVGO', 'NVDA']


def test_select_intraday_candidates_returns_empty_for_no_signals():
    assert _select_intraday_candidate_symbols([], limit=5) == []


def test_prefilter_actionable_buys_drops_zero_share_buys_before_submission():
    sell = SimpleNamespace(
        decision_id="sell-1",
        symbol="NBIS",
        proposed_order=SimpleNamespace(side="sell"),
        evidence={},
    )
    buy_blocked = SimpleNamespace(
        decision_id="buy-1",
        symbol="AMD",
        proposed_order=SimpleNamespace(side="buy"),
        evidence={"market_regime": "neutral"},
    )
    buy_allowed = SimpleNamespace(
        decision_id="buy-2",
        symbol="NVDA",
        proposed_order=SimpleNamespace(side="buy"),
        evidence={"market_regime": "neutral"},
    )

    class FakeExecutor:
        def _calculate_position_size(self, decision, market_regime="neutral"):
            if decision.decision_id == "buy-1":
                return 0, {"skip_reason": "insufficient_remaining_exposure"}
            return 12, {"skip_reason": None, "shares_by_exposure": 12}

    filtered, preview_cache, skipped_by_reason, skipped_symbols = _prefilter_actionable_buys_for_submission(
        [sell, buy_blocked, buy_allowed],
        FakeExecutor(),
    )

    assert filtered == [sell, buy_allowed]
    assert preview_cache["buy-1"][0] == 0
    assert preview_cache["buy-2"][0] == 12
    assert skipped_by_reason == {"insufficient_remaining_exposure": 1}
    assert skipped_symbols == [("AMD", "insufficient_remaining_exposure")]


def test_filter_sells_outside_regular_hours_defers_non_catastrophic_sell(monkeypatch):
    monkeypatch.delenv("PAPER_DEMO_ALLOW_OFFHOURS_SELLS", raising=False)
    moderate_sell = SimpleNamespace(
        action="sell",
        symbol="AMD",
        evidence={"notes": ["Breakeven stop triggered: return -7.62% <= 0%"]},
    )
    buy = SimpleNamespace(action="buy", symbol="NVDA", evidence={})

    filtered, deferred = _filter_sells_outside_regular_hours(
        [moderate_sell, buy],
        now=datetime(2026, 6, 6, 10, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
    )

    assert filtered == [buy]
    assert deferred == [("AMD", "breakeven_stop", -0.0762)]


def test_filter_sells_outside_regular_hours_keeps_catastrophic_sell(monkeypatch):
    monkeypatch.delenv("PAPER_DEMO_ALLOW_OFFHOURS_SELLS", raising=False)
    catastrophic_sell = SimpleNamespace(
        action="sell",
        symbol="MU",
        evidence={"notes": ["Breakeven stop triggered: return -12.25% <= 0%"]},
    )

    filtered, deferred = _filter_sells_outside_regular_hours(
        [catastrophic_sell],
        now=datetime(2026, 6, 6, 10, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
    )

    assert filtered == [catastrophic_sell]
    assert deferred == []
