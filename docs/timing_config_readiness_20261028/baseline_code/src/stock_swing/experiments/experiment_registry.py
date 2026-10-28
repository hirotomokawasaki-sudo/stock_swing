from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from stock_swing.experiments.experiment_context import ExperimentContext


class ExperimentRegistry:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "experiments.jsonl"

    def register(self, context: ExperimentContext, extra: dict[str, Any] | None = None) -> Path:
        payload = context.to_dict()
        if extra:
            payload["extra"] = extra

        experiment_dir = self.root / context.experiment_id
        experiment_dir.mkdir(parents=True, exist_ok=True)

        self._write_json_atomic(experiment_dir / "manifest.json", payload)
        self._append_jsonl(self.index_path, payload)
        return experiment_dir

    def get_manifest(self, experiment_id: str) -> dict[str, Any]:
        path = self.root / experiment_id / "manifest.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def list_experiments(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.index_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.index_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows[-limit:]

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(payload, fh, ensure_ascii=False, sort_keys=True, indent=2)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    @staticmethod
    def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
