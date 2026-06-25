#!/usr/bin/env python3
"""Secret scan script for CI (P5-A).

Scans the repository for patterns that look like real API keys or secrets.
Known safe patterns (***REDACTED***, <masked>) are explicitly allowed.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
    "data/raw", "data/news", "data/archive",
}
SKIP_EXTENSIONS = {".pyc", ".pyo", ".png", ".jpg", ".jpeg", ".gif", ".zip"}
SKIP_FILES = {
    "tests/unit/test_secret_scan.py",
}

PATTERNS = [
    re.compile(r"BROKER_API_SECRET\s*=\s*(?!\*\*\*REDACTED\*\*\*|<masked>|\s*$).{8,}"),
    re.compile(r"BROKER_API_KEY\s*=\s*(?!\*\*\*REDACTED\*\*\*|<masked>|\s*$)[A-Za-z0-9]{16,}"),
    re.compile(r"TELEGRAM_BOT_TOKEN\s*=\s*(?!\*\*\*REDACTED\*\*\*|<masked>|\s*$)\d{8,}"),
    re.compile(r"(?i)api[_-]?secret\s*=\s*['\"]?[A-Za-z0-9_\-]{32,}"),
    re.compile(r"APCA-API-SECRET-KEY:\s*[A-Za-z0-9_\-]{32,}"),
]

SAFE_MARKERS = {
    "***REDACTED***",
    "<masked>",
    "your-api-key",
    "your-secret",
    "your-alpaca-api-key",
    "your-alpaca-api-secret",
    "example",
}


def should_skip(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if path.name.startswith(".env"):
        return True
    if rel.as_posix() in SKIP_FILES:
        return True
    for skip_dir in SKIP_DIRS:
        if skip_dir in str(rel):
            return True
    return path.suffix in SKIP_EXTENSIONS


def main() -> int:
    findings = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or should_skip(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if any(marker in line for marker in SAFE_MARKERS):
                continue
            for pattern in PATTERNS:
                if pattern.search(line):
                    findings.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()[:80]}")
                    break

    if findings:
        print(f"ERROR: {len(findings)} potential secret(s) found:")
        for f in findings:
            print(f"  {f}")
        return 1
    print(f"OK: Secret scan passed ({ROOT} scanned).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
