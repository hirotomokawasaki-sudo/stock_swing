from types import SimpleNamespace

from stock_swing.cli.paper_demo import _select_intraday_candidate_symbols


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
