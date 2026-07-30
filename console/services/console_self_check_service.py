"""Console self-check service.

Verifies that required data files and optional UI assets are present.
Returns HTTP 200 even when optional files are missing — warnings only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from console.adapters.system_adapter import SystemAdapter


# Files that must exist for JSON APIs to work (critical)
_CRITICAL_FILES: list[tuple[str, str]] = [
    ("pnl_state", "data/tracking/pnl_state.json"),
]

# Files that power richer analytics (warn if absent, don't fail)
# exports/ files are generated artifacts; recent_decisions is populated by cron.
_OPTIONAL_FILES: list[tuple[str, str]] = [
    ("recent_decisions",       "data/decisions/recent_decisions.json"),
    ("exports_summary_stats",  "exports/summary_stats.json"),
    ("exports_closed_trades",  "exports/closed_trades.csv"),
    ("exports_open_positions", "exports/open_positions.csv"),
    ("price_overrides",        "data/price_overrides.json"),
    ("pending_exit_reasons",   "data/tracking/pending_exit_reasons.json"),
]

# Directories that are optional (UI assets)
_OPTIONAL_DIRS: list[tuple[str, str]] = [
    ("static_ui", "console/ui"),
]


def run_self_check(project_root: Path) -> dict[str, Any]:
    """Run all file-existence checks and return a diagnostic dict.

    Args:
        project_root: Absolute path to repo root.

    Returns:
        {ok, root, checks, warnings}
    """
    checks: dict[str, Any] = {}
    warnings: list[str] = []
    any_critical_missing = False

    for key, rel in _CRITICAL_FILES:
        path = project_root / rel
        ok = path.exists()
        checks[key] = {"ok": ok, "path": rel}
        if not ok:
            any_critical_missing = True
            warnings.append(f"Critical file missing: {rel}")

    for key, rel in _OPTIONAL_FILES:
        path = project_root / rel
        ok = path.exists()
        checks[key] = {"ok": ok, "path": rel, "severity": "warning" if not ok else "ok"}
        if not ok:
            warnings.append(f"Optional file missing: {rel} — some analytics will be unavailable.")

    for key, rel in _OPTIONAL_DIRS:
        path = project_root / rel
        ok = path.exists() and path.is_dir()
        checks[key] = {"ok": ok, "path": rel, "severity": "warning" if not ok else "ok"}
        if not ok:
            warnings.append(f"Optional UI assets missing: {rel} — JSON APIs can still operate.")

    system_health = SystemAdapter(project_root).get_health()
    health_status = system_health.get("status", "unknown")
    health_score = int(system_health.get("score", 0) or 0)
    critical_missing = list(system_health.get("critical_missing") or [])
    if critical_missing:
        warnings.append(
            "Critical operational evidence missing: "
            + ", ".join(critical_missing)
        )

    return {
        "ok": not any_critical_missing,
        "root": str(project_root),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "warnings": warnings,
        "health_status": health_status,
        "health_score": health_score,
        "health_evidence_status": system_health.get("evidence_status", "unknown"),
        "critical_missing": critical_missing,
        "health_evidence": system_health.get("evidence", {}),
    }
