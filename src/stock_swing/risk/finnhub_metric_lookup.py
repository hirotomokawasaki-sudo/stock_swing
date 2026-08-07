"""Shared helper: load the most recent Finnhub basic-financials ("stock/metric")
snapshot for a symbol from the raw data lake.

Both volatility_gate.py (Plan B) and distance_from_high.py (Plan C) — the
2026-08-07 NBIS incident follow-ups — need the same per-symbol metric fields
(3MonthADReturnStd, 52WeekHigh, 52WeekHighDate, ...) that collect_data.py
already fetches via FinnhubClient.fetch_basic_financials() and writes to
data/raw/finnhub/finnhub_{symbol_lower}_{timestamp}.json (see
collect_data.collect_finnhub() and _write_raw_snapshot()). paper_demo.py does
not fetch this data itself (it only fetches price bars via
HybridDataFetcher), so this module reads the most recent snapshot already on
disk from the separate stock_swing_news_collection cron job (runs every 4h).

This is a best-effort, read-only lookup: metric data can be up to ~4h stale
relative to a given paper_demo run. That is acceptable for the shadow/
observability-only gates that consume it (nothing here blocks a trade), and
matches how sector_shock_hold.py's benchmark-return lookups behave.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_latest_finnhub_metric(
    symbol: str,
    finnhub_raw_dir: Path | str,
) -> dict[str, Any] | None:
    """Return the metric payload from the most recent finnhub 'stock/metric'
    snapshot for *symbol*, or None if no snapshot exists.

    Args:
        symbol: Stock symbol (case-insensitive).
        finnhub_raw_dir: Directory containing finnhub_*.json raw snapshots
            (typically project_root / "data" / "raw" / "finnhub").

    Returns:
        The `payload["metric"]` dict from the freshest matching snapshot
        (by `fetched_at`), or None if none found / unreadable.
    """
    raw_dir = Path(finnhub_raw_dir)
    if not raw_dir.exists():
        return None

    sym_lower = symbol.strip().lower()
    if not sym_lower:
        return None

    # collect_data.py writes finnhub_{symbol_lower}_{timestamp}.json for
    # stock/metric snapshots, and finnhub_{symbol_lower}_news_{timestamp}.json
    # for company-news. Match the metric files only.
    candidates = sorted(raw_dir.glob(f"finnhub_{sym_lower}_*.json"))
    candidates = [p for p in candidates if "_news_" not in p.name]
    if not candidates:
        return None

    best_metric: dict[str, Any] | None = None
    best_fetched_at = ""
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        fetched_at = str(data.get("fetched_at") or "")
        payload = data.get("payload") or {}
        metric = payload.get("metric") if isinstance(payload, dict) else None
        if not isinstance(metric, dict):
            continue
        if fetched_at > best_fetched_at:
            best_fetched_at = fetched_at
            best_metric = metric

    return best_metric
