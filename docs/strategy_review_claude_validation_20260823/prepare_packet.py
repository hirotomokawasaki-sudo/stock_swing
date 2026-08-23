#!/usr/bin/env python3
"""Build the self-contained Claude validation packet and zip archive."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path


PACKET_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKET_DIR.parents[1]
SOURCE_DIR = PACKET_DIR / "source_files"
EVIDENCE_DIR = PACKET_DIR / "evidence"
ZIP_PATH = PACKET_DIR.parent / f"{PACKET_DIR.name}.zip"

SOURCE_FILES = [
    "scripts/r11_backtest_engine.py",
    "scripts/r11_fetch_historical_data.py",
    "scripts/r11b_param_search.py",
    "scripts/r11c2_regime_filter_backtest.py",
    "scripts/check_go_no_go.py",
    "config/strategy/breakout_momentum_v1.yaml",
    "config/strategy/event_swing_v1.yaml",
    "config/strategy/simple_exit_v2.yaml",
    "src/stock_swing/feature_engine/price_momentum_feature.py",
    "src/stock_swing/strategy_engine/breakout_momentum_strategy.py",
    "src/stock_swing/strategy_engine/event_swing_strategy.py",
    "src/stock_swing/strategy_engine/simple_exit_v2_strategy.py",
    "src/stock_swing/risk/position_sizing.py",
    "src/stock_swing/risk/promotion_gate.py",
    "src/stock_swing/reporting/console_summary.py",
    "src/stock_swing/cli/paper_demo.py",
    "console/services/dashboard_service.py",
    "console/adapters/system_adapter.py",
    "docs/console_improvement_tasks.md",
]

EVIDENCE_FILES = [
    "reports/r11_backtest_results.json",
    "reports/r11b_param_search_results.json",
    "reports/r11c2_regime_filter_results.json",
    "reports/signal_strength_decile.json",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def copy_inputs() -> dict[str, str]:
    if SOURCE_DIR.exists():
        shutil.rmtree(SOURCE_DIR)
    SOURCE_DIR.mkdir(parents=True)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    hashes: dict[str, str] = {}
    for relative in SOURCE_FILES:
        src = REPO_ROOT / relative
        if not src.exists():
            raise FileNotFoundError(src)
        dst = SOURCE_DIR / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        hashes[f"source_files/{relative}"] = sha256(dst)

    for relative in EVIDENCE_FILES:
        src = REPO_ROOT / relative
        if not src.exists():
            raise FileNotFoundError(src)
        dst = EVIDENCE_DIR / Path(relative).name
        shutil.copy2(src, dst)
        hashes[f"evidence/{dst.name}"] = sha256(dst)
    return hashes


def refresh_metrics() -> None:
    subprocess.run(
        [sys.executable, str(PACKET_DIR / "reproduce_review_metrics.py"), "--refresh"],
        cwd=PACKET_DIR,
        check=True,
    )


def write_provenance(copied_hashes: dict[str, str]) -> None:
    relevant_status = git("status", "--short", "--", *SOURCE_FILES)
    payload = {
        "schema": "strategy-review-validation-provenance-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_head": git("rev-parse", "HEAD"),
        "git_head_subject": git("log", "-1", "--format=%s"),
        "git_head_time": git("log", "-1", "--format=%aI"),
        "relevant_source_worktree_status": relevant_status or "clean",
        "live_tracker_sha256": sha256(REPO_ROOT / "data/tracking/pnl_state.json"),
        "copied_input_sha256": copied_hashes,
        "privacy": [
            "sanitized trade evidence excludes account IDs",
            "sanitized trade evidence excludes broker order/fill/trade IDs",
            "source code/config snapshots contain no credential files",
        ],
    }
    (EVIDENCE_DIR / "PROVENANCE.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_manifest() -> None:
    entries: list[str] = []
    for path in sorted(PACKET_DIR.rglob("*")):
        if not path.is_file():
            continue
        if path.name == "MANIFEST.sha256" or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(PACKET_DIR)
        entries.append(f"{sha256(path)}  {relative.as_posix()}")
    (PACKET_DIR / "MANIFEST.sha256").write_text("\n".join(entries) + "\n", encoding="utf-8")


def write_zip() -> None:
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(PACKET_DIR.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.write(path, Path(PACKET_DIR.name) / path.relative_to(PACKET_DIR))


def main() -> int:
    refresh_metrics()
    copied_hashes = copy_inputs()
    write_provenance(copied_hashes)
    write_manifest()
    subprocess.run(["sh", str(PACKET_DIR / "verify_bundle.sh")], cwd=PACKET_DIR, check=True)
    write_zip()
    print(f"packet: {PACKET_DIR}")
    print(f"archive: {ZIP_PATH} ({ZIP_PATH.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
