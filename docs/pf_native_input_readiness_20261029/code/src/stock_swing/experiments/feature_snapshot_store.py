from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stock_swing.experiments.measurement_capture import _publish


@dataclass(frozen=True)
class FeatureSnapshotRef:
    experiment_id: str
    run_id: str
    decision_id: str
    symbol: str
    path: str
    sha256: str | None = None  # Legacy references remain readable, but are not hash receipts.


def decision_snapshot_features(signal: Any, decision: Any) -> dict[str, Any]:
    """Engine-stage snapshot, not a claim that downstream filters accepted it."""
    return {
        "strategy_id": signal.strategy_id,
        "action": decision.action,
        "signal_action": signal.action,
        "decision_stage": "decision_engine",
        "decision_time": decision.decision_time,
        "config_hash": decision.config_hash,
        "risk_state": decision.risk_state,
        "deny_reasons": list(decision.deny_reasons or []),
        "signal_strength": signal.signal_strength,
        "confidence": signal.confidence,
        "time_horizon": signal.time_horizon,
        "feature_refs": list(signal.feature_refs or []),
        "metadata": dict(signal.metadata or {}),
        "evidence": {k: v for k, v in (decision.evidence or {}).items() if k != "notes"},
    }


def _no_symlinks(path: Path) -> None:
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("symlinked feature snapshot path")


def _decode(path: Path, raw: bytes) -> dict[str, Any]:
    return json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)


class FeatureSnapshotStore:
    def __init__(self, root: Path, compress: bool = True) -> None:
        self.root = Path(root)
        self.compress = compress
        _no_symlinks(self.root)
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
        for token in (experiment_id, run_id, decision_id):
            if not isinstance(token, str) or not token or token in (".", "..") or any(c in token for c in ("/", "\\", "\x00")):
                raise ValueError("invalid feature snapshot identity")
        safe_symbol = symbol.replace("/", "_").upper()
        if not safe_symbol or any(c in safe_symbol for c in ("\\", "\x00")):
            raise ValueError("invalid feature snapshot symbol")
        ext = ".json.gz" if self.compress else ".json"
        path = self.root / experiment_id / run_id / f"{safe_symbol}_{decision_id}{ext}"
        _no_symlinks(path)
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
        for name in ("config_hash", "decision_time", "risk_state", "deny_reasons"):
            if name in features:
                payload[name] = features[name]
        if path.exists():
            raw = path.read_bytes()
            previous = _decode(path, raw)
            if {k: v for k, v in previous.items() if k != "created_at"} != {k: v for k, v in payload.items() if k != "created_at"}:
                raise ValueError("immutable feature snapshot identity conflict")
        else:
            encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
            raw = gzip.compress(encoded, mtime=0) if self.compress else encoded
            _publish(path, raw)

        return FeatureSnapshotRef(
            experiment_id=experiment_id,
            run_id=run_id,
            decision_id=decision_id,
            symbol=symbol,
            path=str(path),
            sha256=hashlib.sha256(raw).hexdigest(),
        )

    def load(self, ref: FeatureSnapshotRef) -> dict[str, Any]:
        path = Path(ref.path)
        _no_symlinks(path)
        raw = path.read_bytes()
        if ref.sha256 is not None and hashlib.sha256(raw).hexdigest() != ref.sha256:
            raise ValueError("feature snapshot hash drift")
        payload = _decode(path, raw)
        if any(payload.get(k) != getattr(ref, k) for k in ("experiment_id", "run_id", "decision_id", "symbol")):
            raise ValueError("feature snapshot identity drift")
        return payload
