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
FETCH_LOOKBACK_DAYS_BUFFER = 15  # extra calendar days beyond lookback_days to survive weekends/holidays


def load_etf_sector_map() -> dict[str, str]:
    registry = read_symbol_registry()
    return {
        sym: info.get("sector")
        for sym, info in registry.items()
        if info.get("asset_class") == "etf" and info.get("sector") and not sym.endswith(".T")
    }


def fetch_bars_as_canonical(symbols: list[str], lookback_days: int) -> list[CanonicalRecord]:
    """Fetch recent daily bars for `symbols` via yfinance and wrap them as
    CanonicalRecord, matching r11_fetch_historical_data.py's proven
    approach (same data source already used for R13-C/R13-D backtests).
    """
    period_days = lookback_days + FETCH_LOOKBACK_DAYS_BUFFER
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

    records = fetch_bars_as_canonical(sorted(sector_map.keys()), args.lookback_days)
    if not records:
        print("ERROR: no price data fetched, aborting.", file=sys.stderr)
        return 1

    feature = SectorMomentumFeature(sector_map=sector_map, lookback_days=args.lookback_days)
    feature_results = feature.compute(records)
    if not feature_results or not feature_results[0].values.get("ranked_sectors"):
        print("WARNING: SectorMomentumFeature produced no ranked sectors (insufficient coverage?)")
        ranked_sectors: list[str] = []
    else:
        ranked_sectors = feature_results[0].values["ranked_sectors"]
        print("Sector ranking (best to worst):")
        for rank, sector in enumerate(ranked_sectors):
            score = feature_results[0].values.get(f"{sector}_score")
            print(f"  #{rank + 1} {sector:<20} {score:+.2%}" if score is not None else f"  #{rank + 1} {sector}")

    strategy = SectorRotationStrategy(top_n=args.top_n)
    signals = strategy.generate(feature_results) if feature_results else []
    candidate_symbols = sorted({s.symbol for s in signals})
    top_sectors = ranked_sectors[: args.top_n]

    print(f"\nsector_rotation_v1 would signal BUY for {len(candidate_symbols)} symbol(s): {candidate_symbols}")

    state_store = SectorRotationStateStore(path=args.state_path)
    prior_state = state_store.load()
    today = date.today()
    rebalance_due = is_rebalance_due(prior_state, today, hold_days=args.hold_days)
    diff = compute_rebalance_diff(
        current_holdings=(prior_state.current_holdings if prior_state else []),
        new_holdings=candidate_symbols,
    )

    print(f"\nRebalance due today: {rebalance_due} (hold_days={args.hold_days})")
    print(f"  Would enter: {diff.enter}")
    print(f"  Would exit:  {diff.exit}")
    print(f"  Would hold:  {diff.hold}")

    record = {
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "date": today.isoformat(),
        "top_n": args.top_n,
        "lookback_days": args.lookback_days,
        "hold_days": args.hold_days,
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

    if args.dry_run:
        print("\n(--dry-run: nothing written to shadow log or shadow state)")
        return 0

    log_shadow(record, shadow_log_path=PROJECT_ROOT / SHADOW_LOG_RELATIVE)

    # Only advance the SHADOW state (never the real production state file --
    # see the --state-path guard above) when a rebalance was due, so the
    # shadow's own "would-be" holdings tracking stays internally consistent
    # across runs (otherwise every run would look "due" forever).
    if rebalance_due:
        from stock_swing.strategy_engine.sector_rotation_state import advance_rebalance_state
        new_state = advance_rebalance_state(prior_state, today, top_sectors, candidate_symbols)
        state_store.save(new_state)
        print(f"\nShadow state advanced: rebalance_count={new_state.rebalance_count}")

    print(f"\nAppended shadow record to {PROJECT_ROOT / SHADOW_LOG_RELATIVE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
