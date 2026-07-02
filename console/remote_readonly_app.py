#!/usr/bin/env python3
"""Read-only remote monitor for stock_swing.

This server is intentionally separate from console/app.py because the full
console includes parameter mutation endpoints. R6-F exposes only static UI and
read-only GET APIs backed by generated report files.
"""

from __future__ import annotations

import hmac
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
UI_PATH = ROOT / "ui" / "mobile_readonly.html"
SUMMARY_PATH = PROJECT_ROOT / "reports" / "console" / "latest_console_summary.json"
GO_NO_GO_PATH = PROJECT_ROOT / "docs" / "runbooks" / "go_no_go_checklist.md"

HOST = os.environ.get("REMOTE_READONLY_HOST", "127.0.0.1")
PORT = int(os.environ.get("REMOTE_READONLY_PORT", "3340"))
TOKEN_ENV = "REMOTE_READONLY_TOKEN"


def _load_env() -> None:
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _mtime_iso(path: Path) -> str | None:
    if not path.exists():
        return None
    from datetime import datetime, timezone

    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def load_console_summary() -> dict:
    if not SUMMARY_PATH.exists():
        return {
            "available": False,
            "path": str(SUMMARY_PATH),
            "error": "latest_console_summary.json not found",
        }
    try:
        payload = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "available": False,
            "path": str(SUMMARY_PATH),
            "error": str(exc),
        }
    payload["_remote_meta"] = {
        "available": True,
        "path": str(SUMMARY_PATH),
        "mtime": _mtime_iso(SUMMARY_PATH),
        "age_seconds": max(0.0, time.time() - SUMMARY_PATH.stat().st_mtime),
        "read_only": True,
    }
    return payload


def load_go_no_go() -> dict:
    if not GO_NO_GO_PATH.exists():
        return {
            "available": False,
            "path": str(GO_NO_GO_PATH),
            "error": "go_no_go_checklist.md not found",
        }
    text = GO_NO_GO_PATH.read_text(encoding="utf-8")
    return {
        "available": True,
        "path": str(GO_NO_GO_PATH),
        "mtime": _mtime_iso(GO_NO_GO_PATH),
        "content": text,
    }


def _configured_token() -> str:
    return os.environ.get(TOKEN_ENV, "").strip()


def _extract_token(headers, query: dict[str, list[str]]) -> str:
    auth = headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer ") :].strip()
    header_token = headers.get("X-Remote-Token", "")
    if header_token:
        return header_token.strip()
    values = query.get("token") or []
    return values[0].strip() if values else ""


def is_authorized(headers, query: dict[str, list[str]]) -> bool:
    expected = _configured_token()
    if not expected:
        return False
    actual = _extract_token(headers, query)
    return hmac.compare_digest(actual, expected)


class RemoteReadonlyHandler(BaseHTTPRequestHandler):
    server_version = "StockSwingRemoteReadonly/1.0"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("remote_readonly %s - %s\n" % (self.address_string(), fmt % args))

    def _send_bytes(self, payload: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, data: dict, status: int = 200) -> None:
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self._send_bytes(payload, "application/json; charset=utf-8", status=status)

    def _unauthorized(self) -> None:
        self._json(
            {
                "error": "unauthorized",
                "message": f"Set {TOKEN_ENV} on the server and send Authorization: Bearer <token>.",
            },
            status=401,
        )

    def _require_auth(self, query: dict[str, list[str]]) -> bool:
        if is_authorized(self.headers, query):
            return True
        self._unauthorized()
        return False

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        path = parsed.path

        if path in {"/", "/mobile", "/mobile/"}:
            if not UI_PATH.exists():
                return self._json({"error": "mobile UI not found"}, status=404)
            return self._send_bytes(UI_PATH.read_bytes(), "text/html; charset=utf-8")

        if path == "/health":
            return self._json(
                {
                    "ok": bool(_configured_token()),
                    "read_only": True,
                    "token_configured": bool(_configured_token()),
                    "summary_mtime": _mtime_iso(SUMMARY_PATH),
                }
            )

        if path == "/api/console_summary":
            if not self._require_auth(query):
                return
            return self._json(load_console_summary())

        if path == "/api/go_no_go":
            if not self._require_auth(query):
                return
            return self._json(load_go_no_go())

        if path == "/api/status":
            if not self._require_auth(query):
                return
            summary = load_console_summary()
            return self._json(
                {
                    "read_only": True,
                    "summary_available": bool(summary.get("_remote_meta", {}).get("available")),
                    "summary_age_seconds": summary.get("_remote_meta", {}).get("age_seconds"),
                    "go_no_go_available": GO_NO_GO_PATH.exists(),
                }
            )

        return self._json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        self._json({"error": "read_only", "message": "POST is disabled on this server."}, status=405)

    def do_PUT(self) -> None:
        self._json({"error": "read_only", "message": "PUT is disabled on this server."}, status=405)

    def do_DELETE(self) -> None:
        self._json({"error": "read_only", "message": "DELETE is disabled on this server."}, status=405)


def main() -> int:
    _load_env()
    server = ThreadingHTTPServer((HOST, PORT), RemoteReadonlyHandler)
    server.daemon_threads = True

    print("=" * 60)
    print("Stock Swing Remote Read-Only Monitor")
    print("=" * 60)
    print(f"URL: http://{HOST}:{PORT}")
    print(f"Health: http://{HOST}:{PORT}/health")
    print(f"Token configured: {bool(_configured_token())}")
    print("Read-only APIs: /api/console_summary /api/go_no_go /api/status")
    print("=" * 60)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
