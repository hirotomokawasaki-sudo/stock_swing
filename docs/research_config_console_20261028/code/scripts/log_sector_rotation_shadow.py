#!/usr/bin/env python3
"""Daily shadow-signal logger for R13-D ETF sector rotation
(sector_rotation_v1) -- SHADOW MODE, no orders, no broker connection.

Background
----------
R13-D Phase 1 (feasibility, GO), Phase 2 (SectorMomentumFeature +
SectorRotationStrategy implementation), and Phase 3 (RebalanceState
persistence machine) are all complete (see docs/console_improvement_
tasks.md's R13-D section and docs/r13d_*_202608*/). None of it has ever
been wired into paper_demo.py or any execution path -- Phase 2/3's module
docstrings explicitly say "wiring is a SEPARATE decision requiring
explicit user approval."

2026-08-25/26 session: user asked for cost/benefit of wiring
sector_rotation_v1 for real, then asked for a shadow-equivalent review
period before scheduling that wiring decision -- mirroring the exact
same shadow-before-wiring pattern already used for dip_buy_meanreversion_v1
(R14) and overnight_spillover_v1 (JP semiconductor). This script is that
shadow logger for sector_rotation_v1.

Unlike R14's shadow (which is wired INSIDE paper_demo.py's daily_features
loop because it only needs data paper_demo.py already fetches), this
follows the JP-spillover pattern instead: a STANDALONE daily script using
yfinance (no broker connection needed, same choice R13-D Phase 1's
research script and log_jp_overnight_spillover_shadow.py both made) that
exercises the REAL production classes end-to-end:
  1. Fetch recent daily OHLCV for all sector ETFs (symbol_registry.yaml's
     asset_class=="etf" entries with a `sector` tag) via yfinance.
  2. Build CanonicalRecord bars and run them through the REAL
     SectorMomentumFeature (same class Phase 3 would use in production).
  3. Run SectorRotationStrategy.generate() (same class, same strategy_id
     "sector_rotation_v1") to get today's candidate buy signals.
  4. Load the REAL SectorRotationStateStore (same class Phase 3 built) to
     check is_rebalance_due() and compute what compute_rebalance_diff()
     would produce -- WITHOUT ever calling save() or advance_rebalance_
     state() in a way that persists to the real production state file
     (see --state-path below: shadow runs use a SEPARATE state file,
     never data/sector_rotation_state.json, so this script cannot
     interfere with a future real Phase 3 wiring's state).
  5. Append a structured JSON record to
     data/sector_rotation_shadow_log.jsonl via log_shadow() below.

Never submits an order. Never touches the broker. Never touches the
production RebalanceState file. Safe to run daily via cron ahead of any
wiring decision, exactly like Plan B/C/D/E and the JP spillover shadow.

Usage:
    python scripts/log_sector_rotation_shadow.py [--dry-run] [--top-n 2] [--hold-days 21]
    python scripts/log_sector_rotation_shadow.py --parallel-new-headline
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance is required. pip install yfinance", file=sys.stderr)
    sys.exit(1)

from stock_swing.core.types import CanonicalRecord  # noqa: E402
from stock_swing.feature_engine.sector_momentum_feature import (  # noqa: E402
    DEFAULT_LOOKBACK_DAYS,
    SectorMomentumFeature,
)
from stock_swing.risk.allocation_config import read_symbol_registry  # noqa: E402
from stock_swing.strategy_engine.sector_rotation_state import (  # noqa: E402
    SectorRotationStateStore,
    compute_rebalance_diff,
    is_rebalance_due,
)
from stock_swing.strategy_engine.sector_rotation_strategy import (  # noqa: E402
    SectorRotationStrategy,
)

logger = logging.getLogger(__name__)

SHADOW_LOG_RELATIVE = Path("data/sector_rotation_shadow_log.jsonl")
# IMPORTANT: this is a SEPARATE path from the real Phase-3 production state
# file (data/sector_rotation_state.json) -- see module docstring point 4.
SHADOW_STATE_RELATIVE = Path("data/sector_rotation_shadow_state.json")
NEW_HEADLINE_LOG_RELATIVE = Path("data/sector_rotation_new_headline_shadow_log.jsonl")
NEW_HEADLINE_STATE_RELATIVE = Path("data/sector_rotation_new_headline_shadow_state.json")
NEW_HEADLINE_TOP_N = 2
NEW_HEADLINE_LOOKBACK_DAYS = 126
NEW_HEADLINE_HOLD_DAYS = 21
NEW_HEADLINE_MIN_MEMBERS = 2
# yfinance's ``period=Nd`` is calendar-day based.  A 126-trading-day feature
# therefore needs substantially more than 126 calendar days of history.
FETCH_CALENDAR_DAY_MULTIPLIER = 1.7
FETCH_LOOKBACK_DAYS_BUFFER = 15


def load_etf_sector_map() -> dict[str, str]:
    registry = read_symbol_registry()
    return {
        sym: info.get("sector")
        for sym, info in registry.items()
        if info.get("asset_class") == "etf" and info.get("sector") and not sym.endswith(".T")
    }


def filter_sector_map_by_min_members(
    sector_map: dict[str, str], min_members: int,
) -> tuple[dict[str, str], list[str]]:
    """Return the min-members-safe map and excluded sector names.

    R13-D's new headline requires at least two ETF members per sector.  The
    legacy headline intentionally keeps the historical unfiltered universe so
    both variants can be observed forward in parallel.
    """
    if min_members <= 1:
        return dict(sector_map), []
    counts: dict[str, int] = {}
    for sector in sector_map.values():
        counts[sector] = counts.get(sector, 0) + 1
    eligible = {s for s, n in counts.items() if n >= min_members}
    return (
        {symbol: sector for symbol, sector in sector_map.items() if sector in eligible},
        sorted(set(counts) - eligible),
    )


def fetch_bars_as_canonical(symbols: list[str], lookback_days: int) -> list[CanonicalRecord]:
    """Fetch recent daily bars for `symbols` via yfinance and wrap them as
    CanonicalRecord, matching r11_fetch_historical_data.py's proven
    approach (same data source already used for R13-C/R13-D backtests).
    """
    period_days = int(lookback_days * FETCH_CALENDAR_DAY_MULTIPLIER) + FETCH_LOOKBACK_DAYS_BUFFER
    data = yf.download(
        symbols, period=f"{period_days}d", group_by="ticker",
        progress=False, auto_adjust=False, threads=True,
    )
    records: list[CanonicalRecord] = []
    now = datetime.now(timezone.utc)
    for sym in symbols:
        try:
            df = data[sym] if len(symbols) > 1 else data
            df = df.dropna(how="all")
        except (KeyError, TypeError):
            logger.warning("sector_rotation_shadow: no data for %s, skipping", sym)
            continue
        for idx, row in df.iterrows():
            close = row.get("Close")
            if close is None or (hasattr(close, "__len__") and len(close) == 0):
                continue
            try:
                close_f = float(close)
            except (TypeError, ValueError):
                continue
            event_time = idx.to_pydatetime().replace(hour=21, tzinfo=timezone.utc) if hasattr(idx, "to_pydatetime") else now
            records.append(
                CanonicalRecord(
                    record_id=f"sector_rotation_shadow_{sym}_{idx.date().isoformat()}",
                    schema_version="v1",
                    source="yfinance",
                    source_type="price",
                    symbol=sym,
                    event_type="bar_daily",
                    event_time=event_time,
                    as_of=event_time.isoformat(),
                    ingested_at=now,
                    timezone="UTC",
                    payload_version="v1",
                    payload={"close": close_f},
                    quality_flags=[],
                )
            )
    return records


def log_shadow(record: dict[str, Any], shadow_log_path: Path | str | None = None) -> None:
    """Append a shadow observation record. Mirrors the log_shadow() pattern
    used by overnight_spillover_shadow.py / volatility_gate.py.
    """
    logger.info(
        "sector_rotation SHADOW rebalance_due=%s top_sectors=%s candidate_symbols=%d",
        record.get("rebalance_due"), record.get("top_sectors"),
        len(record.get("candidate_symbols") or []),
    )
    if shadow_log_path is None:
        return
    log_path = Path(shadow_log_path)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
    except OSError as exc:
        logger.warning("sector_rotation_shadow: failed to write log to %s: %s", log_path, exc)


def evaluate_shadow_variant(
    *,
    records: list[CanonicalRecord],
    sector_map: dict[str, str],
    top_n: int,
    lookback_days: int,
    hold_days: int,
    state_path: Path | str,
    headline_id: str,
    min_members: int | None = None,
) -> tuple[dict[str, Any], Any, Any]:
    """Evaluate one shadow headline without touching production state."""
    filtered_map, excluded_sectors = filter_sector_map_by_min_members(
        sector_map, min_members or 1,
    )
    feature = SectorMomentumFeature(sector_map=filtered_map, lookback_days=lookback_days)
    feature_results = feature.compute(records)
    ranked_sectors = (
        feature_results[0].values.get("ranked_sectors", [])
        if feature_results else []
    )
    strategy = SectorRotationStrategy(top_n=top_n)
    signals = strategy.generate(feature_results) if feature_results else []
    candidate_symbols = sorted({s.symbol for s in signals})
    top_sectors = ranked_sectors[:top_n]

    state_store = SectorRotationStateStore(path=state_path)
    prior_state = state_store.load()
    today = date.today()
    rebalance_due = is_rebalance_due(prior_state, today, hold_days=hold_days)
    diff = compute_rebalance_diff(
        current_holdings=(prior_state.current_holdings if prior_state else []),
        new_holdings=candidate_symbols,
    )
    record = {
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "date": today.isoformat(),
        "headline_id": headline_id,
        "top_n": top_n,
        "lookback_days": lookback_days,
        "hold_days": hold_days,
        "min_members": min_members,
        "excluded_sectors": excluded_sectors,
        "ranked_sectors": ranked_sectors,
        "top_sectors": top_sectors,
        "candidate_symbols": candidate_symbols,
        "rebalance_due": rebalance_due,
        "diff_enter": diff.enter,
        "diff_exit": diff.exit,
        "diff_hold": diff.hold,
        "prior_state_rebalance_count": prior_state.rebalance_count if prior_state else 0,
        "mode": "shadow",
    }
    return record, prior_state, state_store


def persist_shadow_variant(
    record: dict[str, Any], prior_state: Any, state_store: Any, log_path: Path,
) -> None:
    """Append a variant record and advance only its dedicated shadow state."""
    log_shadow(record, shadow_log_path=log_path)
    if record["rebalance_due"]:
        from stock_swing.strategy_engine.sector_rotation_state import advance_rebalance_state
        new_state = advance_rebalance_state(
            prior_state,
            date.fromisoformat(record["date"]),
            record["top_sectors"],
            record["candidate_symbols"],
        )
        state_store.save(new_state)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-n", type=int, default=2, help="matches SectorRotationStrategy's Phase 1 default")
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--hold-days", type=int, default=21, help="matches SectorRotationStateStore's Phase 1 default")
    parser.add_argument(
        "--state-path", default=str(PROJECT_ROOT / SHADOW_STATE_RELATIVE),
        help="Shadow-only state file; NEVER point this at the real production "
             "sector_rotation_state.json (see module docstring point 4)",
    )
    parser.add_argument("--dry-run", action="store_true", help="print without writing shadow log/state")
    parser.add_argument(
        "--parallel-new-headline", action="store_true",
        help="also evaluate the min-members-safe 126d headline into separate shadow log/state files",
    )
    args = parser.parse_args()

    if Path(args.state_path).name == "sector_rotation_state.json":
        print(
            "ERROR: --state-path must not be the real production state file "
            "(sector_rotation_state.json). This script is shadow-only.",
            file=sys.stderr,
        )
        return 1

    print("=== Sector Rotation Shadow Signal Logger (R13-D Phase 2.5-equivalent) ===")
    sector_map = load_etf_sector_map()
    if not sector_map:
        print("ERROR: no ETF sector mapping found in symbol_registry.yaml", file=sys.stderr)
        return 1
    print(f"Tracking {len(sector_map)} sector ETFs across {len(set(sector_map.values()))} sectors\n")

    fetch_lookback = max(
        args.lookback_days,
        NEW_HEADLINE_LOOKBACK_DAYS if args.parallel_new_headline else args.lookback_days,
    )
    records = fetch_bars_as_canonical(sorted(sector_map.keys()), fetch_lookback)
    if not records:
        print("ERROR: no price data fetched, aborting.", file=sys.stderr)
        return 1

    record, prior_state, state_store = evaluate_shadow_variant(
        records=records,
        sector_map=sector_map,
        top_n=args.top_n,
        lookback_days=args.lookback_days,
        hold_days=args.hold_days,
        state_path=args.state_path,
        headline_id="legacy_top2_63d",
    )
    ranked_sectors = record["ranked_sectors"]
    if not ranked_sectors:
        print("WARNING: SectorMomentumFeature produced no ranked sectors (insufficient coverage?)")
    else:
        print("Sector ranking (best to worst):")
        for rank, sector in enumerate(ranked_sectors):
            print(f"  #{rank + 1} {sector}")

    candidate_symbols = record["candidate_symbols"]

    print(f"\nsector_rotation_v1 would signal BUY for {len(candidate_symbols)} symbol(s): {candidate_symbols}")

    print(f"\nRebalance due today: {record['rebalance_due']} (hold_days={args.hold_days})")
    print(f"  Would enter: {record['diff_enter']}")
    print(f"  Would exit:  {record['diff_exit']}")
    print(f"  Would hold:  {record['diff_hold']}")

    if args.dry_run:
        print("\n(--dry-run: nothing written to shadow log or shadow state)")
    else:
        persist_shadow_variant(
            record, prior_state, state_store, PROJECT_ROOT / SHADOW_LOG_RELATIVE,
        )

    if args.parallel_new_headline:
        new_record, new_prior_state, new_state_store = evaluate_shadow_variant(
            records=records,
            sector_map=sector_map,
            top_n=NEW_HEADLINE_TOP_N,
            lookback_days=NEW_HEADLINE_LOOKBACK_DAYS,
            hold_days=NEW_HEADLINE_HOLD_DAYS,
            state_path=PROJECT_ROOT / NEW_HEADLINE_STATE_RELATIVE,
            headline_id="new_top2_126d_min2",
            min_members=NEW_HEADLINE_MIN_MEMBERS,
        )
        if not args.dry_run:
            persist_shadow_variant(
                new_record,
                new_prior_state,
                new_state_store,
                PROJECT_ROOT / NEW_HEADLINE_LOG_RELATIVE,
            )
        print("\nNew headline parallel shadow:")
        print(f"  excluded_sectors={new_record['excluded_sectors']}")
        print(f"  top_sectors={new_record['top_sectors']}")
        print(f"  candidates={new_record['candidate_symbols']}")
        print(f"  rebalance_due={new_record['rebalance_due']}")

    if not args.dry_run:
        print(f"\nAppended shadow record to {PROJECT_ROOT / SHADOW_LOG_RELATIVE}")
        if args.parallel_new_headline:
            print(f"Appended new-headline record to {PROJECT_ROOT / NEW_HEADLINE_LOG_RELATIVE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
