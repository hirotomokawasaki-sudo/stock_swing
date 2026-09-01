"""Unit tests for lot_level_exit_diagnostic.py (2026-09-01 shadow diagnostic).

Regression / incident basis: 2026-08-31 19:55 UTC, NOW opened a 385-share lot
at $148.84 while an existing 15-share lot (opened 2026-08-12 @ $125.00,
peak_price=$148.44, individually +18.75% peak return) was still open.
SimpleExitV2Strategy.generate() only ever evaluates the qty-weighted blended
position (peak_return collapses to ~+0.6%), so the old lot's trailing-stop
protection becomes invisible at the symbol level. Identified 2026-09-01 during
a user-requested review of "positions with unrealized gains that never sell".
"""

from datetime import datetime, timedelta, timezone

import pytest

from stock_swing.risk.lot_level_exit_diagnostic import (
    LotLevelExitDiagnosticConfig,
    evaluate_lot_level_discrepancies,
    log_shadow,
)
from stock_swing.strategy_engine.base_strategy import CandidateSignal
from stock_swing.strategy_engine.simple_exit_v2_strategy import SimpleExitV2Strategy


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _lot(trade_id, symbol, qty, entry_price, peak_price, entry_signal_strength, days_ago):
    return {
        "trade_id": trade_id,
        "symbol": symbol,
        "qty": qty,
        "entry_price": entry_price,
        "peak_price": peak_price,
        "entry_signal_strength": entry_signal_strength,
        "entry_time": _iso(days_ago),
        "status": "open",
    }


def _staged_strategy(**overrides) -> SimpleExitV2Strategy:
    """Mirror config/strategy/simple_exit_v2.yaml's staged trailing setup
    (same levels used in production) unless overridden.
    """
    defaults = dict(
        stop_loss_pct=-0.07,
        breakeven_activation_pct=0.05,
        trailing_activation_pct=0.08,
        trailing_stop_pct=0.04,
        staged_trailing_enabled=True,
        staged_trailing_levels=[
            {"activation_pct": 0.05, "trailing_stop_pct": 0.035},
            {"activation_pct": 0.08, "trailing_stop_pct": 0.03},
            {"activation_pct": 0.12, "trailing_stop_pct": 0.025},
        ],
        max_hold_days=20,
        min_hold_days_enabled=True,
        min_hold_days=1,
    )
    defaults.update(overrides)
    return SimpleExitV2Strategy(**defaults)


# ── Config tests ─────────────────────────────────────────────────────────

def test_config_from_env_defaults(monkeypatch):
    monkeypatch.delenv("LOT_LEVEL_EXIT_DIAGNOSTIC_DISABLED", raising=False)
    monkeypatch.delenv("LOT_LEVEL_EXIT_DIAGNOSTIC_MIN_LOTS", raising=False)
    cfg = LotLevelExitDiagnosticConfig.from_env()
    assert cfg.is_enabled() is True
    assert cfg.min_lots == 2


def test_config_from_env_disabled(monkeypatch):
    monkeypatch.setenv("LOT_LEVEL_EXIT_DIAGNOSTIC_DISABLED", "true")
    cfg = LotLevelExitDiagnosticConfig.from_env()
    assert cfg.is_enabled() is False


def test_config_from_env_min_lots_override(monkeypatch):
    monkeypatch.setenv("LOT_LEVEL_EXIT_DIAGNOSTIC_MIN_LOTS", "3")
    cfg = LotLevelExitDiagnosticConfig.from_env()
    assert cfg.min_lots == 3


def test_disabled_config_returns_empty_list():
    strat = _staged_strategy()
    lots = [
        _lot("A-1", "NOW", 15, 125.00, 148.44, 1.0, 19),
        _lot("A-2", "NOW", 385, 148.84, 148.84, 0.9185, 0),
    ]
    result = evaluate_lot_level_discrepancies(
        open_trades=lots,
        current_positions_full={"NOW": {"current_price": 144.0}},
        exit_strategy=strat,
        aggregate_exit_signals=[],
        config=LotLevelExitDiagnosticConfig(disabled=True),
    )
    assert result == []


# ── Core incident reproduction ──────────────────────────────────────────

def test_reproduces_now_incident_aggregate_missed_lot_exit():
    """Old lot alone would fire trailing_stop; blended aggregate never
    activates trailing (peak_return ~0.6%) and generate() would not have
    produced a sell signal (aggregate_exit_signals=[] mirrors that).
    """
    strat = _staged_strategy()
    old_lot = _lot("NOW-old", "NOW", 15, 125.00, 148.44, 1.0, 19)
    new_lot = _lot("NOW-new", "NOW", 385, 148.84, 148.84, 0.9185, 0)

    # Sanity-check the blended view the real generate() sees today: peak_return
    # collapses far below the 8% base trailing activation.
    total_qty = 15 + 385
    weighted_entry = (15 * 125.00 + 385 * 148.84) / total_qty
    blended_peak = max(148.44, 148.84)
    blended_peak_return = (blended_peak - weighted_entry) / weighted_entry
    assert blended_peak_return < 0.01, "fixture must reproduce the near-zero blended peak_return"

    result = evaluate_lot_level_discrepancies(
        open_trades=[old_lot, new_lot],
        current_positions_full={"NOW": {"current_price": 144.0}},
        exit_strategy=strat,
        aggregate_exit_signals=[],  # generate() produced no sell signal this run
    )

    assert len(result) == 1
    disc = result[0]
    assert disc.symbol == "NOW"
    assert disc.discrepancy_type == "aggregate_missed_lot_exit"
    assert disc.aggregate_would_exit is False

    by_id = {v.trade_id: v for v in disc.lot_verdicts}
    assert by_id["NOW-old"].would_exit is True
    assert by_id["NOW-old"].exit_trigger == "trailing_stop"
    assert by_id["NOW-new"].would_exit is False


def test_single_lot_symbol_not_evaluated():
    """A symbol with only one open lot cannot be 'diluted' -- must not
    appear in min_lots=2 (default) results even if it would itself exit.
    """
    strat = _staged_strategy()
    lot = _lot("SOLO-1", "SOLO", 100, 100.0, 130.0, 1.0, 10)
    result = evaluate_lot_level_discrepancies(
        open_trades=[lot],
        current_positions_full={"SOLO": {"current_price": 80.0}},
        exit_strategy=strat,
        aggregate_exit_signals=[],
    )
    assert result == []


def test_consistent_lots_produce_no_discrepancy():
    """Two lots that both agree with the (correct) aggregate verdict must
    not be reported -- the diagnostic should stay silent when there is
    nothing to observe.
    """
    strat = _staged_strategy()
    # Two lots both deep in a loss with no signal-strength or peak
    # differentiation: any independent evaluation agrees they should exit,
    # and the aggregate did fire, so there's no split verdict.
    lot_a = _lot("CONS-1", "CONS", 50, 100.0, 100.0, 0.5, 10)
    lot_b = _lot("CONS-2", "CONS", 50, 100.0, 100.0, 0.5, 10)
    aggregate_signal = CandidateSignal(
        strategy_id="simple_exit_v2",
        symbol="CONS",
        action="sell",
        signal_strength=1.0,
        generated_at=datetime.now(timezone.utc),
        time_horizon="immediate",
        confidence=0.9,
        reasoning="Stop loss triggered",
        metadata={"exit_trigger": "Stop loss triggered"},
    )
    result = evaluate_lot_level_discrepancies(
        open_trades=[lot_a, lot_b],
        current_positions_full={"CONS": {"current_price": 88.0}},  # -12%, both below -5% low-conviction stop
        exit_strategy=strat,
        aggregate_exit_signals=[aggregate_signal],
    )
    assert result == []


def test_aggregate_exit_lot_disagreement():
    """Aggregate fired an exit but not every individual lot would have --
    the other discrepancy direction (over-eager aggregate exit)."""
    strat = _staged_strategy()
    # High-conviction old lot: wide -9% stop, still comfortably positive.
    safe_lot = _lot("DISAG-safe", "DISAG", 10, 100.0, 100.0, 1.0, 15)
    # Low-conviction new lot: tight -5% stop, deep in the loss zone on its own.
    losing_lot = _lot("DISAG-loss", "DISAG", 10, 100.0, 100.0, 0.5, 15)
    aggregate_signal = CandidateSignal(
        strategy_id="simple_exit_v2",
        symbol="DISAG",
        action="sell",
        signal_strength=1.0,
        generated_at=datetime.now(timezone.utc),
        time_horizon="immediate",
        confidence=0.9,
        reasoning="Stop loss triggered",
        metadata={"exit_trigger": "Stop loss triggered"},
    )
    # current_price=100 (flat return_pct=0 for both lots individually --
    # neither would exit on its own) but aggregate says exit anyway
    # (simulating a blended-average distortion in the opposite direction).
    result = evaluate_lot_level_discrepancies(
        open_trades=[safe_lot, losing_lot],
        current_positions_full={"DISAG": {"current_price": 100.0}},
        exit_strategy=strat,
        aggregate_exit_signals=[aggregate_signal],
    )
    assert len(result) == 1
    disc = result[0]
    assert disc.discrepancy_type == "aggregate_exit_lot_disagreement"
    assert disc.aggregate_would_exit is True
    assert all(v.would_exit is False for v in disc.lot_verdicts)


# ── Missing/invalid data handling ────────────────────────────────────────

def test_missing_current_position_skips_symbol_gracefully():
    strat = _staged_strategy()
    lots = [
        _lot("MISS-1", "MISSING", 10, 100.0, 100.0, 1.0, 10),
        _lot("MISS-2", "MISSING", 10, 100.0, 100.0, 1.0, 5),
    ]
    result = evaluate_lot_level_discrepancies(
        open_trades=lots,
        current_positions_full={},  # no broker position data for MISSING
        exit_strategy=strat,
        aggregate_exit_signals=[],
    )
    assert result == []


def test_zero_or_missing_price_skips_symbol():
    strat = _staged_strategy()
    lots = [
        _lot("ZERO-1", "ZERO", 10, 100.0, 100.0, 1.0, 10),
        _lot("ZERO-2", "ZERO", 10, 100.0, 100.0, 1.0, 5),
    ]
    result = evaluate_lot_level_discrepancies(
        open_trades=lots,
        current_positions_full={"ZERO": {"current_price": 0.0}},
        exit_strategy=strat,
        aggregate_exit_signals=[],
    )
    assert result == []


def test_below_min_lots_threshold_not_evaluated_with_custom_config():
    strat = _staged_strategy()
    lots = [
        _lot("TWO-1", "TWO", 10, 100.0, 130.0, 1.0, 10),
        _lot("TWO-2", "TWO", 10, 100.0, 130.0, 1.0, 5),
    ]
    cfg = LotLevelExitDiagnosticConfig(min_lots=3)
    result = evaluate_lot_level_discrepancies(
        open_trades=lots,
        current_positions_full={"TWO": {"current_price": 80.0}},
        exit_strategy=strat,
        aggregate_exit_signals=[],
        config=cfg,
    )
    assert result == []


def test_unrelated_symbols_not_grouped_together():
    """Lots for different symbols must never be blended into one group."""
    strat = _staged_strategy()
    lots = [
        _lot("A-1", "AAA", 10, 100.0, 130.0, 1.0, 10),
        _lot("A-2", "AAA", 10, 100.0, 130.0, 1.0, 5),
        _lot("B-1", "BBB", 10, 50.0, 60.0, 1.0, 10),
    ]
    # BBB only has 1 lot -> excluded; AAA has 2 lots -> evaluated (but here
    # both AAA lots agree with each other and with a firing aggregate, so no
    # discrepancy -- this just confirms no cross-symbol leakage/crash).
    aggregate_signal = CandidateSignal(
        strategy_id="simple_exit_v2",
        symbol="AAA",
        action="sell",
        signal_strength=1.0,
        generated_at=datetime.now(timezone.utc),
        time_horizon="immediate",
        confidence=0.9,
        reasoning="Trailing stop triggered",
        metadata={"exit_trigger": "Trailing stop triggered"},
    )
    result = evaluate_lot_level_discrepancies(
        open_trades=lots,
        current_positions_full={
            "AAA": {"current_price": 120.0},  # both lots: peak 130 -> pullback ~7.7%, trailing fires
            "BBB": {"current_price": 55.0},
        },
        exit_strategy=strat,
        aggregate_exit_signals=[aggregate_signal],
    )
    assert all(d.symbol != "BBB" for d in result)


# ── Integration: real generate() call confirms the blended silence ──────

def test_generate_produces_no_signal_for_now_incident_shape():
    """Confirms (against the real, unmodified SimpleExitV2Strategy.generate())
    that the blended NOW-shaped position produces zero exit signals at the
    symbol level -- i.e. this is not a hypothetical, it is what the
    production code actually does today. The diagnostic's value is
    detecting exactly this silence.
    """
    from stock_swing.feature_engine.base_feature import FeatureResult

    strat = _staged_strategy()
    current_positions_full = {
        "NOW": {
            "qty": 400,
            "avg_entry_price": (15 * 125.00 + 385 * 148.84) / 400,
            "current_price": 144.0,
            "peak_price": 148.84,
            "entry_signal_strength": 0.9185,
            "created_at": _iso(19),
        }
    }
    features = [
        FeatureResult(
            feature_name="price_momentum",
            symbol="NOW",
            computed_at=datetime.now(timezone.utc),
            values={"latest_close": 144.0},
        )
    ]
    signals = strat.generate(features, current_positions_full)
    assert signals == [], (
        "blended aggregate view must NOT fire an exit here -- this is the "
        "exact gap the lot-level diagnostic is designed to surface"
    )


# ── log_shadow smoke tests ───────────────────────────────────────────────

def test_log_shadow_no_path_does_not_raise():
    strat = _staged_strategy()
    lots = [
        _lot("LOG-1", "LOGX", 15, 125.00, 148.44, 1.0, 19),
        _lot("LOG-2", "LOGX", 385, 148.84, 148.84, 0.9185, 0),
    ]
    result = evaluate_lot_level_discrepancies(
        open_trades=lots,
        current_positions_full={"LOGX": {"current_price": 144.0}},
        exit_strategy=strat,
        aggregate_exit_signals=[],
    )
    assert len(result) == 1
    log_shadow(result[0], shadow_log_path=None)  # must not raise


def test_log_shadow_writes_jsonl(tmp_path):
    strat = _staged_strategy()
    lots = [
        _lot("LOG-1", "LOGY", 15, 125.00, 148.44, 1.0, 19),
        _lot("LOG-2", "LOGY", 385, 148.84, 148.84, 0.9185, 0),
    ]
    result = evaluate_lot_level_discrepancies(
        open_trades=lots,
        current_positions_full={"LOGY": {"current_price": 144.0}},
        exit_strategy=strat,
        aggregate_exit_signals=[],
    )
    log_path = tmp_path / "lot_level_exit_shadow_log.jsonl"
    log_shadow(result[0], shadow_log_path=log_path)
    assert log_path.exists()
    import json
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["symbol"] == "LOGY"
    assert record["discrepancy_type"] == "aggregate_missed_lot_exit"
    assert len(record["lots"]) == 2


def test_log_shadow_appends_multiple_records(tmp_path):
    strat = _staged_strategy()
    lots = [
        _lot("A-1", "APPX", 15, 125.00, 148.44, 1.0, 19),
        _lot("A-2", "APPX", 385, 148.84, 148.84, 0.9185, 0),
    ]
    result = evaluate_lot_level_discrepancies(
        open_trades=lots,
        current_positions_full={"APPX": {"current_price": 144.0}},
        exit_strategy=strat,
        aggregate_exit_signals=[],
    )
    log_path = tmp_path / "shadow.jsonl"
    log_shadow(result[0], shadow_log_path=log_path)
    log_shadow(result[0], shadow_log_path=log_path)
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
