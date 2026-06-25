from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_json_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _git_commit(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


@dataclass(frozen=True)
class ExperimentContext:
    experiment_id: str
    run_id: str
    created_at: str
    source_commit: str
    strategy_version: str
    prompt_version: str
    config_hash: str
    feature_schema_version: str
    mode: str = "paper"
    owner: str = "local"
    notes: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def attach_to(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(payload)
        payload["experiment_id"] = self.experiment_id
        payload["run_id"] = self.run_id
        payload["source_commit"] = self.source_commit
        payload["strategy_version"] = self.strategy_version
        payload["prompt_version"] = self.prompt_version
        payload["config_hash"] = self.config_hash
        payload["feature_schema_version"] = self.feature_schema_version
        return payload


def build_experiment_context(
    *,
    repo_root: Path,
    run_id: str,
    strategy_version: str,
    prompt_version: str,
    feature_schema_version: str,
    config_payload: dict[str, Any],
    mode: str = "paper",
    experiment_id: str | None = None,
    notes: str = "",
    tags: list[str] | None = None,
) -> ExperimentContext:
    source_commit = _git_commit(repo_root)
    config_hash = _stable_json_hash(config_payload)

    if experiment_id is None:
        date_key = datetime.now(timezone.utc).strftime("%Y%m%d")
        short_commit = source_commit[:8] if source_commit != "unknown" else "unknown"
        experiment_id = f"exp-{date_key}-{strategy_version}-{prompt_version}-{short_commit}-{config_hash[:8]}"

    return ExperimentContext(
        experiment_id=experiment_id,
        run_id=run_id,
        created_at=_utc_now_iso(),
        source_commit=source_commit,
        strategy_version=strategy_version,
        prompt_version=prompt_version,
        config_hash=config_hash,
        feature_schema_version=feature_schema_version,
        mode=mode,
        owner=os.environ.get("USERNAME") or os.environ.get("USER") or "local",
        notes=notes,
        tags=tags or [],
    )
