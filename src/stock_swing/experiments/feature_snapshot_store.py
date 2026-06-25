from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FeatureSnapshotRef:
    experiment_id: str
    run_id: str
    decision_id: str
    symbol: str
    path: str


class FeatureSnapshotStore:
    def __init__(self, root: Path, compress: bool = True) -> None:
        self.root = Path(root)
        self.compress = compress
        self.root.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        *,
        experiment_id: str,
        run_id: str,
        decision_id: str,
        symbol: str,
        features: dict[str, Any],
        schema_version: str,
    ) -> FeatureSnapshotRef:
        safe_symbol = symbol.replace("/", "_").upper()
        ext = ".json.gz" if self.compress else ".json"
        path = self.root / experiment_id / run_id / f"{safe_symbol}_{decision_id}{ext}"
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "experiment_id": experiment_id,
            "run_id": run_id,
            "decision_id": decision_id,
            "symbol": symbol,
            "schema_version": schema_version,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "features": features,
        }

        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if self.compress:
            with gzip.open(path, "wt", encoding="utf-8", newline="\n") as fh:
                fh.write(encoded)
                fh.write("\n")
        else:
            path.write_text(encoded + "\n", encoding="utf-8")

        return FeatureSnapshotRef(
            experiment_id=experiment_id,
            run_id=run_id,
            decision_id=decision_id,
            symbol=symbol,
            path=str(path),
        )

    def load(self, ref: FeatureSnapshotRef) -> dict[str, Any]:
        path = Path(ref.path)
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                return json.loads(fh.read())
        return json.loads(path.read_text(encoding="utf-8"))
