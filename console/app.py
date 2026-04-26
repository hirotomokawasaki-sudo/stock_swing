#!/usr/bin/env python3
"""Stock Swing Web Console.

Lightweight web-based operations console for monitoring and managing
the stock_swing trading system.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Add project root to path
ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))

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

HOST = "0.0.0.0"
PORT = 3333

# Initialize services
dashboard = DashboardService(PROJECT_ROOT)
summary_service = SummaryService(PROJECT_ROOT)
parameter_service = ParameterService(PROJECT_ROOT)
benchmark_service = BenchmarkService(PROJECT_ROOT)


class ConsoleHandler(BaseHTTPRequestHandler):
    """HTTP request handler for Stock Swing Console."""
    
    def _json(self, data, status=200):
        """Send JSON response."""
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(payload)
    
    def _file(self, path: Path, content_type: str):
        """Serve static file."""
        if not path.exists():
            self._json({"error": "not found"}, status=404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if path.suffix in ('.js', '.css', '.html'):
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(data)
    
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
        if p == "/ui/style.css":
            return self._file(ROOT / "ui" / "style.css", "text/css; charset=utf-8")
        if p == "/ui/test.html":
            return self._file(ROOT / "ui" / "test.html", "text/html; charset=utf-8")
        
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
                data = dashboard.get_dashboard()
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
                data = dashboard.get_cron_jobs()
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

        # T11: Daily summary
        if p == "/api/summary/daily":
            try:
                data = summary_service.generate_daily_summary()
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
    server = HTTPServer((HOST, PORT), ConsoleHandler)
    
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
        
