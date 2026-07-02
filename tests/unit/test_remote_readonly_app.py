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
