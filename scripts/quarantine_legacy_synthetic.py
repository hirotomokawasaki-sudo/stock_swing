#!/usr/bin/env python3
"""FIX-SOURCE-4: Quarantine legacy synthetic raw data files.

Moves files with is_synthetic=True or synthetic news content to
data/raw_legacy_untrusted/ WITHOUT deleting originals.
Files are logged to data/audits/legacy_synthetic_quarantine.json.

Usage:
    python scripts/quarantine_legacy_synthetic.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
from datetime import datetime, timezone

project_root = pathlib.Path(__file__).resolve().parents[1]
RAW_DIR    = project_root / "data" / "raw"
QUARANTINE = project_root / "data" / "raw_legacy_untrusted"
LOG_PATH   = project_root / "data" / "audits" / "legacy_synthetic_quarantine.json"


def is_synthetic(data: dict) -> bool:
    if data.get("is_synthetic"):
        return True
    if data.get("quality_status") == "synthetic":
        return True
    payload = data.get("payload", {})
    if isinstance(payload, dict):
        news = payload.get("news", [])
        if isinstance(news, list):
            for item in news:
                if isinstance(item, dict):
                    if "example.local" in item.get("url", ""):
                        return True
                    if item.get("source") == "synthetic":
                        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Quarantine legacy synthetic raw files.")
    parser.add_argument("--dry-run", action="store_true", help="List files without moving.")
    args = parser.parse_args()

    if not RAW_DIR.exists():
        print("data/raw not found — nothing to quarantine.")
        return 0

    files = list(RAW_DIR.rglob("*.json"))
    synthetic_files: list[str] = []
    errors: list[str] = []

    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if is_synthetic(data):
                synthetic_files.append(str(f.relative_to(project_root)))
        except Exception as exc:
            errors.append(f"{f}: {exc}")

    print(f"Found {len(synthetic_files)} synthetic files out of {len(files)} total.")
    print(f"Errors reading files: {len(errors)}")

    if args.dry_run:
        for s in synthetic_files[:20]:
            print(f"  WOULD MOVE: {s}")
        if len(synthetic_files) > 20:
            print(f"  ... and {len(synthetic_files) - 20} more")
        print("Dry-run: no files moved.")
        return 0

    moved: list[str] = []
    move_errors: list[str] = []
    for rel_str in synthetic_files:
        src = project_root / rel_str
        # Preserve directory structure under QUARANTINE
        dest = QUARANTINE / pathlib.Path(rel_str).relative_to("data/raw")
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(src), str(dest))
            moved.append(rel_str)
        except Exception as exc:
            move_errors.append(f"{rel_str}: {exc}")

    log = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "total_raw_files": len(files),
        "synthetic_found": len(synthetic_files),
        "moved": len(moved),
        "move_errors": len(move_errors),
        "quarantine_dir": str(QUARANTINE.relative_to(project_root)),
        "files": moved,
        "errors": errors + move_errors,
    }
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Moved {len(moved)} files to {QUARANTINE.relative_to(project_root)}")
    if move_errors:
        print(f"Move errors: {len(move_errors)}", file=sys.stderr)
        for e in move_errors:
            print(f"  {e}", file=sys.stderr)

    return 0 if not move_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
