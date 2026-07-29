"""Adapter for system health status.

FIX-OBSERVE-1: health_score=100 and status='healthy' are PROHIBITED when any
critical evidence input is missing, stale, or invalid.  The score is now
derived from a mandatory evidence checklist rather than simple api-key presence.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

# Maximum age (seconds) before an evidence source is considered stale.
_LEDGER_STALENESS_S = 86400      # 24 h
_GUARDRAIL_STALENESS_S = 3600   # 1 h
_BROKER_STALENESS_S = 3600      # 1 h
_CONSOLE_STALENESS_S = 900      # 15 min


def _age_seconds(iso_str: Optional[str]) -> Optional[float]:
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds()
    except Exception:
        return None


class SystemAdapter:
    """Read system health and configuration."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.runtime_config = project_root / "config" / "runtime" / "current_mode.yaml"
        self.env_file = project_root / ".env"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_health(self) -> Dict[str, Any]:
        """Return health dict with evidence-based score.

        CRITICAL RULE: score=100 / status='healthy' is only possible when ALL
        critical evidence inputs are present, fresh, and valid.  Any missing
        or stale critical evidence caps the score at 70 (degraded).
        """
        runtime_mode = self._get_runtime_mode()
        api_ok = self._check_api_keys()
        venv_ok = (self.project_root / "venv").exists()

        evidence = self._collect_evidence()
        critical_missing = [k for k, v in evidence.items() if v["critical"] and not v["ok"]]

        # Base score from infrastructure
        score = 0
        if runtime_mode in ["research", "paper"]:
            score += 40
        if api_ok:
            score += 20
        if venv_ok:
            score += 10

        # Evidence bonus — each healthy critical evidence adds points
        critical_ok = sum(1 for v in evidence.values() if v["critical"] and v["ok"])
        critical_total = sum(1 for v in evidence.values() if v["critical"])
        if critical_total > 0:
            score += int(30 * critical_ok / critical_total)

        # Hard cap: any missing critical evidence => max 70 (degraded)
        if critical_missing:
            score = min(score, 70)

        if score >= 80 and not critical_missing:
            status = "healthy"
        elif score >= 50:
            status = "degraded"
        else:
            status = "unhealthy"

        return {
            "runtime_mode": runtime_mode,
            "api_keys_configured": api_ok,
            "venv_exists": venv_ok,
            "score": score,
            "status": status,
            "evidence": evidence,
            "critical_missing": critical_missing,
            "evidence_status": "invalid" if critical_missing else "valid",
        }

    # ------------------------------------------------------------------
    # Evidence checklist
    # ------------------------------------------------------------------

    def _collect_evidence(self) -> Dict[str, Dict[str, Any]]:
        """Build evidence checklist for all critical inputs."""
        ev: Dict[str, Dict[str, Any]] = {}

        # 1. Ledger validity
        ev["ledger_validity"] = self._check_ledger_validity()

        # 2. Guardrail metric freshness
        ev["guardrail_metric_freshness"] = self._check_guardrail_freshness()

        # 3. Broker/tracker reconciliation freshness
        ev["broker_tracker_reconciliation"] = self._check_broker_tracker_freshness()

        # 4. Console summary freshness
        ev["console_summary_freshness"] = self._check_console_summary_freshness()

        # 5. Source SLA (at least one primary data source collected today)
        ev["source_sla"] = self._check_source_sla()

        # 6. Cron run history parse coverage
        ev["cron_run_history"] = self._check_cron_parse_coverage()

        return ev

    def _check_ledger_validity(self) -> Dict[str, Any]:
        cfg_path = self.runtime_config
        try:
            cfg = yaml.safe_load(cfg_path.read_text()) if cfg_path.exists() else {}
            gate = cfg.get("ledger_quality_gate", {})
            status = gate.get("current_status", "UNKNOWN")
            last_checked = gate.get("last_checked")
            ok = status == "VALID"
            age = _age_seconds(last_checked + "T00:00:00+00:00") if last_checked else None
            stale = age is not None and age > _LEDGER_STALENESS_S
            return {
                "critical": True, "ok": ok and not stale,
                "status": status, "last_checked": last_checked,
                "stale": stale, "detail": "ledger_quality_gate.current_status",
            }
        except Exception as exc:
            return {"critical": True, "ok": False, "error": str(exc)}

    def _check_guardrail_freshness(self) -> Dict[str, Any]:
        cb_path = self.project_root / "data" / "guardrails" / "circuit_breaker.json"
        try:
            d = json.loads(cb_path.read_text()) if cb_path.exists() else {}
            cleared_at = d.get("cleared_at") or d.get("triggered_at")
            age = _age_seconds(cleared_at)
            stale = age is not None and age > _GUARDRAIL_STALENESS_S
            status = d.get("status", "unknown")
            ok = status == "ok" and not stale
            return {
                "critical": True, "ok": ok,
                "cb_status": status, "as_of": cleared_at,
                "stale": stale, "detail": "circuit_breaker.json",
            }
        except Exception as exc:
            return {"critical": True, "ok": False, "error": str(exc)}

    def _check_broker_tracker_freshness(self) -> Dict[str, Any]:
        audit_path = self.project_root / "data" / "audits" / "reconcile_status.json"
        try:
            if not audit_path.exists():
                return {
                    "critical": True, "ok": False,
                    "detail": "reconcile_status.json not found — run reconcile first",
                }
            d = json.loads(audit_path.read_text())
            as_of = d.get("as_of") or d.get("time")
            age = _age_seconds(as_of)
            stale = age is not None and age > _BROKER_STALENESS_S
            mismatch = int(d.get("unexplained_mismatch_count", 1))
            ok = not stale and mismatch == 0
            return {
                "critical": True, "ok": ok,
                "mismatch_count": mismatch, "as_of": as_of,
                "stale": stale, "detail": "data/audits/reconcile_status.json",
            }
        except Exception as exc:
            return {"critical": True, "ok": False, "error": str(exc)}

    def _check_console_summary_freshness(self) -> Dict[str, Any]:
        summary_path = self.project_root / "data" / "config" / "latest_console_summary.json"
        try:
            if not summary_path.exists():
                return {"critical": False, "ok": False, "detail": "latest_console_summary.json not found"}
            import os
            mtime = os.path.getmtime(summary_path)
            age = datetime.now(timezone.utc).timestamp() - mtime
            stale = age > _CONSOLE_STALENESS_S
            return {
                "critical": False, "ok": not stale,
                "age_seconds": round(age), "stale": stale,
                "detail": "data/config/latest_console_summary.json",
            }
        except Exception as exc:
            return {"critical": False, "ok": False, "error": str(exc)}

    def _check_source_sla(self) -> Dict[str, Any]:
        status_path = self.project_root / "data" / "audits" / "news_collection_status.json"
        try:
            if not status_path.exists():
                return {"critical": True, "ok": False, "detail": "news_collection_status.json not found"}
            d = json.loads(status_path.read_text())
            as_of = d.get("time")
            age = _age_seconds(as_of)
            stale = age is not None and age > 86400 * 2  # allow up to 2 days (weekends)
            symbols = d.get("symbols", [])
            ok_count = sum(1 for s in symbols if not s.get("used_fallback") and s.get("news_count", 0) > 0)
            total = max(len(symbols), 1)
            coverage = round(ok_count / total, 3)
            ok = not stale and coverage >= 0.5  # >=50% symbols have real news
            return {
                "critical": True, "ok": ok,
                "coverage": coverage, "as_of": as_of,
                "stale": stale, "ok_symbols": ok_count, "total_symbols": total,
                "detail": "data/audits/news_collection_status.json",
            }
        except Exception as exc:
            return {"critical": True, "ok": False, "error": str(exc)}

    def _check_cron_parse_coverage(self) -> Dict[str, Any]:
        """Check cron run history parse coverage via last-run summary files."""
        # We infer parse health from the presence of cron_summary files written
        # by the most recent runs.  A parse error would leave the file absent or corrupt.
        summaries_dir = self.project_root / "data" / "audits"
        try:
            cron_summaries = list(summaries_dir.glob("cron_run_summary_*.json")) if summaries_dir.exists() else []
            valid = 0
            invalid = 0
            for f in cron_summaries:
                try:
                    json.loads(f.read_text())
                    valid += 1
                except Exception:
                    invalid += 1
            total = valid + invalid
            coverage = round(valid / total, 3) if total > 0 else None
            ok = coverage is not None and coverage >= 1.0
            return {
                "critical": False, "ok": ok,
                "valid_count": valid, "invalid_count": invalid,
                "parse_coverage": coverage,
                "detail": "data/audits/cron_run_summary_*.json",
            }
        except Exception as exc:
            return {"critical": False, "ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_runtime_mode(self) -> str:
        if not self.runtime_config.exists():
            return "unknown"
        try:
            data = yaml.safe_load(self.runtime_config.read_text())
            return data.get("mode", "unknown")
        except Exception:
            return "error"

    def _check_api_keys(self) -> bool:
        if not self.env_file.exists():
            return False
        content = self.env_file.read_text()
        required_keys = ["FINNHUB_API_KEY"]
        for key in required_keys:
            if f"{key}=your_key_here" in content or f"{key}=" not in content:
                return False
        return True
    
    def _get_runtime_mode(self) -> str:
        """Get current runtime mode."""
        if not self.runtime_config.exists():
            return "unknown"
        
        try:
            data = yaml.safe_load(self.runtime_config.read_text())
            return data.get("mode", "unknown")
        except Exception:
            return "error"
    
    def _check_api_keys(self) -> bool:
        """Check if API keys are configured."""
        if not self.env_file.exists():
            return False
        
        content = self.env_file.read_text()
        required_keys = ["FINNHUB_API_KEY", "FRED_API_KEY"]
        
        for key in required_keys:
            if f"{key}=your_key_here" in content or f"{key}=" not in content:
                return False
        
        return True
