"""Historical backfill for Plan B (volatility_gate) / Plan C (distance_from_high)
shadow classification — 2026-08-08 data-accumulation acceleration follow-up.

Purpose
-------
Plan B/C (2026-08-07, NBIS incident follow-up) only log shadow observations
for *new* BUY decisions going forward, so the 2026-08-14 (1-week volume
check) and 2026-08-21 (mid-review/promotion decision) reviews would have to
wait on live cron accumulation from a near-zero starting point (see
docs/daily_logs/2026-08-08.md investigation: "データ蓄積状況：かなり薄い").

This script retroactively applies the *same* classify_buy_volatility() /
classify_bounce_candidate() logic (unchanged, read-only) to every historical
BUY decision already on disk (data/decisions/decision_*.json, ~2,300 files),
using the Finnhub metric snapshot that was actually the freshest one
available *at the time of that decision* (not "latest" -- using today's
latest snapshot for a June decision would be a lookahead bug).

IMPORTANT: This is explicitly a *separate, clearly-labeled* dataset, not a
substitute for live shadow accumulation:
  - Output goes to data/volatility_gate_historical_backfill_log.jsonl and
    data/distance_from_high_historical_backfill_log.jsonl -- distinct
    filenames from the live data/volatility_gate_shadow_log.jsonl and
    data/distance_from_high_log.jsonl.
  - Every record is tagged "source": "historical_backfill" (vs "live" for
    the real paper_demo.py shadow logs) so any downstream review script
    can filter/report on the two separately and never silently merge them.
  - This does NOT change how paper_demo.py behaves in shadow mode; it only
    reads existing decision files and existing Finnhub raw snapshots.

Metric-snapshot lookup
-----------------------
collect_data.py's stock/metric collector runs every ~4h (news_collection
cron) and writes data/raw/finnhub/finnhub_{symbol_lower}_{timestamp}.json.
For each historical decision, we pick the snapshot with the latest
fetched_at that is still <= the decision's generated_at (i.e. what would
have actually been on disk at decision time), falling back to "closest
snapshot within +/- lookback_hours" if none exists before it (early-history
edge case). If no snapshot is found within the window, the decision is
skipped (counted in "no_metric_data").

Momentum extraction
--------------------
BreakoutMomentumStrategy's evidence.notes contains a string like
"Strong bullish momentum (29.30%) indicates breakout"; momentum_pct is
parsed from that via regex (needed for Plan C's classify_bounce_candidate).
EventSwingStrategy decisions (no such note) are still run through Plan B
(volatility) but skipped for Plan C (no momentum concept for that strategy).
"""

from __future__ import annotations

import glob
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from stock_swing.risk.volatility_gate import (
    VolatilityGateConfig,
    classify_buy_volatility,
)
from stock_swing.risk.distance_from_high import (
    DistanceFromHighConfig,
    classify_bounce_candidate,
)

FINNHUB_RAW_DIR = ROOT / "data" / "raw" / "finnhub"
DECISIONS_DIR = ROOT / "data" / "decisions"
VOL_OUT_PATH = ROOT / "data" / "volatility_gate_historical_backfill_log.jsonl"
DIST_OUT_PATH = ROOT / "data" / "distance_from_high_historical_backfill_log.jsonl"

MOMENTUM_RE = re.compile(r"momentum \(([-+]?\d+(?:\.\d+)?)%\)")

# Metric snapshots refresh ~every 4h; allow a generous lookback so early
# history (before Finnhub collection had run for that symbol yet) isn't
# silently excluded when a slightly-later snapshot would suffice.
LOOKBACK_HOURS = 12
LOOKAHEAD_HOURS = 4  # small forward tolerance for the earliest few decisions


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _load_symbol_metric_index(symbol: str) -> list[tuple[datetime, dict]]:
    """Return sorted [(fetched_at, metric_payload), ...] for *symbol*."""
    sym_lower = symbol.strip().lower()
    candidates = sorted(FINNHUB_RAW_DIR.glob(f"finnhub_{sym_lower}_*.json"))
    candidates = [p for p in candidates if "_news_" not in p.name]
    index: list[tuple[datetime, dict]] = []
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        fetched_at = _parse_iso(str(data.get("fetched_at") or ""))
        payload = data.get("payload") or {}
        metric = payload.get("metric") if isinstance(payload, dict) else None
        if fetched_at is None or not isinstance(metric, dict):
            continue
        index.append((fetched_at, metric))
    index.sort(key=lambda x: x[0])
    return index


def _lookup_metric_at(
    index: list[tuple[datetime, dict]], at_time: datetime
) -> dict | None:
    """Snapshot with the latest fetched_at <= at_time (within LOOKBACK_HOURS),
    falling back to the earliest snapshot within LOOKAHEAD_HOURS after
    at_time if nothing prior exists."""
    if not index:
        return None
    lo = at_time - timedelta(hours=LOOKBACK_HOURS)
    best: dict | None = None
    for fetched_at, metric in index:
        if fetched_at > at_time:
            break
        if fetched_at >= lo:
            best = metric
    if best is not None:
        return best
    # Fallback: earliest snapshot slightly after at_time (covers the very
    # first few decisions for a symbol, before its first metric fetch).
    hi = at_time + timedelta(hours=LOOKAHEAD_HOURS)
    for fetched_at, metric in index:
        if at_time <= fetched_at <= hi:
            return metric
        if fetched_at > hi:
            break
    return None


def main() -> None:
    vol_config = VolatilityGateConfig.from_env()
    dist_config = DistanceFromHighConfig.from_env()

    decision_files = sorted(glob.glob(str(DECISIONS_DIR / "decision_*.json")))
    print(f"Scanning {len(decision_files)} decision files for historical BUY signals...")

    metric_index_cache: dict[str, list[tuple[datetime, dict]]] = {}

    n_buy = 0
    n_vol_evaluated = 0
    n_vol_no_metric = 0
    n_vol_would_block = 0
    n_dist_evaluated = 0
    n_dist_no_data = 0
    n_dist_bounce_candidates = 0
    n_written_already = 0

    vol_records = []
    dist_records = []

    for fpath in decision_files:
        try:
            d = json.loads(Path(fpath).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if d.get("action") != "buy":
            continue
        n_buy += 1

        symbol = d.get("symbol") or "?"
        generated_at = _parse_iso(d.get("generated_at") or "")
        if generated_at is None:
            continue

        if symbol not in metric_index_cache:
            metric_index_cache[symbol] = _load_symbol_metric_index(symbol)
        metric_payload = _lookup_metric_at(metric_index_cache[symbol], generated_at)

        # Plan B: volatility gate (works for any strategy)
        vol_result = classify_buy_volatility(symbol, metric_payload, config=vol_config)
        n_vol_evaluated += 1
        if metric_payload is None:
            n_vol_no_metric += 1
        if vol_result.would_block:
            n_vol_would_block += 1
        vol_records.append(
            {
                "logged_at": datetime.now(timezone.utc).isoformat(),
                "source": "historical_backfill",
                "decision_generated_at": d.get("generated_at"),
                "decision_id": d.get("decision_id"),
                "strategy_id": d.get("strategy_id"),
                "symbol": symbol,
                "would_block": vol_result.would_block,
                "reason": vol_result.reason,
                "return_std_3m_pct": vol_result.return_std_3m_pct,
                "mode": vol_result.mode,
            }
        )

        # Plan C: distance-from-high (needs momentum; only meaningful for
        # momentum-driven strategies whose evidence.notes carries it)
        notes = d.get("evidence", {}).get("notes") or []
        momentum_pct = None
        for note in notes:
            m = MOMENTUM_RE.search(str(note))
            if m:
                momentum_pct = float(m.group(1))
                break
        if momentum_pct is not None:
            latest_close = d.get("evidence", {}).get("latest_close")
            dist_result = classify_bounce_candidate(
                symbol, latest_close, momentum_pct, metric_payload, config=dist_config
            )
            n_dist_evaluated += 1
            if dist_result.distance_from_high_pct is None:
                n_dist_no_data += 1
            if dist_result.is_bounce_candidate:
                n_dist_bounce_candidates += 1
            dist_records.append(
                {
                    "logged_at": datetime.now(timezone.utc).isoformat(),
                    "source": "historical_backfill",
                    "decision_generated_at": d.get("generated_at"),
                    "decision_id": d.get("decision_id"),
                    "strategy_id": d.get("strategy_id"),
                    "symbol": symbol,
                    "is_bounce_candidate": dist_result.is_bounce_candidate,
                    "distance_from_high_pct": dist_result.distance_from_high_pct,
                    "momentum_pct": dist_result.momentum_pct,
                    "week52_high": dist_result.week52_high,
                    "week52_high_date": dist_result.week52_high_date,
                    "reason": dist_result.reason,
                }
            )

    VOL_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(VOL_OUT_PATH, "w", encoding="utf-8") as fh:
        for rec in vol_records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    DIST_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DIST_OUT_PATH, "w", encoding="utf-8") as fh:
        for rec in dist_records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print()
    print("=" * 70)
    print("Historical backfill summary (source=historical_backfill, NOT live)")
    print("=" * 70)
    print(f"Total BUY decisions scanned: {n_buy}")
    print()
    print(f"Plan B (volatility_gate): {n_vol_evaluated} evaluated, "
          f"{n_vol_no_metric} no_metric_data, {n_vol_would_block} would_block "
          f"(cap={vol_config.max_3m_return_std_pct:.1f}%)")
    print(f"  -> wrote {len(vol_records)} records to {VOL_OUT_PATH}")
    print()
    print(f"Plan C (distance_from_high): {n_dist_evaluated} evaluated "
          f"(momentum-bearing strategies only), {n_dist_no_data} no_data, "
          f"{n_dist_bounce_candidates} bounce_candidates flagged")
    print(f"  -> wrote {len(dist_records)} records to {DIST_OUT_PATH}")
    print()
    print("NOTE: these files are separate from the live shadow logs and are")
    print("tagged source=historical_backfill; use for early calibration context")
    print("only, not as a substitute for forward-looking live shadow volume.")


if __name__ == "__main__":
    main()
