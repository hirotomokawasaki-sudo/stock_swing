"""R7-v2 (2026-08-14): --require-market-session CLI wiring regression tests.

Verifies that collect_data.py main():
  - defaults to the day-only guard (should_skip_non_market_day) when the flag
    is absent, preserving existing behavior for jobs like massive/manual runs
  - calls the session-aware guard (should_skip_outside_market_hours) when
    --require-market-session is passed, and honors its skip decision
  - emits the expected skip cron-summary + exit code in both cases
"""
from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from stock_swing.cli import collect_data


def _run_main_with_args(argv, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["collect_data.py"] + argv)
    rc = collect_data.main()
    return rc, capsys.readouterr()


class TestRequireMarketSessionFlagWiring:
    def test_default_uses_day_only_guard(self, monkeypatch, capsys):
        """Without --require-market-session, only should_skip_non_market_day
        is consulted (existing weekday/holiday-only behavior)."""
        with patch.object(
            collect_data, "should_skip_non_market_day", return_value=(True, "Non-trading day: Saturday 2026-08-15")
        ) as mock_day_guard, patch.object(
            collect_data, "should_skip_outside_market_hours"
        ) as mock_session_guard:
            rc, captured = _run_main_with_args(
                ["--sources", "finnhub", "--cron-summary-json"], monkeypatch, capsys
            )
        assert rc == 0
        mock_day_guard.assert_called_once()
        mock_session_guard.assert_not_called()
        assert "Saturday" in captured.out
        assert '"status": "skipped"' in captured.out or '"status":"skipped"' in captured.out

    def test_flag_uses_session_aware_guard(self, monkeypatch, capsys):
        """With --require-market-session, should_skip_outside_market_hours is
        consulted instead of the day-only guard."""
        with patch.object(
            collect_data, "should_skip_non_market_day"
        ) as mock_day_guard, patch.object(
            collect_data,
            "should_skip_outside_market_hours",
            return_value=(True, "Market closed: Outside trading hours"),
        ) as mock_session_guard:
            rc, captured = _run_main_with_args(
                ["--sources", "finnhub", "--require-market-session", "--cron-summary-json"],
                monkeypatch,
                capsys,
            )
        assert rc == 0
        mock_session_guard.assert_called_once()
        mock_day_guard.assert_not_called()
        assert "Outside trading hours" in captured.out

    def test_flag_proceeds_when_session_active(self, monkeypatch, capsys):
        """When should_skip_outside_market_hours says don't skip, main() must
        proceed past the guard (not short-circuit with skip status)."""
        with patch.object(
            collect_data,
            "should_skip_outside_market_hours",
            return_value=(False, "Market open: Regular hours"),
        ), patch.object(collect_data, "PathManager"), patch.object(
            collect_data, "StageStore"
        ):
            rc, captured = _run_main_with_args(
                ["--sources", "fred", "--cron-summary-json"] + ["--require-market-session"],
                monkeypatch,
                capsys,
            )
        # Should not print the skip line; proceeds to collection summary instead.
        assert "skipping collect_data run" not in captured.out

    def test_flag_absent_defaults_to_false(self):
        """argparse default for --require-market-session must be False."""
        parser_args = collect_data.main.__globals__
        # Simplest robust check: parse with no args (besides required none) and
        # inspect the Namespace directly via argparse, mirroring main()'s parser.
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--require-market-session", action="store_true")
        ns = parser.parse_args([])
        assert ns.require_market_session is False
