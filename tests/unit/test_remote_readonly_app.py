"""Tests for the R6-F remote read-only monitor."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from console import remote_readonly_app as remote


class Headers(dict):
    def get(self, key, default=None):  # match BaseHTTPRequestHandler headers enough for tests
        return super().get(key, default)


def test_is_authorized_with_bearer_token(monkeypatch) -> None:
    monkeypatch.setenv("REMOTE_READONLY_TOKEN", "secret-token")

    assert remote.is_authorized(Headers({"Authorization": "Bearer secret-token"}), {}) is True
    assert remote.is_authorized(Headers({"Authorization": "Bearer wrong"}), {}) is False


def test_is_authorized_rejects_when_server_token_missing(monkeypatch) -> None:
    monkeypatch.delenv("REMOTE_READONLY_TOKEN", raising=False)

    assert remote.is_authorized(Headers({"Authorization": "Bearer anything"}), {}) is False


def test_is_authorized_accepts_query_token(monkeypatch) -> None:
    monkeypatch.setenv("REMOTE_READONLY_TOKEN", "secret-token")

    assert remote.is_authorized(Headers({}), {"token": ["secret-token"]}) is True


def test_load_console_summary_adds_remote_metadata(tmp_path: Path, monkeypatch) -> None:
    summary_path = tmp_path / "latest_console_summary.json"
    summary_path.write_text(
        json.dumps({"run": {"status": "OK"}, "portfolio": {"equity": 123.45}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(remote, "SUMMARY_PATH", summary_path)

    payload = remote.load_console_summary()

    assert payload["run"]["status"] == "OK"
    assert payload["_remote_meta"]["available"] is True
    assert payload["_remote_meta"]["read_only"] is True


def test_load_go_no_go_reads_markdown(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "go_no_go_checklist.md"
    path.write_text("# Go\n\nDecision: TBD\n", encoding="utf-8")
    monkeypatch.setattr(remote, "GO_NO_GO_PATH", path)

    payload = remote.load_go_no_go()

    assert payload["available"] is True
    assert "Decision: TBD" in payload["content"]


def test_load_recent_trades_sorts_closed_by_exit_time(tmp_path: Path, monkeypatch) -> None:
    state_path = tmp_path / "pnl_state.json"
    state_path.write_text(
        json.dumps(
            {
                "trades": [
                    {
                        "symbol": "OLD",
                        "status": "closed",
                        "entry_time": "2025-12-31T00:00:00+00:00",
                        "exit_time": "2026-01-01T00:00:00+00:00",
                        "pnl": 1,
                    },
                    {
                        "symbol": "NEW",
                        "status": "closed",
                        "entry_time": "2026-01-31T00:00:00+00:00",
                        "exit_time": "2026-02-01T00:00:00+00:00",
                        "pnl": 2,
                    },
                    {"symbol": "OPEN", "status": "open", "entry_time": "2026-03-01T00:00:00+00:00"},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(remote, "PNL_STATE_PATH", state_path)

    payload = remote.load_recent_trades(limit=2)

    assert payload["count"] == 2
    assert [row["symbol"] for row in payload["trades"]] == ["NEW", "OLD"]
    assert payload["trades"][0]["hold_days"] == 1.0


def test_query_limit_clamps_bad_values() -> None:
    assert remote._query_limit({"limit": ["abc"]}, default=25, minimum=1, maximum=100) == 25
    assert remote._query_limit({"limit": ["0"]}, default=25, minimum=1, maximum=100) == 1
    assert remote._query_limit({"limit": ["999"]}, default=25, minimum=1, maximum=100) == 100


def test_load_at_risk_positions_flags_loss(monkeypatch) -> None:
    monkeypatch.setattr(
        remote,
        "load_positions",
        lambda limit=200: {
            "source": "test",
            "warnings": [],
            "positions": [
                {"symbol": "BAD", "return_pct": -0.06, "entry_price": 100, "peak_price": 101},
                {"symbol": "OK", "return_pct": 0.02, "entry_price": 100, "peak_price": 101},
            ],
        },
    )

    payload = remote.load_at_risk_positions()

    assert payload["count"] == 1
    assert payload["positions"][0]["symbol"] == "BAD"
    assert payload["positions"][0]["risk_reason"] == "loss <= -5%"


def test_load_broker_tracker_detail_uses_console_summary(tmp_path: Path, monkeypatch) -> None:
    summary_path = tmp_path / "latest_console_summary.json"
    summary_path.write_text(
        json.dumps({"broker_tracker_diff": {"mismatch_count": 2, "broker_only": ["A"], "tracker_only": ["B"]}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(remote, "SUMMARY_PATH", summary_path)

    payload = remote.load_broker_tracker_detail()

    assert payload["available"] is True
    assert payload["mismatch_count"] == 2
