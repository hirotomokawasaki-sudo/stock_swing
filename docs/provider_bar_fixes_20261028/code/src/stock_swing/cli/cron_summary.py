"""Helpers for compact machine-readable cron summaries."""

from __future__ import annotations

import json
from typing import Any, Mapping


CRON_SUMMARY_PREFIX = "CRON_SUMMARY_JSON="


def emit_cron_summary(summary: Mapping[str, Any]) -> None:
    """Print one compact summary line that wrappers can extract reliably."""
    print(
        f"{CRON_SUMMARY_PREFIX}"
        f"{json.dumps(summary, ensure_ascii=False, separators=(',', ':'))}"
    )
