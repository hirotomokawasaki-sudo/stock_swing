"""Tests for overnight_spillover_shadow (JP semiconductor expansion Phase 2.5).

See docs/jp_semiconductor_ai_expansion_plan.md (Phase 2.5) for context. This
module is a shadow-only, read-only signal logger with no broker/order
interaction, so tests focus on the pure evaluate_overnight_spillover_signal()
function plus log_shadow()'s file-writing behavior.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stock_swing.strategy_engine.overnight_spillover_shadow import (
    OvernightSpilloverSignal,
    evaluate_overnight_spillover_signal,
    log_shadow,
)


class TestEvaluateOvernightSpilloverSignal:
    def test_large_up_move_triggers_signal_tier1(self) -> None:
        """Acceptance: a Tier 1 symbol (Tokyo Electron) with a large US up-move
        must trigger would_signal=True, direction='up', with tier=1 recorded."""
        result = evaluate_overnight_spillover_signal(
            "8035.T", "SOXX", us_benchmark_return_pct=3.0, threshold_pct=2.0
        )
        assert result.would_signal is True
        assert result.direction == "up"
        assert result.tier == 1
        assert result.signal_strength > 0

    def test_large_down_move_triggers_signal_with_down_direction(self) -> None:
        result = evaluate_overnight_spillover_signal(
            "6857.T", "SOXX", us_benchmark_return_pct=-2.5, threshold_pct=2.0
        )
        assert result.would_signal is True
        assert result.direction == "down"

    def test_below_threshold_does_not_trigger(self) -> None:
        """Boundary: a move just under the threshold must not signal."""
        result = evaluate_overnight_spillover_signal(
            "8035.T", "SOXX", us_benchmark_return_pct=1.5, threshold_pct=2.0
        )
        assert result.would_signal is False
        assert result.direction == "none"
        assert result.signal_strength == 0.0
        assert "below_threshold" in result.reason

    def test_exactly_at_threshold_triggers(self) -> None:
        """Boundary: a move exactly at the threshold must trigger (>=, not >)."""
        result = evaluate_overnight_spillover_signal(
            "8035.T", "SOXX", us_benchmark_return_pct=2.0, threshold_pct=2.0
        )
        assert result.would_signal is True

    def test_unranked_symbol_uses_fallback_tier_weight(self) -> None:
        """Boundary: a symbol not in JP_CANDIDATE_TIERS must still compute a
        signal (using the fallback tier weight), not crash."""
        result = evaluate_overnight_spillover_signal(
            "9999.T", "SOXX", us_benchmark_return_pct=3.0, threshold_pct=2.0
        )
        assert result.would_signal is True
        assert result.tier is None
        assert result.signal_strength > 0

    def test_tier1_gets_higher_signal_strength_than_tier3_for_same_move(self) -> None:
        """Acceptance: for an identical US move magnitude, a Tier 1 symbol
        (higher historical spillover correlation, per Phase 1) must get a
        higher signal_strength than a Tier 3 symbol."""
        tier1_result = evaluate_overnight_spillover_signal(
            "8035.T", "SOXX", us_benchmark_return_pct=3.0, threshold_pct=2.0
        )  # Tokyo Electron, tier 1
        tier3_result = evaluate_overnight_spillover_signal(
            "6506.T", "SOXX", us_benchmark_return_pct=3.0, threshold_pct=2.0
        )  # Yaskawa Electric, tier 3

        assert tier1_result.signal_strength > tier3_result.signal_strength

    def test_signal_strength_is_clamped_to_one(self) -> None:
        """Boundary: an extreme US move must not push signal_strength above 1.0."""
        result = evaluate_overnight_spillover_signal(
            "8035.T", "SOXX", us_benchmark_return_pct=50.0, threshold_pct=2.0
        )
        assert result.signal_strength <= 1.0

    def test_jp_open_gap_pct_passthrough(self) -> None:
        """The optional jp_open_gap_pct parameter must be carried through
        unchanged to the result (used for forward-validation backfill)."""
        result = evaluate_overnight_spillover_signal(
            "8035.T", "SOXX", us_benchmark_return_pct=3.0,
            threshold_pct=2.0, jp_open_gap_pct=2.4,
        )
        assert result.jp_open_gap_pct == 2.4

    def test_zero_return_does_not_signal(self) -> None:
        """Boundary: a flat (0%) US session must not trigger a signal."""
        result = evaluate_overnight_spillover_signal(
            "8035.T", "SOXX", us_benchmark_return_pct=0.0, threshold_pct=2.0
        )
        assert result.would_signal is False


class TestLogShadow:
    def test_writes_jsonl_record_to_file(self, tmp_path: Path) -> None:
        """Acceptance: log_shadow must append one valid JSON line per call,
        matching the pattern used by sector_shock_hold/volatility_gate shadow
        logs (accumulates across runs, one record per line)."""
        log_path = tmp_path / "test_shadow_log.jsonl"
        result = evaluate_overnight_spillover_signal(
            "8035.T", "SOXX", us_benchmark_return_pct=3.0, threshold_pct=2.0
        )

        log_shadow(result, shadow_log_path=log_path)
        log_shadow(result, shadow_log_path=log_path)

        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        record = json.loads(lines[0])
        assert record["symbol"] == "8035.T"
        assert record["would_signal"] is True
        assert record["mode"] == "shadow"
        assert "logged_at" in record

    def test_none_path_does_not_write_anything(self) -> None:
        """Fallback: passing shadow_log_path=None must not raise (used for
        --dry-run mode in the daily script)."""
        result = evaluate_overnight_spillover_signal(
            "8035.T", "SOXX", us_benchmark_return_pct=3.0, threshold_pct=2.0
        )
        # Should not raise
        log_shadow(result, shadow_log_path=None)

    def test_creates_parent_directory_if_missing(self, tmp_path: Path) -> None:
        """Boundary: log_shadow must create parent directories automatically
        (mirrors volatility_gate.log_shadow's mkdir behavior)."""
        log_path = tmp_path / "nested" / "dir" / "shadow_log.jsonl"
        result = evaluate_overnight_spillover_signal(
            "8035.T", "SOXX", us_benchmark_return_pct=3.0, threshold_pct=2.0
        )

        log_shadow(result, shadow_log_path=log_path)

        assert log_path.exists()
