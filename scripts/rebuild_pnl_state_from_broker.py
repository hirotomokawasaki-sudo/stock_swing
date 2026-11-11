#!/usr/bin/env python3
"""
Rebuild pnl_state.json from broker order history.

This script fetches all filled orders from the broker and reconstructs
pnl_state.json with accurate entry/exit prices and P&L calculations.

Usage:
    python scripts/rebuild_pnl_state_from_broker.py [--dry-run] [--backup]
"""

import argparse
import json
import math
import os
import shutil
import sys
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stock_swing.sources.broker_client import BrokerClient
from stock_swing.risk.allocation_config import read_symbol_registry
from stock_swing.tracking.pnl_tracker import PnLTracker
from stock_swing.tracking.execution_cost import decimal_value, whole_quantity

# Reuse the single source of truth for "this strategy_id means the trade's
# real origin is unknown / rebuild-synthesized" -- do not duplicate this
# set locally (see AUDIT FIX note on PROVENANCE_FIELDS below for why this
# distinction matters for rebuild attribution preservation).
UNTRACKED_ORIGIN_STRATEGY_IDS = PnLTracker.UNTRACKED_ORIGIN_STRATEGY_IDS

_REGISTRY_PATH = PROJECT_ROOT / "config" / "reference" / "symbol_registry.yaml"


def fetch_yahoo_daily_bars(symbol: str) -> dict[str, tuple[float, float, float]]:
    """Fetch recent daily bars from Yahoo Finance keyed by date."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1mo"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception:
        return {}

    try:
        result = data.get("chart", {}).get("result", [{}])[0]
        timestamps = result.get("timestamp", [])
        quote = result.get("indicators", {}).get("quote", [{}])[0]
        highs = quote.get("high", [])
        lows = quote.get("low", [])
        closes = quote.get("close", [])
    except Exception:
        return {}

    bars: dict[str, tuple[float, float, float]] = {}
    for ts, high, low, close in zip(timestamps, highs, lows, closes):
        if high is None or low is None or close is None:
            continue
        day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        bars[day] = (float(low), float(high), float(close))
    return bars


def maybe_correct_scaled_price(
    symbol: str,
    price: float,
    fill_time: str,
    market_cache: dict[str, dict[str, tuple[float, float, float]]],
) -> tuple[float, int | None]:
    """Correct obvious scale errors in broker fill prices using market data.

    Some broker paper fills have been observed at 10x/100x market price.
    If dividing by 10 or 100 places the fill back near the day's market range,
    apply that correction.
    """
    if price <= 0 or not fill_time:
        return price, None

    day = fill_time[:10]
    bars = market_cache.get(symbol)
    if bars is None:
        bars = fetch_yahoo_daily_bars(symbol)
        market_cache[symbol] = bars
    market_bar = bars.get(day) if bars else None
    if not market_bar:
        return price, None

    low, high, close = market_bar
    if low <= price <= high:
        return price, None

    for factor in (10, 100):
        candidate = price / factor
        # Allow a small cushion around the daily range to tolerate minute-level fills.
        if (low * 0.97) <= candidate <= (high * 1.03):
            return round(candidate, 4), factor
        if close > 0 and abs(candidate - close) / close <= 0.08:
            return round(candidate, 4), factor

    return price, None


def load_env(env_file: Path):
    """Load environment variables from .env file."""
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()


def load_existing_tracking_metadata(state_file: Path) -> dict[str, Any]:
    """Load reusable tracking metadata from current pnl_state.json if present."""
    if not state_file.exists():
        return {}
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if not isinstance(data, dict):
        return {}

    return {
        'created_at': data.get('created_at'),
        'baseline_date': data.get('baseline_date'),
        'baseline_equity': data.get('baseline_equity'),
        'tracking_label': data.get('tracking_label'),
        'performance_scope': data.get('performance_scope'),
        'archived_from_account_id': data.get('archived_from_account_id'),
        'archive_path': data.get('archive_path'),
        'migration_note_path': data.get('migration_note_path'),
        # Preserve chart history — do NOT reset on rebuild
        'daily_snapshots': data.get('daily_snapshots', []),
        'strategy_daily_snapshots': data.get('strategy_daily_snapshots', []),
        'peak_equity': data.get('peak_equity'),
        'max_drawdown_pct': data.get('max_drawdown_pct'),
    }


def validate_rebuild_risk_history(metadata: dict[str, Any]) -> tuple[float, float]:
    """Preserve known risk fields; never manufacture zero DD from realized PnL.

    R22 (2026-10-20): date-only snapshots give consistency bounds, not a
    canonical cash-flow-adjusted/session-close curve. If saved fields conflict
    with those bounds, stop for an explicit historical repair, not auto-repair.
    """
    def number(value: Any, name: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f'risk history: missing/invalid {name}; audited metadata required')
        return float(value)

    peak = number(metadata.get('peak_equity'), 'peak_equity')
    dd = number(metadata.get('max_drawdown_pct'), 'max_drawdown_pct')
    baseline = number(metadata.get('baseline_equity'), 'baseline_equity')
    if peak <= 0 or baseline <= 0 or not 0 <= dd <= 1:
        raise ValueError('risk history: invalid peak, baseline or DD range')
    try:
        baseline_day = date.fromisoformat(metadata['baseline_date'])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('risk history: baseline_date is unknown') from exc
    snapshots = metadata.get('daily_snapshots')
    if not isinstance(snapshots, list):
        raise ValueError('risk history: daily_snapshots must be a list')
    curve = []
    for index, row in enumerate(snapshots):
        if not isinstance(row, dict):
            raise ValueError('risk history: malformed snapshot')
        try:
            day = date.fromisoformat(row['date'])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('risk history: snapshot date is unknown') from exc
        equity = number(row.get('equity'), 'snapshot equity')
        if day < baseline_day or equity <= 0:
            raise ValueError('risk history: snapshot is outside epoch or has invalid equity')
        curve.append((day, index, equity))
    observed_peak, observed_dd = baseline, 0.
    for _, _, equity in sorted(curve):
        observed_peak = max(observed_peak, equity)
        observed_dd = max(observed_dd, 1 - equity / observed_peak)
    # Stored DD is rounded to four decimal places by PnLTracker.
    if peak + .01 < observed_peak or dd + .000050000001 < observed_dd:
        raise ValueError('risk history: saved peak/DD contradict retained snapshots; '
                         'resolve valuation history before rebuilding')
    return peak, dd


# AUDIT FIX (2026-08-23, provenance-loss incident -- see docs/equity_bridge_
# root_cause_20260823/INCIDENT_rebuild_lost_attribution.md): fields that
# identify WHICH strategy decision produced a trade, distinct from
# exit_reason (why it closed) and entry_signal_strength (a feature value).
# Before this fix, load_existing_attribution()/apply_attribution() only
# preserved exit_reason + entry_signal_strength + quarantined_trades across
# a rebuild; every one of these provenance fields was silently overwritten
# with rebuild's 'broker_reconstructed' placeholder on every rebuild run,
# even for trades that were originally submitted by PaperExecutor with a
# real decision_id. Confirmed live: a rebuild on 2026-08-23 turned this
# account's 49 attributable (real-strategy-origin) closed trades into 0
# attributable trades, caught only because tests/unit/
# test_r8v2_ml_readiness.py's real-data sanity assertion failed -- restored
# from the pre-rebuild backup before any further changes were made.
PROVENANCE_FIELDS = (
    'strategy_id',
    'original_strategy_id',
    'strategy_version_id',
    'decision_id',
    'run_id',
    'experiment_id',
    'config_hash',
    'prompt_version',
)


def _aware_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed if parsed.utcoffset() is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def _decision_precedes_entry(generated_at: Any, entry_time: Any) -> bool:
    decision_time, entry = _aware_time(generated_at), _aware_time(entry_time)
    return decision_time is not None and entry is not None and decision_time <= entry


def _load_entry_provenance(trades: list[dict], decisions_dir: Path) -> tuple[dict, dict]:
    """Use same-buy identity plus unique, matching, pre-entry decision evidence.

    This is a conservative preservation check, not proof of original execution
    causality or a substitute for a full fill/event replay. Conflicting or already
    contaminated source rows must not be propagated by last-write-wins.
    """
    decisions: dict[str, list[dict]] = defaultdict(list)
    diagnostics = {'real_origin_source_rows': 0, 'rejected_source_rows': 0,
                   'ambiguous_entry_keys': 0, 'withheld_tainted_entry_keys': 0,
                   'unreadable_decision_files': 0}
    for path in sorted(decisions_dir.glob('*.json')):
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(record, dict) or not isinstance(record.get('decision_id'), str):
                raise ValueError('invalid decision record')
            decisions[record['decision_id']].append(record)
        except (OSError, ValueError):
            diagnostics['unreadable_decision_files'] += 1
    result, rejected, conflicts = {}, set(), set()
    for trade in trades:
        origin = trade.get('original_strategy_id') or trade.get('strategy_id') or ''
        if not isinstance(origin, str) or not origin or origin in UNTRACKED_ORIGIN_STRATEGY_IDS:
            continue
        diagnostics['real_origin_source_rows'] += 1
        key = (trade.get('symbol'), trade.get('broker_order_id'))
        if not all(isinstance(x, str) and x.strip() for x in key):
            diagnostics['rejected_source_rows'] += 1
            continue
        decision_id = trade.get('decision_id')
        records = decisions.get(decision_id, []) if isinstance(decision_id, str) else []
        record = records[0] if len(records) == 1 else {}
        valid = (record.get('symbol') == key[0] and record.get('action') == 'buy'
                 and origin in (record.get('strategy_id'), record.get('strategy_version_id'))
                 and _decision_precedes_entry(record.get('generated_at'), trade.get('entry_time')))
        for field in ('strategy_version_id', 'run_id', 'experiment_id', 'config_hash', 'prompt_version'):
            if trade.get(field) is not None and trade[field] != record.get(field):
                valid = False
        if not valid:
            diagnostics['rejected_source_rows'] += 1
            rejected.add(key)
            continue
        candidate = {'fields': {f: trade[f] for f in PROVENANCE_FIELDS if trade.get(f) is not None},
                     'decision_generated_at': record['generated_at']}
        if key in result and result[key] != candidate:
            conflicts.add(key)
        else:
            result[key] = candidate
    diagnostics['withheld_tainted_entry_keys'] = len(rejected & result.keys())
    for key in rejected | conflicts:
        result.pop(key, None)
    diagnostics['ambiguous_entry_keys'] = len(conflicts)
    return result, diagnostics


def load_existing_attribution(state_file: Path, *, decisions_dir: Path | None = None) -> dict[str, Any]:
    """Extract exit_reason attribution and quarantined_trades from current pnl_state.

    Returns a dict with:
      'by_exit_order_id'  : exit_broker_order_id -> exit_reason   (highest priority)
      'by_key'            : (symbol, exit_time[:19], pnl_int) -> exit_reason  (fallback)
      'quarantined_trades': list of quarantined trade dicts
      'provenance_by_entry_key' : (symbol, buy order ID) -> validated entry evidence
      'exit_strategy_by_pair'  : (symbol, buy order ID, sell order ID) -> exit strategy
      'provenance_diagnostics' : counts of rejected/ambiguous source evidence

    Only non-broker_fill reasons are indexed (broker_fill is the rebuild default)
    for exit_reason. Entry provenance is independent of exit attribution and may
    be preserved for open or closed trades. R22: never infer entry origin from a
    shared sell or approximate PnL key. Missing/conflicting evidence stays unknown.
    """
    empty = {
        'by_exit_order_id': {}, 'by_key': {}, 'quarantined_trades': [],
        'provenance_by_entry_key': {}, 'exit_strategy_by_pair': {},
        'provenance_diagnostics': {},
    }
    if not state_file.exists():
        return empty
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        return empty

    if not isinstance(data, dict) or not isinstance(data.get('trades', []), list):
        return empty
    trades = [t for t in data.get('trades', []) if isinstance(t, dict)]
    provenance, diagnostics = _load_entry_provenance(
        trades, decisions_dir if decisions_dir is not None else state_file.parent.parent / 'decisions')

    by_exit_order_id: dict[str, str] = {}
    by_key: dict[tuple, str] = {}
    collisions: set = set()
    exit_strategy_by_pair, exit_strategy_conflicts = {}, set()
    # entry_signal_strength: keyed by broker_order_id (buy order)
    ess_by_order_id: dict[str, float] = {}

    for trade in trades:
        # entry_signal_strength: preserve for both open and closed trades
        ess = trade.get('entry_signal_strength')
        bid = trade.get('broker_order_id', '')
        if ess is not None and bid:
            try:
                ess_by_order_id[bid] = float(ess)
            except (TypeError, ValueError):
                pass

        if trade.get('status') == 'open':
            continue

        # Preserve exit metadata separately, only on the identical order pair.
        pair = (trade.get('symbol'), bid, trade.get('exit_broker_order_id'))
        exit_strategy = trade.get('exit_strategy_id')
        if all(pair) and exit_strategy is not None:
            if pair in exit_strategy_by_pair and exit_strategy_by_pair[pair] != exit_strategy:
                exit_strategy_conflicts.add(pair)
            else:
                exit_strategy_by_pair[pair] = exit_strategy

        reason = trade.get('exit_reason', '')
        if not reason or reason == 'broker_fill':
            continue

        # Primary: exit_broker_order_id (sell order id)
        eid = trade.get('exit_broker_order_id', '')
        if eid:
            by_exit_order_id[eid] = reason

        # Secondary: (symbol, exit_time[:19], pnl rounded to int)
        sym = trade.get('symbol', '')
        et = str(trade.get('exit_time', ''))[:19]
        pnl_i = int(round(float(trade.get('pnl', 0) or 0)))
        key = (sym, et, pnl_i)
        if key in by_key and by_key[key] != reason:
            collisions.add(key)   # ambiguous; skip
        else:
            by_key[key] = reason

    # Remove ambiguous keys
    for k in collisions:
        by_key.pop(k, None)
    for pair in exit_strategy_conflicts:
        exit_strategy_by_pair.pop(pair, None)

    # Also load ESS from trade_events.jsonl (fallback for trades where pnl_state had None)
    events_file = state_file.parent / "trade_events.jsonl"
    ess_by_order_id = _merge_ess_from_trade_events(events_file, ess_by_order_id)

    return {
        'by_exit_order_id': by_exit_order_id,
        'by_key': by_key,
        'quarantined_trades': data.get('quarantined_trades', []),
        'ess_by_order_id': ess_by_order_id,
        'provenance_by_entry_key': provenance,
        'exit_strategy_by_pair': exit_strategy_by_pair,
        'provenance_diagnostics': diagnostics,
    }


def _merge_ess_from_trade_events(
    events_file: Path,
    existing: dict[str, float],
) -> dict[str, float]:
    """Read trade_opened events from trade_events.jsonl and merge signal_strength.

    Only fills entries that are missing from ``existing`` (pnl_state takes priority).
    Returns a new dict (does not mutate ``existing``).
    Added 2026-07-28: makes entry_signal_strength durable across rebuilds.
    """
    result = dict(existing)
    if not events_file.exists():
        return result
    try:
        with events_file.open(encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    ev = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if ev.get("event_type") != "trade_opened":
                    continue
                bid = ev.get("broker_order_id", "")
                if not bid:
                    continue
                ss = ev.get("payload", {}).get("signal_strength")
                if ss is None:
                    continue
                if bid not in result:  # pnl_state wins if already present
                    try:
                        result[bid] = float(ss)
                    except (TypeError, ValueError):
                        pass
    except Exception:
        pass
    return result


def apply_attribution(pnl_state: dict, attribution: dict[str, Any]) -> dict[str, int]:
    """Merge saved attribution back onto freshly rebuilt trades.

    Mutates pnl_state['trades'] in-place and sets pnl_state['quarantined_trades'].
    Returns stats dict: {'by_exit_order': N, 'by_key': N, 'kept_broker_fill': N,
    'ess_restored': N, 'provenance_restored': N, 'provenance_unresolved': N}.
    Added 2026-07-17 (exit_reason/quarantine); extended 2026-08-23 (provenance --
    see PROVENANCE_FIELDS / load_existing_attribution()'s docstring for the
    incident this closes: a rebuild previously overwrote strategy_id/
    original_strategy_id/decision_id/etc. on every trade unconditionally,
    silently erasing real strategy-decision provenance for trades that were
    NOT actually rebuild-synthesized).
    """
    by_exit_order_id = attribution.get('by_exit_order_id', {})
    by_key = attribution.get('by_key', {})
    quarantined = attribution.get('quarantined_trades', [])
    provenance_by_entry_key = attribution.get('provenance_by_entry_key', {})
    exit_strategy_by_pair = attribution.get('exit_strategy_by_pair', {})

    ess_by_order_id = attribution.get('ess_by_order_id', {})
    stats = {
        'by_exit_order': 0, 'by_key': 0, 'kept_broker_fill': 0,
        'ess_restored': 0, 'provenance_restored': 0, 'provenance_unresolved': 0,
    }

    for trade in pnl_state.get('trades', []):
        # Restore entry_signal_strength for all trades (open + closed)
        # keyed by broker_order_id (buy order id)
        bid = trade.get('broker_order_id', '')
        if bid and bid in ess_by_order_id and trade.get('entry_signal_strength') is None:
            trade['entry_signal_strength'] = ess_by_order_id[bid]
            stats['ess_restored'] += 1

        # Source and destination must both pass chronology. A FIFO rebuild can
        # change lot boundaries, so validating only the old entry is insufficient.
        entry_key = (trade.get('symbol'), bid)
        evidence = provenance_by_entry_key.get(entry_key)
        if evidence and _decision_precedes_entry(evidence.get('decision_generated_at'), trade.get('entry_time')):
            for field, value in evidence['fields'].items():
                if field in PROVENANCE_FIELDS:
                    trade[field] = value
            stats['provenance_restored'] += 1
        else:
            stats['provenance_unresolved'] += 1

        if trade.get('status') == 'open':
            continue
        pair = (*entry_key, trade.get('exit_broker_order_id'))
        if pair in exit_strategy_by_pair:
            trade['exit_strategy_id'] = exit_strategy_by_pair[pair]

        if trade.get('exit_reason') != 'broker_fill':
            continue

        # Try primary key: exit_broker_order_id
        eid = trade.get('exit_broker_order_id', '')
        if eid and eid in by_exit_order_id:
            trade['exit_reason'] = by_exit_order_id[eid]
            stats['by_exit_order'] += 1
            continue

        # Try secondary key: (symbol, exit_time[:19], pnl_int)
        sym = trade.get('symbol', '')
        et = str(trade.get('exit_time', ''))[:19]
        pnl_i = int(round(float(trade.get('pnl', 0) or 0)))
        key = (sym, et, pnl_i)
        if key in by_key:
            trade['exit_reason'] = by_key[key]
            stats['by_key'] += 1
            continue

        stats['kept_broker_fill'] += 1

    pnl_state['quarantined_trades'] = quarantined
    return stats


# ---------------------------------------------------------------------------
# R1-v2 / H1: Quarantine tombstone – prevent rebuild from re-creating quarantined trades
# as closed trades, which would cause closed/quarantine overlap.
# Added 2026-07-23
# ---------------------------------------------------------------------------

QuarantineTombstoneKey = tuple  # (entry_broker_order_id, exit_broker_order_id)


def extract_quarantine_tombstones(
    quarantined_trades: list[dict[str, Any]],
) -> frozenset:
    """Build a frozenset of tombstone keys from the existing quarantined trades.

    A tombstone key is (entry_broker_order_id, exit_broker_order_id).  Only trades
    with both fields present are included.  Rebuild will filter out any newly
    generated closed trade whose key matches a tombstone.

    Args:
        quarantined_trades: List of quarantined trade dicts from pnl_state.

    Returns:
        frozenset of (entry_order_id, exit_order_id) pairs.
    """
    tombstones: set = set()
    for qt in quarantined_trades:
        entry_oid = (qt.get('broker_order_id') or '').strip()
        exit_oid = (qt.get('exit_broker_order_id') or '').strip()
        if entry_oid and exit_oid:
            tombstones.add((entry_oid, exit_oid))
    return frozenset(tombstones)


def apply_asset_class_from_registry(
    pnl_state: dict[str, Any],
    registry_path: Path | None = None,
) -> int:
    """Backfill asset_class on all trades (open + closed) from symbol_registry.yaml.

    Called automatically after every rebuild so that asset_class is never wiped.
    Root cause fix (2026-07-28): --preserve-attribution only saved exit_reason /
    quarantined_trades; asset_class was silently lost on each rebuild.

    Returns the number of trades updated.
    """
    path = registry_path or _REGISTRY_PATH
    try:
        registry = read_symbol_registry(path)
    except Exception:
        registry = {}

    updated = 0
    for trade in pnl_state.get("trades", []):
        sym = trade.get("symbol", "")
        current_ac = (trade.get("asset_class") or "").lower()
        if current_ac in ("stock", "etf"):
            continue  # already valid, preserve
        reg_info = registry.get(sym) or {}
        new_ac = (reg_info.get("asset_class") or "").lower()
        if new_ac in ("stock", "etf"):
            trade["asset_class"] = new_ac
            updated += 1
        else:
            trade["asset_class"] = "unknown"
    return updated


def apply_tombstone_filter(
    pnl_state: dict[str, Any],
    quarantined_trades: list[dict[str, Any]],
) -> int:
    """Remove trades from pnl_state['trades'] whose order-ID pair matches a quarantined trade.

    Ensures that rebuild is idempotent: quarantined trades are never re-added to
    the closed trade list on subsequent rebuilds from the same broker fills.

    The pnl_state's quarantined_trades list is NOT modified here; that is done
    by apply_attribution().  This function only filters state['trades'].

    Args:
        pnl_state: Freshly rebuilt pnl_state dict (mutated in-place).
        quarantined_trades: Saved quarantined trades from the previous state.

    Returns:
        Number of trades removed (tombstone hits).
    """
    tombstones = extract_quarantine_tombstones(quarantined_trades)
    if not tombstones:
        return 0

    original = pnl_state.get('trades', [])
    kept: list[dict[str, Any]] = []
    removed = 0

    for trade in original:
        entry_oid = (trade.get('broker_order_id') or '').strip()
        exit_oid = (trade.get('exit_broker_order_id') or '').strip()
        key = (entry_oid, exit_oid)
        if key in tombstones:
            removed += 1
        else:
            kept.append(trade)

    if removed:
        pnl_state['trades'] = kept
        # Recompute counts to keep state consistent
        closed = [t for t in kept if t.get('status') == 'closed']
        pnl_state['total_trades'] = len(kept)
        pnl_state['cumulative_realized_pnl'] = round(sum(t.get('pnl') or 0 for t in closed), 2)
        # BUG FIX (2026-08-24, found by scripts/verify_rebuild_integrity.py's
        # pnl-consistency invariant check on a 2026-08-24 rebuild): this
        # function already recomputed total_trades/cumulative_realized_pnl
        # after removing tombstoned trades, but NOT winning_trades/
        # losing_trades -- those were left at whatever calculate_summary()
        # computed BEFORE the tombstone filter ran (rebuild_pnl_state()
        # calls calculate_summary() first, then main() calls this function
        # afterward). Confirmed live: a 5-trade tombstone filter left
        # winning_trades=164/losing_trades=176 (summing to 341, the PRE-
        # filter closed count) while the actual post-filter closed list
        # (336 trades) had only 163 wins / 172 losses / 1 zero-pnl trade.
        # This did not fail check_pnl_consistency() (which only checks the
        # pnl SUM, not win/loss counts), so it went undetected until a
        # separate later step (quarantine migration) additionally shifted
        # counts and made the drift visible via a different symptom.
        pnl_state['winning_trades'] = sum(1 for t in closed if (t.get('pnl') or 0) > 0)
        pnl_state['losing_trades'] = sum(1 for t in closed if (t.get('pnl') or 0) < 0)

    return removed


def compute_rebuild_fingerprint(pnl_state: dict[str, Any]) -> dict[str, Any]:
    """Compute a content fingerprint of a pnl_state for idempotency checks.

    Returns a dict with closed_count, open_count, quarantine_count, pnl_sum, and a
    sorted list of (trade_id, pnl) pairs so two runs can be diff'd.

    Args:
        pnl_state: A rebuilt pnl_state dict.

    Returns:
        Dict with fingerprint fields.
    """
    trades = pnl_state.get('trades', [])
    closed = sorted(
        [(t.get('trade_id', ''), round(float(t.get('pnl') or 0), 2))
         for t in trades if t.get('status') == 'closed'],
        key=lambda x: x[0],
    )
    open_t = [t for t in trades if t.get('status') == 'open']
    quarantined = pnl_state.get('quarantined_trades', [])
    return {
        'closed_count': len(closed),
        'open_count': len(open_t),
        'quarantine_count': len(quarantined),
        'pnl_sum': round(sum(p for _, p in closed), 2),
        'closed_trades': closed,  # for diff
    }


def resolve_tracking_metadata(args: argparse.Namespace, existing: dict[str, Any], now_iso: str) -> dict[str, Any]:
    """Resolve tracking metadata for rebuilt pnl_state.

    Priority:
    1. Explicit CLI args
    2. Existing pnl_state metadata
    3. Safe defaults derived from current rebuild timestamp
    """
    baseline_date = args.baseline_date or existing.get('baseline_date') or now_iso[:10]
    baseline_equity = (
        args.baseline_equity
        if args.baseline_equity is not None
        else existing.get('baseline_equity')
        if existing.get('baseline_equity') is not None
        else 1000000.0
    )
    created_at = args.created_at or existing.get('created_at') or now_iso
    tracking_label = (
        args.tracking_label
        or existing.get('tracking_label')
        or f'alpaca_account_epoch_{baseline_date}'
    )
    performance_scope = (
        args.performance_scope
        or existing.get('performance_scope')
        or 'current_account_since_baseline'
    )
    resolved = {
        'created_at': created_at,
        'baseline_date': baseline_date,
        'baseline_equity': float(baseline_equity),
        'tracking_label': tracking_label,
        'performance_scope': performance_scope,
        'archived_from_account_id': existing.get('archived_from_account_id'),
        'archive_path': args.archive_path or existing.get('archive_path'),
        'migration_note_path': args.migration_note_path or existing.get('migration_note_path'),
    }
    # R22: the old resolver dropped histories loaded immediately above it.
    # Never silently carry old risk fields into a different capital/time epoch.
    if 'peak_equity' in existing or 'max_drawdown_pct' in existing:
        for key in ('baseline_date', 'baseline_equity', 'performance_scope'):
            if existing.get(key) is not None and resolved[key] != existing[key]:
                raise ValueError(f'risk history: changing {key} requires a separate epoch migration')
    for key in ('peak_equity', 'max_drawdown_pct', 'daily_snapshots', 'strategy_daily_snapshots'):
        if key in existing:
            resolved[key] = existing[key]
    return resolved


def fetch_all_filled_orders(broker: BrokerClient) -> list:
    """Fetch all filled orders (including partial fills on since-cancelled
    orders) from broker.

    AUDIT FIX (2026-08-23, pagination): previously called broker.fetch_
    orders(status='all', limit=500), a SINGLE un-paginated call. Alpaca's
    v2/orders endpoint returns at most `limit` orders with no pagination
    applied by a single call -- once the account has more than 500 total
    orders, this silently returned only the most recent 500 (confirmed
    live: missing ~9 days / ~200 orders of history predating 2026-05-21,
    despite genuine order history back to 2026-05-12). Because match_buy_
    sell_orders()'s FIFO matcher below has no way to detect a missing buy
    leg, this silent truncation was ONE of two root causes traced for
    ~$150K+ of PnL ending up in quarantined_trades with impossible
    entry>exit chronology and/or multiple buy legs matched to the same
    sell fill (see broker_client.py's fetch_orders()/fetch_all_orders()
    docstrings for the full trace). Fixed to use fetch_all_orders(), which
    paginates ascending until the complete history is retrieved.

    AUDIT FIX (2026-08-23, partial-fill status filter -- found and fixed
    the SAME evening as the pagination fix above, while investigating why
    5 impossible-chronology trades still remained even after re-running
    the matcher with the pagination fix alone): this function used to
    filter to `status == 'filled'` ONLY, silently dropping any order whose
    status is 'canceled' (or 'expired') but which nonetheless has a
    nonzero filled_qty -- i.e. an order that was PARTIALLY filled before
    being cancelled/expired. Confirmed live: 4 such orders exist in this
    account's history (ADBE/MSFT/CDNS/AVGO, all dated 2026-06-01,
    totaling 402 shares of real, PnL-relevant fills), and every single one
    of them was the MISSING buy leg for a sell that appeared later in the
    filled-only order list -- e.g. ADBE's 2026-06-03 sell of 101 shares
    had NO buy leg in the filtered list at all (its true buy, 2026-06-01,
    was status='canceled' with filled_qty=101), so match_buy_sell_orders()
    incorrectly matched that sell against a LATER, unrelated buy fill
    (2026-07-28), producing a trade with entry_time AFTER exit_time.
    Verified fix: re-running the matcher with orders filtered by
    `filled_qty > 0` instead of `status == 'filled'` reduced impossible-
    chronology trades from 17 to 5 (the remaining 5, all CRWD/KLAC, trace
    to a SEPARATE, already-known limitation -- apply_split_adjustment()
    below only rescales entry PRICE across a stock-split ex_date, not
    entry QTY, so a pre-split buy fill's share count is not comparable to
    a post-split sell fill's share count for FIFO matching purposes; not
    fixed in this change, tracked separately).
    """
    print("Fetching filled orders from broker (paginated, full history)...")
    orders_env = broker.fetch_all_orders(status='all')
    payload = orders_env.payload if hasattr(orders_env, 'payload') else orders_env
    orders = payload.get('orders', []) if isinstance(payload, dict) else payload
    if isinstance(payload, dict) and payload.get('truncated'):
        raise ValueError("truncated broker order history; cannot reconstruct complete inventory")
    if isinstance(payload, dict):
        print(f"  Fetched {len(orders)} total orders across {payload.get('page_count')} page(s)")

    filled_orders = [o for o in orders if float(o.get('filled_qty') or 0) > 0]
    partial_non_filled = [o for o in filled_orders if o.get('status') != 'filled']
    print(f"  Found {len(filled_orders)} orders with a nonzero fill "
          f"({len(partial_non_filled)} of which are partial fills on a "
          f"since-cancelled/expired order, not status=='filled')")
    if partial_non_filled:
        for o in sorted(partial_non_filled, key=lambda o: o.get('created_at', '')):
            print(
                f"    ℹ️  partial-fill-before-cancel: {o.get('symbol')} "
                f"{o.get('side')} filled_qty={o.get('filled_qty')} of qty={o.get('qty')} "
                f"at ${o.get('filled_avg_price')} (status={o.get('status')})"
            )

    return filled_orders


def fetch_broker_open_positions(broker: BrokerClient) -> dict[str, dict]:
    """A failed/incomplete fetch is not evidence of an empty portfolio."""
    try:
        response = broker.fetch_positions()
        positions = response.payload if hasattr(response, "payload") else response
        if not isinstance(positions, list):
            raise ValueError("expected position list")
        result = {}
        for pos in positions:
            symbol = pos.get("symbol")
            if not symbol or symbol in result:
                raise ValueError("missing/duplicate position identity")
            result[symbol] = {
                "qty": whole_quantity(pos.get("qty"), "broker position quantity"),
                "avg_entry_price": float(decimal_value(pos.get("avg_entry_price"), "broker position price")),
                "asset_id": pos.get("asset_id"),
            }
        return result
    except Exception as exc:
        raise ValueError("broker position evidence unavailable or unsupported") from exc


def load_corporate_actions(project_root: Path) -> list[dict]:
    """Load corporate actions registry from data/corporate_actions.json."""
    ca_path = project_root / "data" / "corporate_actions.json"
    try:
        with open(ca_path) as f:
            data = json.load(f)
        return data.get("actions", [])
    except Exception:
        return []


def apply_split_adjustment(
    symbol: str,
    entry_price: float,
    entry_time: str,
    exit_time: str,
    corporate_actions: list[dict],
) -> tuple[float, float | None]:
    """Adjust entry price for splits that occurred between buy and sell.

    If a forward split ex_date falls between the buy fill date and the sell
    fill date, the recorded buy price is pre-split while the sell price is
    post-split.  Dividing the entry price by the split ratio makes both
    prices comparable on a post-split basis.

    Returns (adjusted_entry_price, split_ratio_applied | None).
    """
    for action in corporate_actions:
        if action.get("symbol") != symbol:
            continue
        if action.get("type") != "split" or action.get("direction") != "forward":
            continue
        ex_date = action.get("ex_date", "")[:10]  # YYYY-MM-DD
        if not ex_date:
            continue
        ratio = float(action.get("ratio", 1))
        if ratio <= 1:
            continue
        buy_date = entry_time[:10]
        sell_date = exit_time[:10]
        # Buy is pre-split, sell is post-split
        if buy_date < ex_date <= sell_date:
            adjusted = round(entry_price / ratio, 4)
            return adjusted, ratio
    return entry_price, None


def match_buy_sell_orders(
    filled_orders: list,
    corporate_actions: list[dict] | None = None,
    *,
    split_activities: list[dict] | None = None,
    split_date_overrides: dict[str, str] | None = None,
) -> tuple[list, list]:
    """Offline chronological order-VWAP FIFO; never infer economics from market bars.

    Split activities must prove removed/added inventory. An explicit registry
    date mapping is needed if broker effective date differs from the registry.
    This accounting replay is not point-in-time strategy evidence.
    """
    from stock_swing.tracking.execution_fifo import match_order_completion_fifo
    return match_order_completion_fifo(
        filled_orders, corporate_actions, split_activities=split_activities,
        split_date_overrides=split_date_overrides,
    )


def reconcile_open_positions(
    open_from_fills: list,
    broker_positions: dict[str, dict],
    trade_num_offset: int,
) -> list:
    """Verify inventory; do not overwrite missing history with position averages.

    Order history and positions are not an atomic snapshot. A mismatch requires
    a new consistent observation, not dropping a lot or inventing a new basis.
    trade_num_offset remains accepted for caller compatibility.
    """
    expected = defaultdict(int)
    for lot in open_from_fills:
        expected[lot["symbol"]] += whole_quantity(lot["qty"], "open lot quantity")
    actual = {symbol: whole_quantity(pos.get("qty"), "broker position quantity")
              for symbol, pos in broker_positions.items()}
    if dict(expected) != actual:
        raise ValueError("open inventory differs between order history and broker positions")
    return list(open_from_fills)


def calculate_summary(trades: list, open_positions: list) -> dict:
    """Calculate summary statistics."""
    closed_trades = [t for t in trades if t['status'] == 'closed']
    wins = [t for t in closed_trades if t['pnl'] > 0]
    losses = [t for t in closed_trades if t['pnl'] < 0]
    
    total_pnl = sum(t['pnl'] for t in closed_trades)
    win_rate = len(wins) / len(closed_trades) if closed_trades else 0.0
    
    return {
        'total_trades': len(closed_trades) + len(open_positions),
        'closed_trades': len(closed_trades),
        'open_trades': len(open_positions),
        'winning_trades': len(wins),
        'losing_trades': len(losses),
        'win_rate': round(win_rate, 4),
        'cumulative_realized_pnl': round(total_pnl, 2),
        'avg_pnl_per_trade': round(total_pnl / len(closed_trades), 2) if closed_trades else 0.0,
    }


def rebuild_pnl_state(
    broker: BrokerClient,
    tracking_metadata: dict[str, Any] | None = None,
    *,
    split_activities: list[dict] | None = None,
    split_date_overrides: dict[str, str] | None = None,
) -> dict:
    """Rebuild pnl_state.json from broker order history and current positions."""
    tracking_metadata = tracking_metadata or {}
    peak_equity, max_drawdown_pct = validate_rebuild_risk_history(tracking_metadata)
    filled_orders = fetch_all_filled_orders(broker)
    corporate_actions = load_corporate_actions(PROJECT_ROOT)
    closed_trades, open_from_fills = match_buy_sell_orders(
        filled_orders, corporate_actions, split_activities=split_activities,
        split_date_overrides=split_date_overrides,
    )
    
    # Fetch current broker positions and reconcile
    broker_positions = fetch_broker_open_positions(broker)
    trade_num_offset = len(closed_trades) + len(open_from_fills)
    open_positions = reconcile_open_positions(open_from_fills, broker_positions, trade_num_offset)

    all_trades = closed_trades + open_positions
    summary = calculate_summary(closed_trades, open_positions)

    now = datetime.now(timezone.utc).isoformat()
    tracking_metadata = tracking_metadata or {}
    baseline_equity = float(tracking_metadata.get('baseline_equity') or 1000000.0)

    # Get broker account info
    try:
        account_resp = broker.fetch_account()
        account = account_resp.payload if hasattr(account_resp, 'payload') else account_resp
        broker_account_id = account.get('account_number') or account.get('id')
    except Exception:
        broker_account_id = None

    pnl_state = {
        'created_at': tracking_metadata.get('created_at') or now,
        'last_updated': now,
        'trades': all_trades,
        'daily_snapshots': tracking_metadata.get('daily_snapshots', []),
        'strategy_daily_snapshots': tracking_metadata.get('strategy_daily_snapshots', []),
        'cumulative_realized_pnl': summary['cumulative_realized_pnl'],
        'total_trades': len(all_trades),
        'winning_trades': summary['winning_trades'],
        'losing_trades': summary['losing_trades'],
        'peak_equity': peak_equity,
        'max_drawdown_pct': max_drawdown_pct,
        'broker_account_id': broker_account_id,
        'baseline_date': tracking_metadata.get('baseline_date') or now[:10],
        'baseline_equity': baseline_equity,
        'tracking_label': tracking_metadata.get('tracking_label') or f'broker_rebuilt_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}',
        'performance_scope': tracking_metadata.get('performance_scope') or 'current_account_since_baseline',
        'archived_from_account_id': tracking_metadata.get('archived_from_account_id'),
        'archive_path': tracking_metadata.get('archive_path'),
        'migration_note_path': tracking_metadata.get('migration_note_path'),
    }

    return pnl_state


from stock_swing.tracking.compatibility import legacy_entrypoint, legacy_maintenance, tracking_root

@legacy_entrypoint(lambda *a, **k: globals().get('project_root', globals().get('PROJECT_ROOT', Path(__file__).resolve().parents[1])))
def main():
    parser = argparse.ArgumentParser(description="Rebuild pnl_state.json from broker order history")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be changed without writing")
    parser.add_argument("--backup", action="store_true", help="Create backup of existing pnl_state.json")
    # R0-v2: --preserve-attribution is now DEFAULT True.
    # To skip (destructive, will lose all attribution): use --no-preserve-attribution --force
    parser.add_argument(
        "--preserve-attribution",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Restore exit_reason / quarantined_trades from the current pnl_state after rebuild. "
            "DEFAULT: True. Use --no-preserve-attribution --force to opt out (DESTRUCTIVE). "
            "History: 07-14 two rebuilds without this flag caused attribution loss (76 trades). "
            "See: MEMORY.md / docs/daily_logs/2026-07-21.md for context."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Required when using --no-preserve-attribution to acknowledge data loss.",
    )
    parser.add_argument("--baseline-equity", type=float, default=None, help="Override baseline equity")
    parser.add_argument("--baseline-date", type=str, default=None, help="Override baseline date (YYYY-MM-DD)")
    parser.add_argument("--created-at", type=str, default=None, help="Override tracking created_at (ISO-8601)")
    parser.add_argument("--tracking-label", type=str, default=None, help="Override tracking label")
    parser.add_argument("--performance-scope", type=str, default=None, help="Override performance scope")
    parser.add_argument("--archive-path", type=str, default=None, help="Override archive path metadata")
    parser.add_argument("--migration-note-path", type=str, default=None, help="Override migration note path metadata")
    parser.add_argument("--split-evidence-file", help="Local JSON: activities + optional registry_date_overrides; post-hoc accounting only")
    args = parser.parse_args()
    
    # Local frozen evidence only; no activity fetch or automatic registry edits.
    split_evidence = {}
    if args.split_evidence_file:
        try:
            split_evidence = json.loads(Path(args.split_evidence_file).read_text(encoding="utf-8"))
            if not isinstance(split_evidence, dict) or not isinstance(split_evidence.get("activities"), list):
                raise ValueError("expected object with activities list and optional registry_date_overrides")
            from stock_swing.tracking.execution_fifo import _confirmed_splits
            _confirmed_splits(split_evidence["activities"], split_evidence.get("registry_date_overrides", {}))
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            print(f"ERROR: invalid split evidence: {exc}. No broker history fetched or state written.")
            return 1

    # Load environment
    load_env(PROJECT_ROOT / '.env')
    api_key = os.environ.get('BROKER_API_KEY')
    api_secret = os.environ.get('BROKER_API_SECRET')
    
    if not api_key or not api_secret:
        print("ERROR: BROKER_API_KEY and BROKER_API_SECRET must be set", file=sys.stderr)
        return 1
    
    # Initialize broker client
    broker = BrokerClient(api_key=api_key, api_secret=api_secret, paper_mode=True)
    state_file = PROJECT_ROOT / "data" / "tracking" / "pnl_state.json"
    existing_meta = load_existing_tracking_metadata(state_file)
    try:
        resolved_meta = resolve_tracking_metadata(args, existing_meta, datetime.now(timezone.utc).isoformat())
        validate_rebuild_risk_history(resolved_meta)
    except ValueError as exc:
        print(f'ERROR: {exc}. No broker history fetched or state written.')
        return 1

    # R0-v2: Guard against --no-preserve-attribution without --force
    if not args.preserve_attribution:
        if not getattr(args, 'force', False):
            print()
            print("ERROR: --no-preserve-attribution requires --force to acknowledge data loss.")
            print("  All exit_reason and quarantined_trades will be permanently wiped.")
            print("  Re-run: python scripts/rebuild_pnl_state_from_broker.py"
                  " --no-preserve-attribution --force")
            print()
            return 1
        if state_file.exists():
            try:
                _existing = json.loads(state_file.read_text(encoding="utf-8"))
                _closed_e = [t for t in _existing.get('trades', []) if t.get('status') != 'open']
                _non_bf = sum(1 for t in _closed_e
                              if t.get('exit_reason', 'broker_fill') not in ('broker_fill', '', None))
                _q_count = len(_existing.get('quarantined_trades', []))
                print()
                print(f"\u26a0\ufe0f  DESTRUCTIVE REBUILD (--force): losing {_non_bf} attributed exits "
                      f"and {_q_count} quarantined trades.")
                print()
            except Exception:
                pass

    # Load attribution BEFORE rebuild (--preserve-attribution default True since R0-v2 2026-07-21)
    attribution: dict[str, Any] = {'by_exit_order_id': {}, 'by_key': {}, 'quarantined_trades': []}
    if args.preserve_attribution:
        attribution = load_existing_attribution(state_file)
        n_attr = len(attribution['by_exit_order_id']) + len(attribution['by_key'])
        n_q = len(attribution['quarantined_trades'])
        print(f"\u2139\ufe0f  --preserve-attribution (default): loaded {n_attr} attribution entries, "
              f"{n_q} quarantined trades from existing pnl_state.")

        # Rebuild state
    print("=" * 70)
    print("Rebuilding pnl_state.json from Broker Order History")
    print("=" * 70)
    print()
    print("Tracking metadata:")
    print(json.dumps({key: value for key, value in resolved_meta.items()
                      if key not in {'daily_snapshots', 'strategy_daily_snapshots'}},
                     indent=2, ensure_ascii=False))
    print()

    try:
        pnl_state = rebuild_pnl_state(
            broker, tracking_metadata=resolved_meta,
            split_activities=split_evidence.get("activities"),
            split_date_overrides=split_evidence.get("registry_date_overrides"),
        )
    except ValueError as exc:
        print(f"ERROR: accounting evidence unresolved: {exc}. No state written.")
        return 1

    # Merge attribution back (if --preserve-attribution)
    if args.preserve_attribution:
        # R1-v2 / H1: Apply tombstone filter BEFORE attribution merge.
        # This removes any newly-generated closed trades whose order-ID pair matches
        # a quarantined trade, preventing closed/quarantine overlap on subsequent rebuilds.
        _tombstone_hits = apply_tombstone_filter(pnl_state, attribution.get('quarantined_trades', []))
        if _tombstone_hits:
            print(f"🪦  Tombstone filter: removed {_tombstone_hits} re-generated closed trade(s) "
                  f"that matched quarantined tombstones (idempotency guard).")

        attr_stats = apply_attribution(pnl_state, attribution)
        print()
        print("✅ Attribution restored:")
        print(f"   by exit_broker_order_id : {attr_stats['by_exit_order']}")
        print(f"   by (symbol,exit_time,pnl): {attr_stats['by_key']}")
        print(f"   kept as broker_fill      : {attr_stats['kept_broker_fill']}")
        print(f"   quarantined_trades       : {len(pnl_state.get('quarantined_trades', []))}")
        print(f"   provenance_restored (strategy_id/decision_id/etc.): {attr_stats['provenance_restored']}")
        print(f"   provenance_unresolved    : {attr_stats['provenance_unresolved']}")
        print(f"   provenance source checks : {attribution.get('provenance_diagnostics', {})}")
        if _tombstone_hits:
            print(f"   tombstone_filtered       : {_tombstone_hits}")

    # Always backfill asset_class from symbol_registry.yaml after rebuild.
    # Root cause fix (2026-07-28): asset_class was silently wiped on every rebuild
    # because --preserve-attribution only saved exit_reason + quarantined_trades.
    # The daily audit and ledger_quality_gate now both check asset_class.
    _ac_updated = apply_asset_class_from_registry(pnl_state)
    print(f"\n🏷️  asset_class backfill from symbol_registry: {_ac_updated} trade(s) updated.")

    # Print summary
    print()
    print("=" * 70)
    print("Summary:")
    print("=" * 70)
    print(f"Total Trades: {pnl_state['total_trades']}")
    print(f"Closed: {len([t for t in pnl_state['trades'] if t['status'] == 'closed'])}")
    print(f"Open: {len([t for t in pnl_state['trades'] if t['status'] == 'open'])}")
    print(f"Wins: {pnl_state['winning_trades']}")
    print(f"Losses: {pnl_state['losing_trades']}")
    print(f"Win Rate: {pnl_state['winning_trades'] / (pnl_state['winning_trades'] + pnl_state['losing_trades']) * 100:.1f}%" if (pnl_state['winning_trades'] + pnl_state['losing_trades']) > 0 else "N/A")
    print(f"Cumulative Realized P&L: ${pnl_state['cumulative_realized_pnl']:+,.2f}")
    print()
    
    if args.dry_run:
        print("DRY RUN: Would write to data/tracking/pnl_state.json")
        print()
        print("Sample trades:")
        for trade in pnl_state['trades'][:10]:
            print(f"  {trade['symbol']:6} {trade['status']:6} qty={trade['qty']:>4} entry=${trade['entry_price']:>7.2f} exit={trade.get('exit_price') or 'open':>7} pnl={trade.get('pnl') or 'N/A':>10}")
        return 0
    
    # Backup if requested
    backup_file = None
    if args.backup and state_file.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = state_file.parent / f"pnl_state_backup_{timestamp}.json"
        shutil.copy2(state_file, backup_file)
        print(f"✅ Created backup: {backup_file}")
    
    # Write new state
    state_file.write_text(json.dumps(pnl_state, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ Wrote pnl_state.json: {state_file}")
    print()

    # --- Post-rebuild integrity check (auto-fix if backup was created) ---
    print("Running post-rebuild integrity check...")
    post_check_failed = False
    try:
        import subprocess
        verify_args = [sys.executable, str(PROJECT_ROOT / "scripts" / "verify_rebuild_integrity.py")]
        if backup_file and backup_file.exists():
            verify_args += ["--backup", str(backup_file), "--fix"]
        else:
            verify_args += ["--fix"]
        result = subprocess.run(verify_args, capture_output=True, text=True)
        print(result.stdout)
        if result.returncode != 0:
            # BUG FIX (2026-08-24): previously this branch only printed a
            # warning and main() still `return 0`-ed unconditionally below,
            # so a caller/cron checking this script's exit code (or a human
            # skimming only the final "Next: Restart console" line) could
            # miss that verify_rebuild_integrity.py reported UNRESOLVED
            # issues (e.g. reversed chronology) after --fix. Now surfaces
            # both a clear non-"passed" message here AND propagates a
            # non-zero exit code from this script's main().
            post_check_failed = True
            print("❌ Post-rebuild integrity check FAILED — unresolved issues remain "
                  "even after --fix (see detail above). pnl_state.json has already been "
                  "written; back it out (restore from the backup created above) or resolve "
                  "the listed issues manually before treating this rebuild as clean.")
            if result.stderr:
                print(result.stderr)
        else:
            print("✅ Post-rebuild integrity check passed.")
    except Exception as e:
        print(f"WARN: Could not run post-rebuild check: {e}")

    print("Next: Restart console to see accurate data")
    print()

    return 1 if post_check_failed else 0


if __name__ == "__main__":
    sys.exit(main())
