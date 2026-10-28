"""Read-only, hash-qualified documentary evidence; never a trading gate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

DOCUMENTS = {
    "roadmap": "docs/console_improvement_tasks.md",
    "plan": "docs/strategy_improvement_validation_plan_20261020.md",
    "operating": "docs/investment_operating_brief_20261028.md",
    "readiness": "docs/p4_advance_review_20261028.md",
    "review": "docs/closure_research_review_20261028/FIRST_REVIEW_DRAFT.md",
    "costs": "docs/integration_ops_cost_20261028/COSTS.md",
    "safety": "docs/emergency_corrections_20261028/README.md",
}


def get_evidence_document(root: Path, name: str) -> Path | None:
    """Only explicitly allowlisted non-secret documents may be served."""
    relative = DOCUMENTS.get(name)
    if not relative:
        return None
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        return None
    return path


def get_console_evidence(root: Path) -> dict:
    """Unknown on missing/corrupt input; a source edit invalidates currency."""
    unknown = {"status": "unknown", "reviewed_at": None, "items": [],
               "reason": "確認資料未取得。稼働・利益効果の証明ではありません。"}
    path = root / "docs/console_evidence_20261028/status.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("schema_version") != 1:
            return unknown
        if not isinstance(raw.get("reviewed_at"), str):
            return unknown
        from datetime import datetime
        stamp = datetime.fromisoformat(raw["reviewed_at"].replace("Z", "+00:00"))
        if stamp.tzinfo is None or not isinstance(raw["items"], list) or not raw["items"]:
            return unknown
        items = []
        stale = False
        for row in raw["items"]:
            if not isinstance(row, dict) or not all(isinstance(row.get(k), str) and row[k] for k in ("title", "state", "detail", "source", "sha256")):
                return unknown
            source = get_evidence_document(root, row["source"])
            current = source is not None and hashlib.sha256(source.read_bytes()).hexdigest() == row["sha256"]
            stale |= not current
            items.append({k: row[k] for k in ("title", "state", "detail", "source")}
                         | {"source_current": current,
                            "url": "/api/console-evidence/document?name=" + row["source"]})
        return {"status": "stale" if stale else "current", "reviewed_at": raw["reviewed_at"],
                "items": items, "reason": "根拠文書に変更・欠測あり。状態は再確認が必要。" if stale else "資料時点の確認結果。稼働状態は別途確認。"}
    except (OSError, ValueError, TypeError, KeyError):
        return unknown
