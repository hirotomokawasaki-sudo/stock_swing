"""Tests for console_self_check_service."""
from __future__ import annotations
import json
from pathlib import Path
import pytest

from console.services.console_self_check_service import run_self_check


@pytest.fixture
def tmp_root(tmp_path: Path) -> Path:
    """Minimal repo root with all critical files present."""
    (tmp_path / "data/tracking").mkdir(parents=True)
    (tmp_path / "data/decisions").mkdir(parents=True)
    (tmp_path / "exports").mkdir()
    (tmp_path / "data/tracking/pnl_state.json").write_text('{"trades":[]}')
    (tmp_path / "data/decisions/recent_decisions.json").write_text('[]')
    (tmp_path / "exports/summary_stats.json").write_text('{}')
    (tmp_path / "exports/closed_trades.csv").write_text("symbol,pnl\n")
    (tmp_path / "exports/open_positions.csv").write_text("symbol,qty\n")
    return tmp_path


def test_all_present_returns_ok(tmp_root: Path) -> None:
    result = run_self_check(tmp_root)
    assert result["ok"] is True
    assert result["checks"]["pnl_state"]["ok"] is True
    assert result["checks"]["exports_closed_trades"]["ok"] is True


def test_optional_ui_missing_is_warning_not_error(tmp_root: Path) -> None:
    # No console/ui dir — should warn but not fail
    result = run_self_check(tmp_root)
    assert result["ok"] is True  # only critical files affect ok
    assert result["checks"]["static_ui"]["ok"] is False
    assert any("UI" in w or "ui" in w for w in result["warnings"])


def test_missing_critical_pnl_state_sets_ok_false(tmp_root: Path) -> None:
    (tmp_root / "data/tracking/pnl_state.json").unlink()
    result = run_self_check(tmp_root)
    assert result["ok"] is False
    assert result["checks"]["pnl_state"]["ok"] is False
    assert any("pnl_state" in w or "Critical" in w for w in result["warnings"])


def test_missing_optional_export_warns_but_ok(tmp_root: Path) -> None:
    (tmp_root / "exports/closed_trades.csv").unlink()
    result = run_self_check(tmp_root)
    assert result["ok"] is True
    assert result["checks"]["exports_closed_trades"]["ok"] is False
    assert any("closed_trades" in w for w in result["warnings"])


def test_returns_200_compatible_structure(tmp_root: Path) -> None:
    result = run_self_check(tmp_root)
    assert "ok" in result
    assert "checks" in result
    assert "warnings" in result
    assert "root" in result
