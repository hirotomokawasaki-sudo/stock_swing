#!/usr/bin/env python3
"""Read the latest promotion snapshot and emit a stable correlation state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_SNAPSHOT_DIR = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "audits"
    / "promotion_gate_snapshots"
)


def read_observation(snapshot_dir: Path) -> dict:
    snapshots = sorted(snapshot_dir.glob("snapshot_*.json"))
    if not snapshots:
        raise FileNotFoundError(f"no promotion snapshot in {snapshot_dir}")

    latest = snapshots[-1]
    data = json.loads(latest.read_text(encoding="utf-8"))
    gate = ((data.get("promotion") or {}).get("pairwise_correlation") or {})
    if "pass" not in gate:
        raise ValueError("latest snapshot has no pairwise_correlation verdict")

    pairs = sorted(str(item) for item in (gate.get("actual") or []) if item)
    status = "clear" if bool(gate["pass"]) and not pairs else "alert"
    if status == "alert" and not pairs:
        pairs = ["pairwise_correlation failed without pair detail"]

    return {
        "status": status,
        "pairs": pairs,
        "signature": "|".join(pairs),
        "snapshot": latest.name,
        "captured_at": data.get("captured_at"),
        "detail": gate.get("detail"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    args = parser.parse_args()
    try:
        observation = read_observation(args.snapshot_dir)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(observation, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
