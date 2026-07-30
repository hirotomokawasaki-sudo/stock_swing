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
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))
UI_PATH = ROOT / "ui" / "mobile_readonly.html"
SUMMARY_PATH = PROJECT_ROOT / "reports" / "console" / "latest_console_summary.json"
GO_NO_GO_PATH = PROJECT_ROOT / "docs" / "runbooks" / "go_no_go_checklist.md"
PNL_STATE_PATH = PROJECT_ROOT / "data" / "tracking" / "pnl_state.json"
CIRCUIT_BREAKER_PATH = PROJECT_ROOT / "data" / "guardrails" / "circuit_breaker.json"

# H9 (2026-07-27): mtime-based cache for large JSON files
# latest_console_summary.json は paper_demo 実行時のみ更新される (~paper_demo ごと)
# 毎リクエスト全読込から mtime 変化時のみ再読込に変更し p95 <=500ms SLO を達成する
try:
    from stock_swing.utils.mtime_cache import MtimeFileCache
    _summary_cache: MtimeFileCache[dict] = MtimeFileCache(
        loader_fn=lambda p: json.loads(p.read_text(encoding="utf-8"))
    )
    _pnl_cache: MtimeFileCache[dict] = MtimeFileCache(
        loader_fn=lambda p: json.loads(p.read_text(encoding="utf-8"))
    )
    _HAS_MTIME_CACHE = True
except ImportError:
    _HAS_MTIME_CACHE = False

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
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _file_meta(path: Path, *, read_only: bool = True) -> dict:
    if not path.exists():
        return {
            "available": False,
            "path": str(path),
            "mtime": None,
            "age_seconds": None,
            "read_only": read_only,
        }
    return {
        "available": True,
        "path": str(path),
        "mtime": _mtime_iso(path),
        "age_seconds": max(0.0, time.time() - path.stat().st_mtime),
        "read_only": read_only,
    }


def load_console_summary() -> dict:
    if not SUMMARY_PATH.exists():
        return {
            "available": False,
            "path": str(SUMMARY_PATH),
            "error": "latest_console_summary.json not found",
        }
    try:
        # H9: mtime キャッシュ経由で読込 (ファイル未変更なら再パースをスキップ)
        if _HAS_MTIME_CACHE:
            payload = _summary_cache.get(SUMMARY_PATH)
        else:
            payload = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "available": False,
            "path": str(SUMMARY_PATH),
            "error": str(exc),
        }
    payload = dict(payload)  # shallow copy so we don't mutate cache
    payload["_remote_meta"] = _file_meta(SUMMARY_PATH)
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


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _hold_days(value: str | None) -> float | None:
    dt = _parse_dt(value)
    if dt is None:
        return None
    return round((datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 86400.0, 2)


def _trade_hold_days(entry_value: str | None, exit_value: str | None) -> float | None:
    entry_dt = _parse_dt(entry_value)
    exit_dt = _parse_dt(exit_value)
    if entry_dt is None or exit_dt is None:
        return None
    return round((exit_dt.astimezone(timezone.utc) - entry_dt.astimezone(timezone.utc)).total_seconds() / 86400.0, 2)


def _query_limit(query: dict[str, list[str]], default: int, minimum: int, maximum: int) -> int:
    raw = (query.get("limit") or [str(default)])[0]
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _load_pnl_state() -> dict:
    if not PNL_STATE_PATH.exists():
        return {"trades": []}
    try:
        # H9: mtime キャッシュ経由で読込
        if _HAS_MTIME_CACHE:
            return _pnl_cache.get(PNL_STATE_PATH)
        return json.loads(PNL_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"trades": []}


def _slim_position(row: dict) -> dict:
    entry_price = row.get("entry_price") or row.get("avg_entry_price")
    current_price = row.get("current_price")
    qty = row.get("qty")
    unrealized_pnl = row.get("unrealized_pnl")
    if unrealized_pnl is None:
        unrealized_pnl = row.get("unrealized_pl")
    return_pct = row.get("return_pct")
    if return_pct is None:
        return_pct = row.get("unrealized_return_pct")
    if return_pct is None:
        return_pct = row.get("unrealized_pnl_pct")
    if return_pct is not None:
        try:
            return_pct = round(float(return_pct), 4)
        except Exception:
            return_pct = None

    return {
        "trade_id": row.get("trade_id"),
        "symbol": str(row.get("symbol") or "").upper(),
        "asset_class": row.get("asset_class"),
        "qty": qty,
        "entry_price": entry_price,
        "current_price": current_price,
        "peak_price": row.get("peak_price"),
        "unrealized_pnl": unrealized_pnl,
        "return_pct": return_pct,
        "hold_days": row.get("hold_days") if row.get("hold_days") is not None else _hold_days(row.get("entry_time") or row.get("created_at")),
        "entry_signal_strength": row.get("entry_signal_strength"),
        "strategy_id": row.get("strategy_id") or row.get("strategy_version_id"),
        "entry_time": row.get("entry_time") or row.get("created_at"),
    }


def load_positions(limit: int = 100) -> dict:
    """Return current open positions from dashboard service, falling back to pnl_state."""
    warnings: list[str] = []
    meta = _file_meta(PNL_STATE_PATH)
    try:
        from console.services.dashboard_service import DashboardService

        dashboard = DashboardService(PROJECT_ROOT)
        trading = dashboard.get_trading()
        rows = trading.get("open_positions") or []
        if rows:
            positions = [_slim_position(row) for row in rows[:limit]]
            return {
                "available": True,
                "source": "DashboardService.get_trading",
                "count": len(positions),
                "positions": positions,
                "warnings": warnings,
                "_remote_meta": meta,
            }
    except Exception as exc:
        warnings.append(f"DashboardService fallback: {exc}")

    state = _load_pnl_state()
    rows = [row for row in state.get("trades", []) if row.get("status") == "open"]
    positions = [_slim_position(row) for row in rows[:limit]]
    return {
        "available": bool(positions),
        "source": str(PNL_STATE_PATH),
        "count": len(positions),
        "positions": positions,
        "warnings": warnings,
        "_remote_meta": meta,
    }


def load_recent_trades(limit: int = 25) -> dict:
    state = _load_pnl_state()
    rows = [row for row in state.get("trades", []) if row.get("status") == "closed"]
    rows.sort(key=lambda row: row.get("exit_time") or row.get("entry_time") or "", reverse=True)

    trades = []
    for row in rows[:limit]:
        trades.append(
            {
                "trade_id": row.get("trade_id"),
                "symbol": str(row.get("symbol") or "").upper(),
                "asset_class": row.get("asset_class"),
                "qty": row.get("qty"),
                "entry_price": row.get("entry_price"),
                "exit_price": row.get("exit_price"),
                "pnl": row.get("pnl"),
                "return_pct": row.get("return_pct"),
                "entry_time": row.get("entry_time"),
                "exit_time": row.get("exit_time"),
                "hold_days": _trade_hold_days(row.get("entry_time"), row.get("exit_time")),
                "exit_reason": row.get("exit_reason"),
                "strategy_id": row.get("strategy_id") or row.get("strategy_version_id"),
            }
        )
    return {
        "available": True,
        "source": str(PNL_STATE_PATH),
        "count": len(trades),
        "trades": trades,
        "_remote_meta": _file_meta(PNL_STATE_PATH),
    }


def load_at_risk_positions(limit: int = 20) -> dict:
    positions_payload = load_positions(limit=200)
    positions = positions_payload.get("positions", [])
    at_risk = []
    for pos in positions:
        return_pct = pos.get("return_pct")
        peak_price = pos.get("peak_price")
        entry_price = pos.get("entry_price")
        peak_gain_pct = None
        try:
            if peak_price and entry_price:
                peak_gain_pct = (float(peak_price) - float(entry_price)) / float(entry_price)
        except Exception:
            peak_gain_pct = None

        reason = None
        try:
            if return_pct is not None and float(return_pct) <= -0.05:
                reason = "loss <= -5%"
            elif peak_gain_pct is not None and peak_gain_pct >= 0.05 and return_pct is None:
                reason = "peak >= +5%, current unavailable"
            elif return_pct is not None and peak_gain_pct is not None and peak_gain_pct >= 0.05 and float(return_pct) <= 0.01:
                reason = "gave back prior gain"
        except Exception:
            reason = None

        if reason:
            row = dict(pos)
            row["risk_reason"] = reason
            row["peak_gain_pct"] = round(peak_gain_pct, 4) if peak_gain_pct is not None else None
            at_risk.append(row)

    at_risk.sort(key=lambda row: (row.get("return_pct") is None, row.get("return_pct") or 0))
    return {
        "available": True,
        "source": positions_payload.get("source"),
        "count": len(at_risk[:limit]),
        "positions": at_risk[:limit],
        "warnings": positions_payload.get("warnings", []),
        "_remote_meta": positions_payload.get("_remote_meta") or _file_meta(PNL_STATE_PATH),
    }


def load_live_summary() -> dict:
    """Return live portfolio metrics computed on-the-fly via DashboardService.

    This replaces the stale latest_console_summary.json for the key portfolio
    numbers (equity, realized PnL, unrealized PnL, PF, win rate).
    """
    warnings: list[str] = []
    try:
        from console.services.dashboard_service import DashboardService

        dashboard = DashboardService(PROJECT_ROOT)
        trading = dashboard.get_trading()
        if not trading.get("available"):
            return {"available": False, "error": "trading data unavailable", "warnings": warnings}

        positions = dashboard.get_positions(trading=trading)
        account = dashboard._get_account_info()
        t_summary = trading.get("summary") or {}
        p_summary = positions.get("summary") or {}

        # Compute profit factor from closed trades
        closed_trades = trading.get("closed_trades") or []
        wins = [t for t in closed_trades if (t.get("pnl") or 0) > 0]
        losses = [t for t in closed_trades if (t.get("pnl") or 0) < 0]
        gross_profit = sum(float(t.get("pnl") or 0) for t in wins)
        gross_loss = abs(sum(float(t.get("pnl") or 0) for t in losses))
        profit_factor = round(gross_profit / gross_loss, 3) if gross_loss > 0 else None

        # Per-asset-class breakdown if available
        asset_class_breakdown: dict = {}
        try:
            if dashboard._tracker:
                asset_class_breakdown = dashboard._tracker.get_asset_class_breakdown()
        except Exception as exc:
            warnings.append(f"asset_class_breakdown: {exc}")

        equity = float(account.get("equity") or 0.0)
        realized_pnl = float(t_summary.get("cumulative_realized_pnl") or 0.0)
        unrealized_pnl = float(p_summary.get("unrealized_pnl") or 0.0)

        return {
            "available": True,
            "time": datetime.now(timezone.utc).isoformat(),
            "account": account,
            "portfolio": {
                "equity": equity,
                "realized_pnl": realized_pnl,
                "unrealized_pnl": unrealized_pnl,
                "total_pnl": round(realized_pnl + unrealized_pnl, 2),
                "open_positions": t_summary.get("open_trades"),
                "closed_trades": t_summary.get("closed_trades"),
                "win_rate": t_summary.get("win_rate"),
                "profit_factor": profit_factor,
                "asset_class_breakdown": asset_class_breakdown,
            },
            "warnings": warnings,
        }
    except Exception as exc:
        return {"available": False, "error": str(exc), "warnings": warnings}


def load_broker_tracker_detail() -> dict:
    summary = load_console_summary()
    diff = summary.get("broker_tracker_diff") or {}
    return {
        "available": bool(diff),
        "source": str(SUMMARY_PATH),
        "_remote_meta": summary.get("_remote_meta") or _file_meta(SUMMARY_PATH),
        **diff,
    }


def load_operational_health() -> dict:
    warnings: list[str] = []
    cron_jobs: list[dict] = []
    try:
        from console.adapters.cron_adapter import CronAdapter

        cron_jobs = CronAdapter(PROJECT_ROOT).get_jobs()
    except Exception as exc:
        warnings.append(f"cron unavailable: {exc}")

    stock_jobs = [job for job in cron_jobs if str(job.get("name", "")).startswith("stock_swing")]
    bad_jobs = []
    for job in stock_jobs:
        status = (
            job.get("lastRunStatus")
            or job.get("last_run_status")
            or (job.get("state") or {}).get("lastStatus")
            or ""
        )
        if status and str(status).lower() not in {"ok", "success", "completed"}:
            bad_jobs.append({"name": job.get("name"), "status": status, "last_error": job.get("last_error")})

    guardrail = {}
    try:
        from console.services.guardrail_service import get_guardrail_status

        guardrail = get_guardrail_status(PROJECT_ROOT)
    except Exception as exc:
        warnings.append(f"guardrail unavailable: {exc}")

    circuit_breaker = {}
    if CIRCUIT_BREAKER_PATH.exists():
        try:
            circuit_breaker = json.loads(CIRCUIT_BREAKER_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            warnings.append(f"circuit breaker unavailable: {exc}")

    summary = load_console_summary()
    return {
        "available": True,
        "cron": {
            "total_stock_swing_jobs": len(stock_jobs),
            "enabled_stock_swing_jobs": sum(1 for job in stock_jobs if job.get("enabled")),
            "bad_jobs": bad_jobs[:10],
        },
        "guardrail": {
            "latest_console_status": (summary.get("run") or {}).get("guardrail_status"),
            "service_status": guardrail.get("status"),
            "warnings": guardrail.get("warnings", []),
            "risks": guardrail.get("risks", []),
        },
        "circuit_breaker": circuit_breaker,
        "warnings": warnings,
        "_remote_meta": {
            "summary": _file_meta(SUMMARY_PATH),
            "pnl_state": _file_meta(PNL_STATE_PATH),
            "circuit_breaker": _file_meta(CIRCUIT_BREAKER_PATH),
        },
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

        if path == "/api/positions":
            if not self._require_auth(query):
                return
            return self._json(load_positions(limit=_query_limit(query, default=100, minimum=1, maximum=200)))

        if path == "/api/recent_trades":
            if not self._require_auth(query):
                return
            return self._json(load_recent_trades(limit=_query_limit(query, default=25, minimum=1, maximum=100)))

        if path == "/api/at_risk_positions":
            if not self._require_auth(query):
                return
            return self._json(load_at_risk_positions(limit=_query_limit(query, default=20, minimum=1, maximum=100)))

        if path == "/api/live_summary":
            if not self._require_auth(query):
                return
            return self._json(load_live_summary())

        if path == "/api/broker_tracker_detail":
            if not self._require_auth(query):
                return
            return self._json(load_broker_tracker_detail())

        if path == "/api/operational_health":
            if not self._require_auth(query):
                return
            return self._json(load_operational_health())

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
    print("Read-only APIs: /api/console_summary /api/positions /api/recent_trades")
    print("=" * 60)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
