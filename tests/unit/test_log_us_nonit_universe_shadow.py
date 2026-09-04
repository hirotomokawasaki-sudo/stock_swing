"""Tests for scripts/log_us_nonit_universe_shadow.py (R19 shadow logger,
2026-09-05).

Focus: evaluate_universe() must reproduce the production entry condition
exactly (it calls the REAL PriceMomentumFeature / BreakoutMomentumStrategy
classes), and log_shadow() must append valid JSONL. No network access in
these tests -- bars are synthesized as CanonicalRecords.

Style mirrors tests/unit/test_log_sector_rotation_shadow.py.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stock_swing.core.types import CanonicalRecord  # noqa: E402

from log_us_nonit_universe_shadow import (  # noqa: E402
    BAR_LIMIT,
    MIN_MOMENTUM,
    MIN_SIGNAL_STRENGTH,
    UNIVERSE,
    evaluate_universe,
    log_shadow,
)


def make_bars(symbol: str, closes: list[float]) -> list[CanonicalRecord]:
    """Synthesize daily CanonicalRecord bars ending today (avoids the
    stale_data quality flag in PriceMomentumFeature)."""
    now = datetime.now(timezone.utc)
    records = []
    n = len(closes)
    for i, close in enumerate(closes):
        event_time = now - timedelta(days=n - 1 - i)
        records.append(
            CanonicalRecord(
                record_id=f"test_{symbol}_{i}",
                schema_version="v1",
                source="test",
                source_type="price",
                symbol=symbol,
                event_type="bar_daily",
                event_time=event_time,
                as_of=event_time.isoformat(),
                ingested_at=now,
                timezone="UTC",
                payload_version="v1",
                payload={
                    "open": close, "high": close * 1.01,
                    "low": close * 0.99, "close": close, "volume": 1_000_000.0,
                },
                quality_flags=[],
            )
        )
    return records


def rising_closes(start: float, total_return: float, n: int = BAR_LIMIT) -> list[float]:
    return [start * (1 + total_return * i / (n - 1)) for i in range(n)]


def test_universe_is_the_approved_first_batch():
    """R19 scope guard: ETF-only universe, 9 non-IT sector ETFs + SPY."""
    assert set(UNIVERSE) == {
        "XLF", "XLE", "XLV", "XLI", "XLP", "XLU", "XLB", "XLRE", "XLC", "SPY",
    }
    assert MIN_MOMENTUM == 0.05
    assert MIN_SIGNAL_STRENGTH == 0.60
    assert BAR_LIMIT == 20


def test_strong_momentum_produces_would_signal_with_etf_strategy_id():
    """+15% over the window: momentum 0.15 >= 0.05, trend bullish, strength
    min(0.15/0.20, 1.0) = 0.75 >= 0.60 -> production condition met."""
    records = make_bars("XLE", rising_closes(80.0, 0.15))
    obs = evaluate_universe(records)
    assert obs["XLE"]["would_signal"] is True
    assert obs["XLE"]["strategy_id"] == "breakout_momentum_v1_etf"
    assert abs(obs["XLE"]["signal_strength"] - 0.75) < 1e-6
    assert obs["XLE"]["trend"] == "bullish"


def test_moderate_momentum_fails_strength_gate():
    """+8%: momentum 0.08 passes min_momentum but strength 0.40 < 0.60 ->
    no signal (this is exactly why the production strength gate matters)."""
    records = make_bars("XLF", rising_closes(50.0, 0.08))
    obs = evaluate_universe(records)
    assert obs["XLF"]["would_signal"] is False
    assert obs["XLF"]["signal_strength"] is None
    assert abs(obs["XLF"]["reference_strength"] - 0.40) < 0.01


def test_flat_series_no_signal():
    records = make_bars("XLU", [60.0] * BAR_LIMIT)
    obs = evaluate_universe(records)
    assert obs["XLU"]["would_signal"] is False
    assert obs["XLU"]["trend"] == "neutral"


def test_non_universe_symbols_are_excluded():
    records = make_bars("NVDA", rising_closes(100.0, 0.20))
    obs = evaluate_universe(records)
    assert "NVDA" not in obs


def test_log_shadow_writes_and_appends_jsonl(tmp_path):
    log_path = tmp_path / "us_nonit_universe_shadow_log.jsonl"
    record = {
        "date": "2026-09-05",
        "observations": {"XLE": {"would_signal": True}},
        "mode": "shadow",
    }
    log_shadow(record, shadow_log_path=log_path)
    log_shadow(record, shadow_log_path=log_path)

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    parsed = json.loads(lines[0])
    assert parsed["mode"] == "shadow"
    assert parsed["observations"]["XLE"]["would_signal"] is True


def test_log_shadow_without_path_does_not_raise():
    log_shadow({"date": "2026-09-05", "mode": "shadow"}, shadow_log_path=None)
