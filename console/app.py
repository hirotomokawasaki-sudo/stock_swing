#!/usr/bin/env python3
"""Stock Swing Web Console.

Lightweight web-based operations console for monitoring and managing
the stock_swing trading system.
"""

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Add project root to path
ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))  # For stock_swing module
sys.path.insert(0, str(PROJECT_ROOT))  # For console module

# Load environment variables from .env
def load_env():
    env_file = PROJECT_ROOT / '.env'
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value
        print(f"✅ Loaded environment from {env_file}")
    else:
        print(f"⚠️  No .env file found at {env_file}")

load_env()

from console.services.dashboard_service import DashboardService
from console.services.summary_service import SummaryService
from console.services.parameter_service import ParameterService
from console.services.benchmark_service import BenchmarkService
from console.utils.time_utils import now_iso
from console.services.console_self_check_service import run_self_check
from console.services.guardrail_service import get_guardrail_status
from console.services.performance_breakdown_service import get_performance_breakdown
from console.services.position_risk_service import get_open_position_risk

HOST = "0.0.0.0"
PORT = int(os.environ.get("CONSOLE_PORT", "3333"))

# Initialize services
dashboard = DashboardService(PROJECT_ROOT)
summary_service = SummaryService(PROJECT_ROOT)
parameter_service = ParameterService(PROJECT_ROOT)
benchmark_service = BenchmarkService(PROJECT_ROOT)

# In-memory response cache with single-flight pattern (thread-safe).
# Only one goroutine computes a given key; all others wait for the result.
_cache_lock = threading.Lock()
_cache: dict = {}       # key -> {"data": ..., "ts": float, "ttl": float}
_in_flight: dict = {}   # key -> threading.Event  (set when result is ready)


def _get_cached(key: str):
    """Return cached data if still valid, else None."""
    with _cache_lock:
        entry = _cache.get(key)
        if entry and (time.time() - entry["ts"]) < entry["ttl"]:
            return entry["data"]
    return None


def _set_cached(key: str, data, ttl: float = 60.0):
    """Store data in cache with TTL seconds."""
    with _cache_lock:
        _cache[key] = {"data": data, "ts": time.time(), "ttl": ttl}


def _compute_once(key: str, fn, ttl: float = 60.0):
    """Single-flight fetch: run fn() once per key; concurrent callers wait.

    Returns the computed (or cached) value.
    """
    # Fast path: already cached
    cached = _get_cached(key)
    if cached is not None:
        return cached

    with _cache_lock:
        # Re-check after acquiring lock (may have been set while waiting)
        entry = _cache.get(key)
        if entry and (time.time() - entry["ts"]) < entry["ttl"]:
            return entry["data"]

        # Are we already computing this key?
        if key in _in_flight:
            ev = _in_flight[key]
        else:
            ev = threading.Event()
            _in_flight[key] = ev
            ev = None  # We are the primary; no event to wait on

    if ev is not None:
        # Wait for the primary thread to finish (max 30s)
        ev.wait(timeout=30)
        return _get_cached(key)

    # We are the primary: compute and store
    try:
        result = fn()
        _set_cached(key, result, ttl=ttl)
        return result
    finally:
        with _cache_lock:
            ev2 = _in_flight.pop(key, None)
        if ev2 is not None:
            ev2.set()


class ConsoleHandler(BaseHTTPRequestHandler):
    """HTTP request handler for Stock Swing Console."""
    
    def _json(self, data, status=200):
        """Send JSON response."""
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            return
    
    def _file(self, path: Path, content_type: str):
        """Serve static file."""
        if not path.exists():
            self._json({"error": "not found"}, status=404)
            return
        data = path.read_bytes()
        try:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            if path.suffix in ('.js', '.css', '.html'):
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            return
    
    def log_message(self, format, *args):
        """Suppress request logging (too noisy)."""
        pass
    
    def do_GET(self):
        """Handle GET requests."""
        u = urlparse(self.path)
        p = u.path
        q = parse_qs(u.query)
        
        # Static files
        if p in ("/", "/index.html"):
            return self._file(ROOT / "ui" / "index.html", "text/html; charset=utf-8")
        if p == "/ui/app.js":
            return self._file(ROOT / "ui" / "app.js", "application/javascript; charset=utf-8")
        if p == "/ui/utils.js":
            return self._file(ROOT / "ui" / "utils.js", "application/javascript; charset=utf-8")
        if p == "/ui/validators.js":
            return self._file(ROOT / "ui" / "validators.js", "application/javascript; charset=utf-8")
        if p == "/ui/api-client.js":
            return self._file(ROOT / "ui" / "api-client.js", "application/javascript; charset=utf-8")
        if p == "/ui/error-handler.js":
            return self._file(ROOT / "ui" / "error-handler.js", "application/javascript; charset=utf-8")
        if p == "/ui/state-manager.js":
            return self._file(ROOT / "ui" / "state-manager.js", "application/javascript; charset=utf-8")
        if p == "/ui/performance-monitor.js":
            return self._file(ROOT / "ui" / "performance-monitor.js", "application/javascript; charset=utf-8")
        if p == "/ui/error-tracker.js":
            return self._file(ROOT / "ui" / "error-tracker.js", "application/javascript; charset=utf-8")
        if p == "/ui/health-monitor.js":
            return self._file(ROOT / "ui" / "health-monitor.js", "application/javascript; charset=utf-8")
        if p == "/ui/recovery-manager.js":
            return self._file(ROOT / "ui" / "recovery-manager.js", "application/javascript; charset=utf-8")
        if p == "/ui/report-generator.js":
            return self._file(ROOT / "ui" / "report-generator.js", "application/javascript; charset=utf-8")
        if p == "/ui/style.css":
            return self._file(ROOT / "ui" / "style.css", "text/css; charset=utf-8")
        if p == "/ui/test.html":
            return self._file(ROOT / "ui" / "test.html", "text/html; charset=utf-8")
        if p == "/ui/test-robustness.html":
            return self._file(ROOT / "ui" / "test-robustness.html", "text/html; charset=utf-8")
        if p == "/ui/test-phase3.html":
            return self._file(ROOT / "ui" / "test-phase3.html", "text/html; charset=utf-8")
        
        # Health check
        if p == "/health":
            return self._json({
                "ok": True,
                "service": "stock_swing_console",
                "time": now_iso(),
                "project_root": str(PROJECT_ROOT),
            })
        
        # API endpoints
        if p == "/api/dashboard":
            try:
                period = q.get('period', ['month'])[0]
                cache_key = f"dashboard:{period}"
                data = _compute_once(
                    cache_key,
                    lambda: dashboard.get_dashboard(period=period),
                    ttl=60.0,
                )
                return self._json(data)
            except Exception as e:
                return self._json({"error": str(e)}, status=500)
        
        if p == "/api/dashboard/symbol_overview":
            try:
                pipeline = dashboard.get_pipeline_summary()
                data = pipeline.get('symbol_overview', [])
                return self._json(data)
            except Exception as e:
                return self._json({"error": str(e)}, status=500)
        
        if p == "/api/dashboard/strategy_overview":
            try:
                pipeline = dashboard.get_pipeline_summary()
                data = pipeline.get('by_strategy', [])
                return self._json(data)
            except Exception as e:
                return self._json({"error": str(e)}, status=500)
        
        if p == "/api/overview":
            try:
                data = dashboard.get_overview()
                return self._json(data)
            except Exception as e:
                return self._json({"error": str(e)}, status=500)
        
        if p == "/api/cron_jobs":
            try:
                cached = _get_cached("cron_jobs")
                if cached is not None:
                    return self._json(cached)
                data = dashboard.get_cron_jobs()
                _set_cached("cron_jobs", data, ttl=30.0)
                return self._json(data)
            except Exception as e:
                return self._json({"error": str(e)}, status=500)
        
        if p == "/api/system_status":
            try:
                data = dashboard.get_system_status()
                return self._json(data)
            except Exception as e:
                return self._json({"error": str(e)}, status=500)

        if p == "/api/trading":
            try:
                data = dashboard.get_trading()
                return self._json(data)
            except Exception as e:
                return self._json({"error": str(e)}, status=500)

        if p == "/api/positions":
            try:
                data = dashboard.get_positions()
                return self._json(data)
            except Exception as e:
                return self._json({"error": str(e)}, status=500)

        if p == "/api/archives":
            try:
                data = dashboard.get_archive_history()
                return self._json(data)
            except Exception as e:
                return self._json({"error": str(e)}, status=500)

        if p == "/api/logs":
            try:
                data = dashboard.get_logs()
                return self._json(data)
            except Exception as e:
                return self._json({"error": str(e)}, status=500)
        
        # Phase 1 Enhancement APIs
        if p == "/api/strategy_analysis":
            try:
                data = dashboard.get_strategy_analysis()
                return self._json(data)
            except Exception as e:
                return self._json({"error": str(e)}, status=500)
        
        if p == "/api/live_metrics":
            try:
                data = dashboard.get_live_metrics()
                return self._json(data)
            except Exception as e:
                return self._json({"error": str(e)}, status=500)

        if p == "/api/decision_reasons":
            try:
                strategy = q.get('strategy', [None])[0]
                days = int(q.get('days', ['7'])[0])
                limit = int(q.get('limit', ['200'])[0])
                symbol = q.get('symbol', [None])[0]
                data = dashboard.get_decision_reasons(strategy=strategy, days=days, limit=limit, symbol=symbol)
                return self._json(data)
            except Exception as e:
                return self._json({"error": str(e)}, status=500)
        
        if p == "/api/exit_reasons":
            try:
                exit_strategy = q.get('exit_strategy', [None])[0]
                data = dashboard.get_exit_reason_summary(exit_strategy=exit_strategy)
                # C4: Augment with pending exit reasons
                try:
                    pending_path = PROJECT_ROOT / "data/tracking/pending_exit_reasons.json"
                    pending_raw = json.loads(pending_path.read_text()) if pending_path.exists() else {}
                    _REASON_MAP = {
                        "trailing_stop": "trail_stop", "trail_stop": "trail_stop",
                        "breakeven_stop": "trail_stop",
                        "stop_loss": "risk_stop",
                        "take_profit": "take_profit",
                        "time_based": "weakening_momentum", "max_hold": "weakening_momentum",
                        "strategy_exit": "weakening_momentum",
                        "manual": "manual",
                    }
                    pending_list = [
                        {
                            "symbol": v.get("symbol", "?"),
                            "reason": _REASON_MAP.get(v.get("exit_reason", ""), "unknown"),
                            "raw_reason": v.get("exit_reason", "unknown"),
                            "source": "pending_exit_reasons",
                        }
                        for v in pending_raw.values()
                    ]
                    data["pending"] = pending_list
                    data["pending_count"] = len(pending_list)
                except Exception:
                    data["pending"] = []
                    data["pending_count"] = 0
                return self._json(data)
            except Exception as e:
                return self._json({"error": str(e)}, status=500)

        # T11: Daily summary
        if p == "/api/summary/daily":
            try:
                data = summary_service.generate_daily_summary()
                return self._json(data)
            except Exception as e:
                return self._json({"error": str(e)}, status=500)
        
        # T11: Weekly summary
        if p == "/api/summary/weekly":
            try:
                weeks = int(q.get('weeks', ['1'])[0])
                data = summary_service.generate_weekly_summary(weeks=weeks)
                return self._json(data)
            except Exception as e:
                return self._json({"error": str(e)}, status=500)
        
        # Daily conversion rate
        if p == "/api/conversion/daily":
            try:
                date = q.get('date', [None])[0]
                data = dashboard.get_daily_conversion_rate(date)
                return self._json(data)
            except Exception as e:
                return self._json({"error": str(e)}, status=500)
        
        # Benchmark normalized series for equity chart overlay (SPY / QQQ)
        if p == "/api/benchmark/normalized":
            try:
                trading_data = dashboard.get_trading()
                snapshots = trading_data.get('daily_snapshots', [])
                symbols_param = q.get('symbols', ['SPY,QQQ'])[0]
                symbols = [s.strip().upper() for s in symbols_param.split(',') if s.strip()]
                data = benchmark_service.get_normalized_series(snapshots, symbols)
                return self._json(data)
            except Exception as e:
                return self._json({"error": str(e)}, status=500)

        # Performance attribution (Alpha, Beta, Sharpe)
        if p == "/api/performance/attribution":
            try:
                trading_data = dashboard.get_trading()
                snapshots = trading_data.get('daily_snapshots', [])
                benchmark = q.get('benchmark', ['SPY'])[0]
                data = benchmark_service.get_performance_attribution(snapshots, benchmark)
                return self._json(data)
            except Exception as e:
                return self._json({"error": str(e)}, status=500)
        
        # T10: Symbol drilldown
        if p.startswith("/api/symbol/"):
            try:
                symbol = p.split("/")[-1].upper()
                if not symbol:
                    return self._json({"error": "symbol required"}, status=400)
                data = dashboard.get_symbol_detail(symbol)
                return self._json(data)
            except Exception as e:
                return self._json({"error": str(e)}, status=500)
        
        # T12: Parameter management (READ-ONLY)
        if p == "/api/parameters":
            try:
                data = parameter_service.get_all_parameters()
                return self._json(data)
            except Exception as e:
                return self._json({"error": str(e)}, status=500)
        
        if p.startswith("/api/parameters/") and p.endswith("/validate"):
            try:
                param_name = p.split("/")[-2]
                value_str = q.get('value', [''])[0]
                if not value_str:
                    return self._json({"error": "value required"}, status=400)
                value = float(value_str)
                result = parameter_service.validate_value(param_name, value)
                return self._json(result)
            except ValueError as e:
                return self._json({"error": str(e)}, status=400)
            except Exception as e:
                return self._json({"error": str(e)}, status=500)
        
        # C0: Console self-check
        if p == "/api/console/self_check":
            try:
                return self._json(run_self_check(PROJECT_ROOT))
            except Exception as e:
                return self._json({"error": str(e)}, status=500)

        # C1: Risk guardrails
        if p == "/api/risk_guardrails":
            try:
                return self._json(get_guardrail_status(PROJECT_ROOT))
            except Exception as e:
                return self._json({"error": str(e)}, status=500)

        # C2: Performance breakdown (ETF vs Stock vs Sector)
        if p == "/api/performance_breakdown":
            try:
                return self._json(get_performance_breakdown(PROJECT_ROOT))
            except Exception as e:
                return self._json({"error": str(e)}, status=500)

        # C3: Open position risk
        if p == "/api/open_position_risk":
            try:
                return self._json(get_open_position_risk(PROJECT_ROOT))
            except Exception as e:
                return self._json({"error": str(e)}, status=500)

        # 404
        return self._json({"error": "not found"}, status=404)

    def do_POST(self):
        """Handle POST requests."""
        u = urlparse(self.path)
        p = u.path
        
        # T12: Apply parameter change
        if p.startswith("/api/parameters/") and p.endswith("/apply"):
            try:
                # Read request body
                content_length = int(self.headers.get('Content-Length', 0))
                if content_length == 0:
                    return self._json({"error": "Request body required"}, status=400)
                
                body = self.rfile.read(content_length)
                data = json.loads(body.decode('utf-8'))
                
                param_name = p.split("/")[-2]
                value = data.get("value")
                confirmed = data.get("confirmed", False)
                
                if value is None:
                    return self._json({"error": "value required"}, status=400)
                
                result = parameter_service.apply_parameter(param_name, float(value), confirmed)
                
                if result.get("success"):
                    return self._json(result)
                else:
                    return self._json(result, status=400)
                    
            except ValueError as e:
                return self._json({"error": str(e)}, status=400)
            except Exception as e:
                return self._json({"error": str(e)}, status=500)
        
        # T12: Rollback parameter
        if p.startswith("/api/parameters/") and p.endswith("/rollback"):
            try:
                param_name = p.split("/")[-2]
                result = parameter_service.rollback_last_change(param_name)
                return self._json(result)
            except ValueError as e:
                return self._json({"error": str(e)}, status=400)
            except Exception as e:
                return self._json({"error": str(e)}, status=500)

        return self._json({"error": "not found"}, status=404)


def main():
    """Start the console server."""
    server = ThreadingHTTPServer((HOST, PORT), ConsoleHandler)
    server.daemon_threads = True
    
    print("=" * 60)
    print("🤖 Stock Swing Web Console")
    print("=" * 60)
    print(f"📍 URL: http://localhost:{PORT}")
    print(f"🏠 Project: {PROJECT_ROOT}")
    print(f"💚 Health: http://localhost:{PORT}/health")
    print("=" * 60)
    print("Press Ctrl+C to stop")
    print()
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n🛑 Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
        
