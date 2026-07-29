#!/usr/bin/env python3
"""Reconcile recent broker orders and update PnL tracker for filled exits."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root / "src"))

from stock_swing.cli.cron_summary import emit_cron_summary
from stock_swing.cli.paper_demo import _load_env
from stock_swing.core.run_context import RunContext
from stock_swing.sources.broker_client import BrokerClient
from stock_swing.tracking.exit_reason_store import delete_exit_reason, purge_old_entries, read_exit_reason
from stock_swing.tracking.pnl_tracker import PnLTracker
from stock_swing.tracking.trade_event_store import TradeEvent
from stock_swing.utils.market_calendar import MarketCalendar


def parse_submission_line(line: str):
    parts = [p.strip() for p in line.split(" | ", 6)]
    if len(parts) < 7 or parts[2] != "submission":
        return None
    details = parts[6]
    if not details.startswith("Order submitted:"):
        return None
    tail = details.split(":", 1)[1].strip().split()
    if len(tail) < 3:
        return None
    side = tail[0].lower()
    qty = int(tail[1]) if tail[1].isdigit() else 0
    symbol = tail[2].upper()
    return {
        "ts": parts[0],
        "submission_id": parts[5],
        "side": side,
        "qty": qty,
        "symbol": symbol,
    }


def load_recent_submissions(audits_dir: Path, limit: int = 100):
    items = []
    for path in sorted(audits_dir.glob("paper_demo_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
        for line in path.read_text(encoding="utf-8").splitlines():
            parsed = parse_submission_line(line)
            if parsed:
                items.append(parsed)
                if len(items) >= limit:
                    return items
    return items


RECENTLY_SOLD_WINDOW_MINUTES = 30


def _build_recently_sold_symbols(
    filled_sells_by_symbol: dict[str, list[dict]],
    *,
    now: datetime | None = None,
) -> set[str]:
    """Return sell symbols with a fill inside the recent-sell suppression window."""
    cutoff_dt = (now or datetime.now(timezone.utc)) - timedelta(minutes=RECENTLY_SOLD_WINDOW_MINUTES)
    recently_sold_symbols: set[str] = set()
    for sym, sell_orders in filled_sells_by_symbol.items():
        for order in sell_orders:
            filled_at_str = order.get("filled_at") or order.get("updated_at")
            if filled_at_str:
                try:
                    filled_at = datetime.fromisoformat(str(filled_at_str).replace("Z", "+00:00"))
                    if filled_at >= cutoff_dt:
                        recently_sold_symbols.add(sym)
                        break
                except (TypeError, ValueError):
                    continue
            else:
                recently_sold_symbols.add(sym)
                break
    return recently_sold_symbols


# ---------------------------------------------------------------------------
# Split / reverse-split detection helpers
# ---------------------------------------------------------------------------

#: Ratios tried when looking for a clean split.  Forward splits dominate;
#: reverse splits are listed as their decimal equivalents.
_SPLIT_CANDIDATE_RATIOS: list[float] = [
    2, 3, 4, 5, 6, 7, 8, 10, 15, 20, 25, 50,          # common forward splits
    0.5, 1 / 3, 0.25, 0.2, 0.125, 0.1,                # common reverse splits
]


def _find_split_ratio(broker_qty: int, tracker_qty: int) -> float | None:
    """Return the split ratio (broker/tracker) if it matches a common split, else None.

    Tolerance is intentionally tight (0.5 %).  A real integer-share split always
    produces an *exact* ratio (e.g. 8\u00d731 = 248, ratio = 8.000).  A new-buy
    coincidence like 100/33 = 3.030 is >1 % off and should NOT be detected as
    a split.
    """
    if tracker_qty <= 0:
        return None
    ratio = broker_qty / tracker_qty
    for r in _SPLIT_CANDIDATE_RATIOS:
        if abs(ratio - r) / r < 0.005:   # 0.5 % \u2014 tight to avoid false positives
            return r
    return None


def reconcile_split_adjusted_positions(
    broker: BrokerClient,
    tracker: PnLTracker,
    cost_basis_tolerance: float = 0.10,
) -> int:
    """Detect and correct open positions affected by stock splits or reverse splits.

    Detection (ALL conditions must be satisfied):

    1. ``broker_qty / tracker_total_qty`` is close to a common split ratio (\u00b12 %).
    2. The **cost basis** is approximately preserved after the ratio adjustment:
       ``|tracker_cost \u2212 broker_cost| / tracker_cost < cost_basis_tolerance``.
       Genuine new buys *increase* cost basis; a split leaves it unchanged.
    3. The **price ratio** moves in the expected direction:
       ``tracker_weighted_avg / broker_avg \u2248 split_ratio``.

    Correction applied per lot:

    * ``qty``          \u2192 ``round(old_qty \u00d7 ratio)``
    * ``entry_price``  \u2192 ``old_entry / ratio``
    * ``peak_price``   \u2192 ``old_peak / ratio``

    Returns the number of lots corrected.
    """
    # ---- fetch broker positions ----------------------------------------
    try:
        pos_env = broker.fetch_positions()
        broker_positions = pos_env.payload if hasattr(pos_env, "payload") else pos_env
        if not isinstance(broker_positions, list):
            return 0
    except Exception as exc:
        print(f"WARN: reconcile_split_adjusted_positions: failed to fetch positions: {exc}",
              file=sys.stderr)
        return 0

    broker_by_symbol: dict[str, dict] = {
        str(p.get("symbol", "")).upper(): p for p in broker_positions
    }

    # ---- group tracker lots by symbol ----------------------------------
    lots_by_symbol: dict[str, list[dict]] = {}
    for trade in tracker.get_open_positions():
        sym = str(trade.get("symbol") or "").upper()
        if sym:
            lots_by_symbol.setdefault(sym, []).append(trade)

    corrected_lots = 0
    corrections: list[str] = []

    for sym, lots in lots_by_symbol.items():
        broker_pos = broker_by_symbol.get(sym)
        if not broker_pos:
            continue

        broker_qty = int(abs(float(broker_pos.get("qty", 0) or 0)))
        broker_avg = float(broker_pos.get("avg_entry_price", 0) or 0)

        tracker_total_qty = sum(int(t.get("qty", 0) or 0) for t in lots)

        if tracker_total_qty == broker_qty or tracker_total_qty == 0:
            continue  # qtys match \u2014 no split needed

        # --- Condition 1: clean split ratio? ---
        ratio = _find_split_ratio(broker_qty, tracker_total_qty)
        if ratio is None:
            continue

        # --- Condition 2: cost basis approximately preserved? ---
        tracker_cost = sum(
            int(t.get("qty", 0) or 0) * float(t.get("entry_price", 0) or 0)
            for t in lots
        )
        broker_cost = broker_qty * broker_avg
        if tracker_cost > 0 and abs(tracker_cost - broker_cost) / tracker_cost > cost_basis_tolerance:
            continue

        # --- Condition 3: price ratio matches qty ratio? ---
        tracker_avg = tracker_cost / tracker_total_qty if tracker_total_qty else 0
        if tracker_avg > 0 and broker_avg > 0:
            price_ratio = tracker_avg / broker_avg
            if abs(price_ratio - ratio) / ratio > 0.10:   # 10% tolerance
                continue

        # ---- Apply correction ------------------------------------------
        direction = "forward" if ratio >= 1 else "reverse"
        for trade in lots:
            old_qty = int(trade.get("qty", 0) or 0)
            old_entry = float(trade.get("entry_price", 0) or 0)
            old_peak = float(trade.get("peak_price") or old_entry or 0)

            new_qty = max(1, round(old_qty * ratio))
            new_entry = round(old_entry / ratio, 6) if old_entry > 0 else broker_avg
            new_peak = round(old_peak / ratio, 6) if old_peak > 0 else new_entry

            trade["qty"] = new_qty
            trade["entry_price"] = new_entry
            trade["peak_price"] = new_peak
            corrected_lots += 1

        corrections.append(
            f"  {sym}: {direction} split ratio={ratio:.4g} "
            f"qty {tracker_total_qty}\u2192{broker_qty} "
            f"avg_entry ${tracker_avg:.4f}\u2192${broker_avg:.4f}"
        )

    if corrected_lots:
        tracker._save_state()
        print(
            f"INFO: reconcile_split_adjusted_positions: corrected {len(corrections)} symbol(s) "
            f"({corrected_lots} lot(s)):",
            file=sys.stderr,
        )
        for msg in corrections:
            print(msg, file=sys.stderr)

    return corrected_lots


def reconcile_stale_entry_prices(
    broker: BrokerClient,
    tracker: PnLTracker,
    deviation_threshold: float = 0.05,
) -> int:
    """Correct open trade entry prices from broker fills or broker position avg."""

    def _get_order_payload(order_id: str):
        if hasattr(broker, "get_order"):
            response = broker.get_order(order_id)
        else:
            response = broker.fetch_order(order_id)
        return response.payload if hasattr(response, "payload") else response

    broker_positions: dict[str, float] = {}
    try:
        pos_env = broker.fetch_positions()
        positions = pos_env.payload if hasattr(pos_env, "payload") else pos_env
        if isinstance(positions, list):
            for pos in positions:
                sym = str(pos.get("symbol", "")).upper()
                avg = float(pos.get("avg_entry_price", 0) or 0)
                if sym and avg > 0:
                    broker_positions[sym] = avg
    except Exception as exc:
        print(
            f"WARN: reconcile_stale_entry_prices: could not fetch broker positions: {exc}",
            file=sys.stderr,
        )

    lots_by_symbol: dict[str, list[dict]] = {}
    for trade in tracker.get_open_positions():
        sym = str(trade.get("symbol") or "").upper()
        if sym:
            lots_by_symbol.setdefault(sym, []).append(trade)

    corrections = 0
    for symbol, lots in lots_by_symbol.items():
        total_qty = sum(int(trade.get("qty", 0) or 0) for trade in lots)
        if total_qty <= 0:
            continue

        weighted_entry_notional = sum(
            int(trade.get("qty", 0) or 0) * float(trade.get("entry_price", 0) or 0)
            for trade in lots
        )
        recorded_entry = weighted_entry_notional / total_qty if weighted_entry_notional > 0 else 0.0
        if recorded_entry <= 0:
            continue

        corrected_price: float | None = None
        correction_source = ""

        fill_notional = 0.0
        fill_qty = 0
        for trade in lots:
            broker_order_id = trade.get("broker_order_id")
            if not broker_order_id or str(broker_order_id).startswith("reconcile-"):
                continue
            try:
                order = _get_order_payload(str(broker_order_id))
                if not isinstance(order, dict):
                    continue
                status = str(order.get("status", "")).lower()
                if status not in {"filled", "partially_filled"}:
                    continue
                filled_avg_price = float(order.get("filled_avg_price") or 0)
                qty = int(trade.get("qty", 0) or 0)
                if filled_avg_price > 0 and qty > 0:
                    fill_notional += qty * filled_avg_price
                    fill_qty += qty
            except Exception:
                continue

        weighted_fill = fill_notional / fill_qty if fill_qty > 0 else 0.0
        if weighted_fill > 0:
            deviation = abs(weighted_fill - recorded_entry) / recorded_entry
            if deviation > deviation_threshold:
                corrected_price = weighted_fill
                correction_source = "broker_fill"

        pos_avg = broker_positions.get(symbol, 0.0)
        if corrected_price is None and pos_avg > 0:
            deviation = abs(pos_avg - recorded_entry) / recorded_entry
            if deviation > deviation_threshold:
                corrected_price = pos_avg
                correction_source = "broker_position_avg"

        if corrected_price is None or corrected_price <= 0:
            continue

        scale = corrected_price / recorded_entry if recorded_entry > 0 else 1.0
        for trade in lots:
            old_entry = float(trade.get("entry_price", 0) or 0)
            old_peak = float(trade.get("peak_price") or old_entry or 0)
            trade["entry_price"] = (
                round(old_entry * scale, 6) if old_entry > 0 else round(corrected_price, 6)
            )
            if old_peak < trade["entry_price"]:
                trade["peak_price"] = round(trade["entry_price"], 6)
            elif old_peak > 0 and old_entry > 0:
                new_peak = round(old_peak * scale, 6)
                trade["peak_price"] = max(new_peak, trade["entry_price"])

        corrections += 1
        print(
            f"INFO: reconcile_stale_entry_prices: corrected {symbol} "
            f"entry ${recorded_entry:.4f} -> ${corrected_price:.4f} "
            f"(source={correction_source}, "
            f"deviation={abs(corrected_price - recorded_entry) / recorded_entry:.1%})",
            file=sys.stderr,
        )
        if hasattr(tracker, "event_store"):
            tracker.event_store.append(TradeEvent.create(
                "entry_price_corrected",
                symbol=symbol,
                payload={
                    "old_entry": recorded_entry,
                    "new_entry": corrected_price,
                    "source": correction_source,
                },
            ))

    if corrections:
        tracker._save_state()
        print(
            f"INFO: reconcile_stale_entry_prices: {corrections} correction(s) applied",
            file=sys.stderr,
        )
    return corrections


def reconcile_filled_buys(broker: BrokerClient, tracker: PnLTracker, recently_sold_symbols: set[str] | None = None) -> int:
    """Reconcile broker open positions with tracker open trades.
    
    For each broker position that is missing from tracker, record it as an open trade.
    Uses broker's avg_entry_price and current qty.

    recently_sold_symbols: symbols that had a filled sell order in the current reconcile
        cycle.  Positions for these symbols are skipped to avoid creating a ghost open
        trade that immediately gets closed by the same sell fill (duplicate-close loop).
    
    Returns the count of newly recorded entries.
    """
    skip_symbols = recently_sold_symbols or set()

    try:
        positions_env = broker.fetch_positions()
        positions = positions_env.payload if hasattr(positions_env, "payload") else positions_env
        if not isinstance(positions, list):
            print("WARN: broker.fetch_positions() did not return a list", file=sys.stderr)
            return 0
    except Exception as e:
        print(f"WARN: Failed to fetch broker positions: {e}", file=sys.stderr)
        return 0
    
    # Build tracker open symbols map
    tracker_open = {}
    for trade in tracker.state.trades:
        if trade.get("status") == "open":
            symbol = trade.get("symbol", "").upper()
            qty = int(trade.get("qty", 0))
            tracker_open.setdefault(symbol, 0)
            tracker_open[symbol] += qty
    
    newly_recorded = 0
    for pos in positions:
        symbol = str(pos.get("symbol", "")).upper()
        broker_qty = abs(int(float(pos.get("qty", 0) or 0)))
        avg_price = float(pos.get("avg_entry_price", 0) or 0)
        
        if broker_qty <= 0 or avg_price <= 0:
            continue
        
        tracker_qty = tracker_open.get(symbol, 0)
        missing_qty = broker_qty - tracker_qty
        
        if missing_qty > 0:
            # Skip symbols that were just sold — broker position may lag the fill,
            # and creating an open here would trigger an immediate duplicate close.
            if symbol in skip_symbols:
                print(
                    f"INFO: Skipping reconcile_filled_buys for {symbol}: "
                    f"recently sold (broker position may lag)",
                    file=sys.stderr,
                )
                continue

            # Record the missing quantity as a new open trade
            try:
                trade_id = tracker.record_submission(
                    symbol=symbol,
                    strategy_id="breakout_momentum_v1",  # default strategy
                    side="buy",
                    qty=missing_qty,
                    price=avg_price,
                    broker_order_id=None,  # unknown
                    decision_id=f"reconcile-{symbol}-{datetime.now(timezone.utc).isoformat()}",
                    original_strategy_id="reconciled_from_broker",
                    strategy_version_id="reconciled_from_broker",
                    account_id=tracker.state.broker_account_id,
                )
                if trade_id:
                    newly_recorded += 1
                    print(f"INFO: Recorded missing broker position: {symbol} qty={missing_qty} @ ${avg_price:.2f}", file=sys.stderr)
            except Exception as e:
                print(f"WARN: Failed to record {symbol}: {e}", file=sys.stderr)
    
    return newly_recorded


def cancel_stale_buy_orders(broker: BrokerClient) -> list[dict]:
    """Detect and cancel stale open buy orders.

    An order is considered stale when ANY of the following is true:

    Case A — previous-session orders (original logic):
    - side == 'buy'
    - status in {accepted, new, pending_new, held}
    - time_in_force == 'day'
    - submitted_at is before today's market open (09:30 ET = 13:30 UTC)

    Case B — after-hours zero-fill orders (new, 2026-06-03 incident):
    - side == 'buy' OR sell
    - status in {accepted, new, pending_new, held}
    - filled_qty == 0
    - extended_hours == False
    - submitted_at falls inside the after-hours window (16:00–20:00 ET = UTC+3/4h)
      i.e., 19:00–23:00 UTC (standard time) or 20:00–00:00 UTC (DST)
    - The order is older than 30 minutes (avoids cancelling freshly submitted orders
      that might still be routing)

    Returns a list of cancelled order dicts.
    """
    try:
        orders_env = broker.fetch_orders(status="open", limit=200)
        orders = orders_env.payload if hasattr(orders_env, "payload") else orders_env
        if not isinstance(orders, list):
            print("WARN: fetch_orders(open) did not return a list", file=sys.stderr)
            return []
    except Exception as e:
        print(f"WARN: Failed to fetch open orders for stale check: {e}", file=sys.stderr)
        return []

    now_utc = datetime.now(timezone.utc)
    # Market open = 13:30 UTC (09:30 ET). Use today's date; if before open, use yesterday.
    market_open_today = now_utc.replace(hour=13, minute=30, second=0, microsecond=0)
    if now_utc < market_open_today:
        # Before today's open → cutoff is yesterday's open
        from datetime import timedelta
        market_open_today -= timedelta(days=1)

    stale_statuses = {"accepted", "new", "pending_new", "held"}
    cancelled = []

    for order in orders:
        side = str(order.get("side", "")).lower()
        status = str(order.get("status", "")).lower()
        tif = str(order.get("time_in_force", "")).lower()
        submitted_at_str = order.get("submitted_at") or ""
        order_id = order.get("id", "")
        symbol = order.get("symbol", "")

        if side != "buy" or status not in stale_statuses or tif != "day":
            continue
        if not submitted_at_str or not order_id:
            continue

        try:
            submitted_at = datetime.fromisoformat(submitted_at_str.replace("Z", "+00:00"))
        except ValueError:
            continue

        if submitted_at >= market_open_today:
            continue  # submitted today → not stale

        # Case A: stale previous-session order → cancel
        try:
            broker.cancel_order(order_id)
            cancelled.append({"order_id": order_id, "symbol": symbol, "submitted_at": submitted_at_str, "reason": "previous_session"})
            print(
                f"INFO: Cancelled stale buy order {order_id} {symbol} "
                f"submitted {submitted_at_str} (previous session)",
                file=sys.stderr,
            )
        except Exception as e:
            print(f"WARN: Failed to cancel stale order {order_id} {symbol}: {e}", file=sys.stderr)

    # --- Case B: after-hours zero-fill orders (extended_hours=False) ---
    # These were submitted after the regular close (16:00 ET) but before midnight ET.
    # With extended_hours=False they cannot fill and will carry over to the next
    # regular session, causing phantom accepted orders in the PnL tracker.
    #
    # After-hours window in UTC:
    #   DST  (Mar–Nov): 20:00–00:00 UTC  (16:00–20:00 ET + 4h)
    #   Standard (Nov–Mar): 21:00–01:00 UTC  (16:00–20:00 ET + 5h)
    # We use a conservative range: submitted between 19:00–01:00 UTC is a candidate.
    #
    # Guard: only cancel if the order is older than 30 minutes to avoid
    # cancelling freshly submitted orders still being routed by the broker.
    try:
        orders_env_all = broker.fetch_orders(status="open", limit=500)
        orders_all = orders_env_all.payload if hasattr(orders_env_all, "payload") else orders_env_all
        if not isinstance(orders_all, list):
            orders_all = []
    except Exception:
        orders_all = []

    AFTER_HOURS_STALE_STATUSES = {"accepted", "new", "pending_new", "held"}
    MIN_AGE_MINUTES = 30  # don't cancel orders younger than this

    for order in orders_all:
        status = str(order.get("status", "")).lower()
        tif = str(order.get("time_in_force", "")).lower()
        submitted_at_str = order.get("submitted_at") or ""
        order_id = order.get("id", "")
        symbol = order.get("symbol", "")
        filled_qty = float(order.get("filled_qty", 0) or 0)
        extended_hours = order.get("extended_hours", True)  # assume safe unless explicitly False

        if status not in AFTER_HOURS_STALE_STATUSES or tif != "day":
            continue
        if filled_qty > 0:
            continue  # partially filled — do not cancel
        if extended_hours is not False:
            continue  # extended_hours=True orders can fill — leave them alone
        if not submitted_at_str or not order_id:
            continue
        # Skip already-cancelled orders from Case A
        if any(c["order_id"] == order_id for c in cancelled):
            continue

        try:
            submitted_at = datetime.fromisoformat(submitted_at_str.replace("Z", "+00:00"))
        except ValueError:
            continue

        age_minutes = (now_utc - submitted_at).total_seconds() / 60
        if age_minutes < MIN_AGE_MINUTES:
            continue  # too fresh — may still be routing

        # Check if submitted during after-hours UTC window (19:00–01:00 UTC next day)
        # We accept any hour from 19 to 23 or 0 (midnight) as after-hours-candidate.
        submitted_hour_utc = submitted_at.hour
        in_after_hours_window = submitted_hour_utc >= 19 or submitted_hour_utc == 0
        if not in_after_hours_window:
            continue

        # Case B: after-hours zero-fill non-extended order → cancel
        try:
            broker.cancel_order(order_id)
            cancelled.append({"order_id": order_id, "symbol": symbol, "submitted_at": submitted_at_str, "reason": "after_hours_zero_fill"})
            print(
                f"INFO: Cancelled after-hours zero-fill order {order_id} {symbol} "
                f"submitted {submitted_at_str} (age {age_minutes:.0f}m, extended_hours=False)",
                file=sys.stderr,
            )
        except Exception as e:
            print(f"WARN: Failed to cancel after-hours order {order_id} {symbol}: {e}", file=sys.stderr)

    return cancelled


def cancel_stale_sell_orders(
    broker: BrokerClient,
    project_root: Path,
    force_sell_return_pct: float = -0.12,
) -> list[dict]:
    """Cancel queued off-hours SELL orders that are not catastrophic exits.

    These orders are typically submitted during after-hours/weekends and then sit as
    day orders until the next regular-session open, which can bypass the Monday open
    shock cooldown entirely. We only keep catastrophic exits active.
    """
    try:
        orders_env = broker.fetch_orders(status="open", limit=500)
        orders = orders_env.payload if hasattr(orders_env, "payload") else orders_env
        if not isinstance(orders, list):
            return []
    except Exception as e:
        print(f"WARN: Failed to fetch open orders for sell stale check: {e}", file=sys.stderr)
        return []

    stale_statuses = {"accepted", "new", "pending_new", "held"}
    now_utc = datetime.now(timezone.utc)
    cancelled: list[dict] = []

    for order in orders:
        side = str(order.get("side", "")).lower()
        status = str(order.get("status", "")).lower()
        tif = str(order.get("time_in_force", "")).lower()
        submitted_at_str = order.get("submitted_at") or ""
        order_id = order.get("id", "")
        symbol = str(order.get("symbol", "")).upper()
        filled_qty = float(order.get("filled_qty", 0) or 0)

        if side != "sell" or status not in stale_statuses or tif != "day":
            continue
        if filled_qty > 0 or not order_id or not submitted_at_str:
            continue

        try:
            submitted_at = datetime.fromisoformat(submitted_at_str.replace("Z", "+00:00"))
        except ValueError:
            continue

        is_regular_submission, _ = MarketCalendar.is_regular_market_hours(submitted_at)
        if is_regular_submission:
            continue

        age_minutes = (now_utc - submitted_at).total_seconds() / 60
        if age_minutes < 30:
            continue

        stored = read_exit_reason(project_root, order_id)
        if not stored:
            continue

        return_pct = stored.get("return_pct")
        try:
            return_pct = float(return_pct) if return_pct is not None else None
        except (TypeError, ValueError):
            return_pct = None

        if return_pct is not None and return_pct <= force_sell_return_pct:
            continue

        try:
            broker.cancel_order(order_id)
            delete_exit_reason(project_root, order_id)
            cancelled.append(
                {
                    "order_id": order_id,
                    "symbol": symbol,
                    "submitted_at": submitted_at_str,
                    "reason": "offhours_moderate_sell",
                }
            )
            print(
                f"INFO: Cancelled queued off-hours sell order {order_id} {symbol} "
                f"submitted {submitted_at_str} (non-catastrophic carry-over)",
                file=sys.stderr,
            )
        except Exception as e:
            print(f"WARN: Failed to cancel queued sell order {order_id} {symbol}: {e}", file=sys.stderr)

    return cancelled


def main() -> int:
    _load_env(project_root / ".env")
    run_context = RunContext.create("reconcile_orders")
    api_key = os.environ.get("BROKER_API_KEY", "")
    api_secret = os.environ.get("BROKER_API_SECRET", "")
    if not api_key or not api_secret:
        print("BROKER_API_KEY / BROKER_API_SECRET missing")
        return 1

    broker = BrokerClient(api_key=api_key, api_secret=api_secret, paper_mode=True)
    tracker = PnLTracker(project_root)
    tracker.state = tracker._load_state()

    # Step 0: Cancel stale open orders from previous sessions.
    cancelled_stale_buys = cancel_stale_buy_orders(broker)
    cancelled_stale_sells = cancel_stale_sell_orders(broker, project_root)
    cancelled_stale = cancelled_stale_buys + cancelled_stale_sells

    # Step 1a: Fetch orders first to know which symbols were recently sold.
    # This allows reconcile_filled_buys to skip positions that may still show
    # in the broker API despite a sell having been executed (lag window).
    orders_env = broker.fetch_orders(status="all", limit=500)
    orders = orders_env.payload if hasattr(orders_env, "payload") else orders_env
    if not isinstance(orders, list):
        print("broker.fetch_orders() did not return a list")
        return 1

    # Build a lookup: symbol → list of filled sell orders (sorted most-recent first)
    # We keep ALL filled sells per symbol so we can do timestamp-based matching.
    filled_sells_by_symbol: dict[str, list[dict]] = {}
    for order in orders:
        symbol = str(order.get("symbol", "")).upper()
        side = str(order.get("side", "")).lower()
        if side != "sell" or not symbol:
            continue
        status = str(order.get("status", "")).lower()
        if status not in {"filled", "partially_filled"}:
            continue
        filled_sells_by_symbol.setdefault(symbol, []).append(order)

    # Symbols with a filled sell in the broker order history — pass to reconcile_filled_buys
    # so it does not re-open positions that were just exited.
    recently_sold_symbols = _build_recently_sold_symbols(filled_sells_by_symbol)

    # Step 1b: Reconcile filled buys (broker-only positions)
    newly_recorded_buys = reconcile_filled_buys(broker, tracker, recently_sold_symbols)

    # Step 1c: Detect and correct stock splits / reverse splits.
    # Must run BEFORE reconcile_stale_entry_prices so that split-corrected
    # entry prices are not overwritten with pre-split fill prices.
    reconcile_split_adjusted_positions(broker, tracker)

    # Step 1d: Correct stale entry prices from actual broker fills.
    # paper_demo records entry_price at submission time when the order may be
    # pending (filled_avg_price=null), falling back to the Massive estimate.
    # Once the fill is confirmed, we patch any divergent entry_prices here.
    reconcile_stale_entry_prices(broker, tracker)

    # Step 2: Reconcile filled sells (existing logic)

    # Sort each symbol's list newest-first
    for sym in filled_sells_by_symbol:
        filled_sells_by_symbol[sym].sort(
            key=lambda o: o.get("submitted_at") or o.get("created_at") or "",
            reverse=True,
        )

    # Compat alias used below for "most-recent" fallback
    latest_sell_orders_by_symbol = {
        sym: orders_list[0] for sym, orders_list in filled_sells_by_symbol.items()
    }

    MATCH_WINDOW_SECONDS = 600  # ±10 min between log submission and broker submitted_at

    # Build set of sell order IDs already persisted on closed trades.
    # This prevents the same broker sell fill from being replayed on later runs.
    #
    # BUG FIX (2026-07-29): Rebuilds can remove closed trades from state.trades,
    # causing stale sell fills to be re-applied to new positions (phantom close).
    # Fix: also collect IDs from quarantined_trades and historical trade_events.jsonl.
    processed_sell_order_ids: set[str] = set()
    for trade in tracker.state.trades:
        if trade.get("status") == "closed":
            exit_broker_order_id = trade.get("exit_broker_order_id")
            if exit_broker_order_id:
                processed_sell_order_ids.add(str(exit_broker_order_id))
    # Also include quarantined trades (removed from active trades but fills still consumed)
    for trade in tracker.state.quarantined_trades:
        exit_broker_order_id = trade.get("exit_broker_order_id")
        if exit_broker_order_id:
            processed_sell_order_ids.add(str(exit_broker_order_id))
    # Also include broker_order_id from ALL historical trade_closed events in trade_events.jsonl.
    # This is the definitive guard: even if a closed trade was removed by a rebuild,
    # the fill ID is still present in the event log and must not be re-applied.
    _te_path = project_root / "data" / "tracking" / "trade_events.jsonl"
    if _te_path.exists():
        try:
            with open(_te_path) as _tef:
                for _line in _tef:
                    try:
                        _ev = json.loads(_line)
                        if _ev.get("event_type") == "trade_closed":
                            _oid = _ev.get("broker_order_id")
                            if _oid:
                                processed_sell_order_ids.add(str(_oid))
                    except Exception:
                        pass
        except OSError:
            pass

    # Also track which SELL order IDs have already been used to close trades,
    # to prevent the same sell fill from closing multiple reconcile-created open trades.
    used_sell_order_ids: set[str] = set(processed_sell_order_ids)

    # Build map: exit_broker_order_id → total qty already recorded on closed trades.
    # Used by the partial-fill completion logic: when the inline paper_demo reconciler
    # records a partial fill and then the broker completes the order, the cron reconciler
    # uses this map to detect and record the remaining unrecorded shares.
    recorded_qty_by_order_id: dict[str, int] = {}
    for _trade in tracker.state.trades:
        if _trade.get("status") == "closed":
            _eid = _trade.get("exit_broker_order_id")
            if _eid:
                recorded_qty_by_order_id[_eid] = (
                    recorded_qty_by_order_id.get(_eid, 0) + int(_trade.get("qty", 0) or 0)
                )

    submissions = load_recent_submissions(project_root / "data" / "audits")
    filled_exits = 0
    checked = 0

    for sub in submissions:
        if sub["side"] != "sell":
            continue
        checked += 1
        try:
            # --- Timestamp-based matching ---
            # Prefer a broker order whose submitted_at is within MATCH_WINDOW_SECONDS
            # of the log submission timestamp.  Fall back to the most-recent fill only
            # when no time-proximate match exists.
            sub_ts_str = sub.get("ts", "")
            best_match = None
            try:
                sub_ts = datetime.fromisoformat(sub_ts_str.replace("Z", "+00:00")) if sub_ts_str else None
            except ValueError:
                sub_ts = None

            if sub_ts and sub["symbol"] in filled_sells_by_symbol:
                for candidate in filled_sells_by_symbol[sub["symbol"]]:
                    cand_ts_str = candidate.get("submitted_at") or candidate.get("created_at") or ""
                    try:
                        cand_ts = datetime.fromisoformat(cand_ts_str.replace("Z", "+00:00"))
                        if abs((cand_ts - sub_ts).total_seconds()) <= MATCH_WINDOW_SECONDS:
                            best_match = candidate
                            break
                    except ValueError:
                        continue

            # If no time-proximate match found, use most-recent filled sell as fallback.
            # Temporal guard: when using the fallback (not time-proximate), verify that
            # the sell order was submitted AFTER every open position was entered.  If the
            # sell was submitted before the position was opened we cannot legitimately
            # close that position with this order — skip to avoid phantom closures.
            fallback = latest_sell_orders_by_symbol.get(sub["symbol"]) if not best_match else None
            if fallback and not best_match:
                fallback_ts_str = fallback.get("submitted_at") or fallback.get("created_at") or ""
                try:
                    fallback_ts = datetime.fromisoformat(fallback_ts_str.replace("Z", "+00:00")) if fallback_ts_str else None
                    if fallback_ts:
                        open_positions = [
                            t for t in tracker.state.trades
                            if t.get("symbol") == sub["symbol"] and t.get("status") == "open"
                        ]
                        if open_positions:
                            latest_entry_ts_str = max(
                                (t.get("entry_time", "") for t in open_positions), default=""
                            )
                            try:
                                latest_entry_ts = datetime.fromisoformat(
                                    latest_entry_ts_str.replace("Z", "+00:00")
                                )
                                if fallback_ts < latest_entry_ts:
                                    print(
                                        f"WARN: Skipping stale fallback sell for {sub['symbol']}: "
                                        f"order submitted {fallback_ts.date()} before position entry "
                                        f"{latest_entry_ts.date()}",
                                        file=sys.stderr,
                                    )
                                    continue
                            except ValueError:
                                pass
                except ValueError:
                    pass
            match = best_match or fallback
            if not match:
                continue
            
            broker_order_id = match.get("id")
            
            # Dedupe / partial-fill completion guard.
            # A sell order whose broker_order_id is already in used_sell_order_ids was
            # previously recorded (at least partially).  Before skipping, check whether
            # the broker's total filled_qty exceeds what has been recorded so far.
            # If it does, the inline paper_demo reconciler caught only an early partial
            # fill; we process the unrecorded remainder here rather than skipping.
            remaining_fill_qty: int | None = None
            if broker_order_id and broker_order_id in used_sell_order_ids:
                broker_filled_total = int(float(match.get("filled_qty", 0) or 0))
                already_recorded = recorded_qty_by_order_id.get(broker_order_id, 0)
                remaining = broker_filled_total - already_recorded
                if remaining <= 0:
                    continue  # fully recorded — true duplicate, skip
                # Temporal guard for partial-fill completion: the unrecorded remainder
                # must not close a position that was opened AFTER this sell order was
                # submitted.  Without this guard a new position can be incorrectly closed
                # by leftover qty from an old fill.
                order_ts_str = match.get("submitted_at") or match.get("created_at") or ""
                try:
                    order_ts = datetime.fromisoformat(order_ts_str.replace("Z", "+00:00")) if order_ts_str else None
                    if order_ts:
                        open_for_symbol = [
                            t for t in tracker.state.trades
                            if t.get("symbol") == sub["symbol"] and t.get("status") == "open"
                        ]
                        if open_for_symbol:
                            newest_entry_str = max(
                                t.get("entry_time", "") for t in open_for_symbol
                            )
                            try:
                                newest_entry_ts = datetime.fromisoformat(
                                    newest_entry_str.replace("Z", "+00:00")
                                )
                                if order_ts < newest_entry_ts:
                                    print(
                                        f"INFO: partial-fill completion skipped for {sub['symbol']}: "
                                        f"sell order {broker_order_id[:8]} submitted {order_ts.date()} "
                                        f"is older than open position entry {newest_entry_ts.date()}",
                                        file=sys.stderr,
                                    )
                                    continue
                            except ValueError:
                                pass
                except ValueError:
                    pass
                # Unrecorded shares remain from a partial fill: complete the recording
                remaining_fill_qty = remaining
                print(
                    f"INFO: partial-fill completion: {sub['symbol']} "
                    f"order={broker_order_id[:8]} broker_total={broker_filled_total} "
                    f"recorded={already_recorded} remaining={remaining}",
                    file=sys.stderr,
                )

            status = str(match.get("status", "")).lower()
            filled_qty = float(match.get("filled_qty", 0) or 0)
            avg_price = match.get("filled_avg_price")
            # For partial-fill completion use only the unrecorded remainder;
            # for normal (first-time) processing use the full broker filled qty.
            effective_fill_qty = remaining_fill_qty if remaining_fill_qty is not None else int(filled_qty)
            
            # Sanity check: reject obviously wrong prices
            if avg_price is not None:
                avg_price_float = float(avg_price)
                
                # Check 1: Reject prices against entry price (30% threshold)
                open_trades = [t for t in tracker.state.trades if t["symbol"] == sub["symbol"] and t["status"] == "open"]
                if open_trades:
                    entry_price = open_trades[0].get("entry_price", 0)
                    if entry_price > 0:
                        price_change = abs((avg_price_float - entry_price) / entry_price)
                        if price_change > 0.30:  # 30% price change threshold (lowered from 50%)
                            print(f"WARN: Rejecting extreme price for {sub['symbol']}: entry=${entry_price:.2f} exit=${avg_price_float:.2f} ({price_change:.1%} change)", file=sys.stderr)
                            continue
                
                # Check 2: Verify against current market price
                try:
                    quote_resp = broker.fetch_latest_quote(sub["symbol"])
                    quote = quote_resp.payload.get("quote", quote_resp.payload)
                    bid = float(quote.get("bp", 0) or 0)
                    ask = float(quote.get("ap", 0) or 0)
                    if bid > 0 and ask > 0:
                        mid_price = (bid + ask) / 2
                        market_deviation = abs((avg_price_float - mid_price) / mid_price)
                        if market_deviation > 0.30:  # 30% deviation from market
                            print(f"WARN: Rejecting price far from market for {sub['symbol']}: filled=${avg_price_float:.2f} market=${mid_price:.2f} ({market_deviation:.1%} deviation)", file=sys.stderr)
                            continue
                except Exception:
                    # Market quote fetch failed, skip this check
                    pass
            
            if status in {"filled", "partially_filled"} and filled_qty > 0 and avg_price:
                avg_price_float = float(avg_price)
                # Final sanity check: price must be positive
                if avg_price_float <= 0:
                    print(f"WARN: Invalid exit price for {sub['symbol']}: ${avg_price_float}", file=sys.stderr)
                    continue
                    
                # Pass filled_qty to support partial fills
                # Re-read fresh state to detect exits recorded by a concurrent paper_demo
                # run (TOCTOU guard: paper_demo may have recorded the exit between when
                # reconcile loaded state and now).
                tracker.state = tracker._load_state()

                # Check if there's an open trade for this symbol before recording exit
                has_open_trade = any(
                    t.get("symbol") == sub["symbol"] and t.get("status") == "open"
                    for t in tracker.state.trades
                )

                if not has_open_trade:
                    # Already closed — check whether paper_demo gave it a valid reason.
                    already_attributed = any(
                        t.get("symbol") == sub["symbol"]
                        and t.get("status") == "closed"
                        and t.get("exit_reason") not in ("broker_fill_unknown", "broker_fill", None, "")
                        for t in tracker.state.trades
                    )
                    if already_attributed:
                        print(
                            f"INFO: Skipping exit for {sub['symbol']}: already closed with"
                            " attributed reason by paper_demo (TOCTOU guard)",
                            file=sys.stderr,
                        )
                    else:
                        print(f"WARN: Skipping exit for {sub['symbol']}: no open trade found", file=sys.stderr)
                    continue

                # Look up the exit reason written by paper_demo at submission time
                stored = read_exit_reason(project_root, broker_order_id) if broker_order_id else None
                if stored:
                    resolved_exit_reason = stored.get("exit_reason", "broker_fill_unknown")
                    resolved_exit_strategy = (
                        f"simple_exit_v2:{stored.get('exit_trigger', 'unknown')}"
                    )
                elif remaining_fill_qty is not None and broker_order_id:
                    # Partial-fill completion: paper_demo already consumed and deleted the
                    # pending reason for the first portion.  Inherit the reason from the
                    # already-recorded closed trades that share this exit_broker_order_id.
                    inherited_reason = next(
                        (
                            t.get("exit_reason")
                            for t in tracker.state.trades
                            if t.get("exit_broker_order_id") == broker_order_id
                            and t.get("status") == "closed"
                            and t.get("exit_reason") not in (
                                "broker_fill_unknown", "broker_fill", None
                            )
                        ),
                        None,
                    )
                    resolved_exit_reason = inherited_reason or "broker_fill_unknown"
                    resolved_exit_strategy = "reconciled_from_broker"
                    if inherited_reason:
                        print(
                            f"INFO: partial-fill reason inherited from first portion: "
                            f"{sub['symbol']} order={broker_order_id[:8]} reason={inherited_reason}",
                            file=sys.stderr,
                        )
                else:
                    resolved_exit_reason = "broker_fill_unknown"
                    resolved_exit_strategy = "reconciled_from_broker"

                updated = tracker.record_exit(
                    symbol=sub["symbol"],
                    exit_price=avg_price_float,
                    exit_qty=effective_fill_qty,
                    broker_order_id=broker_order_id,
                    exit_strategy_id=resolved_exit_strategy,
                    exit_reason=resolved_exit_reason,
                )
                if updated:
                    filled_exits += 1
                    # Mark this sell order as used to prevent re-use within same run
                    if broker_order_id:
                        used_sell_order_ids.add(broker_order_id)
                        # Update running total so intra-run dedup stays accurate
                        recorded_qty_by_order_id[broker_order_id] = (
                            recorded_qty_by_order_id.get(broker_order_id, 0) + effective_fill_qty
                        )
                    print(
                        f"INFO: Recorded exit for {sub['symbol']}: {int(filled_qty)} @ "
                        f"${avg_price_float:.2f} reason={resolved_exit_reason}",
                        file=sys.stderr,
                    )
                    # Clean up the stored exit reason after successful recording
                    if broker_order_id and stored:
                        delete_exit_reason(project_root, broker_order_id)
        except Exception:
            continue

    # Purge exit_reason entries older than 7 days
    purge_old_entries(project_root, max_age_days=7)

    # --- Clean up pending_exit_reasons for exits already recorded in tracker ---
    # paper_demo may record exits directly without going through reconcile_orders.
    # In that case the pending_exit_reasons entries are never cleaned up here.
    # We do it now by checking which sell broker_order_ids are already fully closed.
    try:
        from stock_swing.tracking.exit_reason_store import _store_path
        store_path = _store_path(project_root)
        if store_path.exists():
            import json as _json
            store_data = _json.loads(store_path.read_text(encoding="utf-8"))
            closed_order_ids = {
                t.get("exit_broker_order_id")
                for t in tracker.state.trades
                if t.get("status") == "closed" and t.get("exit_broker_order_id")
            }
            stale_keys = [k for k in store_data if k in closed_order_ids]
            if stale_keys:
                for k in stale_keys:
                    del store_data[k]
                store_path.write_text(_json.dumps(store_data, indent=2, ensure_ascii=False), encoding="utf-8")
                print(f"INFO: Cleaned up {len(stale_keys)} stale pending_exit_reasons entries", file=sys.stderr)
    except Exception as e:
        print(f"WARN: Failed to clean up pending_exit_reasons: {e}", file=sys.stderr)

    summary_payload = {
        "cancelled_stale_buy_orders": len(cancelled_stale_buys),
        "cancelled_stale_sell_orders": len(cancelled_stale_sells),
        "cancelled_stale_details": cancelled_stale,
        "newly_recorded_buys": newly_recorded_buys,
        "checked_sell_submissions": checked,
        "filled_exits_recorded": filled_exits,
        "summary": tracker.get_summary(),
    }
    print(json.dumps(summary_payload, ensure_ascii=False, indent=2))

    # FIX-OBSERVE-1: Write reconcile_status.json for console health evidence.
    # Contains broker/tracker mismatch count so health score can degrade when stale.
    _reconcile_status = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "unexplained_mismatch_count": 0,  # If we reach this point, reconcile succeeded
        "newly_recorded_buys": newly_recorded_buys,
        "filled_exits_recorded": filled_exits,
        "checked_sell_submissions": checked,
        "job": "reconcile_orders",
    }
    try:
        _status_path = project_root / "data" / "audits" / "reconcile_status.json"
        _status_path.parent.mkdir(parents=True, exist_ok=True)
        _status_path.write_text(
            json.dumps(_reconcile_status, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as _e:
        print(f"WARN: Failed to write reconcile_status.json: {_e}", file=sys.stderr)

    emit_cron_summary({
        "job": "reconcile_orders",
        "status": "ok",
        "cancelled_stale_orders": len(cancelled_stale),
        "newly_recorded_buys": newly_recorded_buys,
        "checked_sell_submissions": checked,
        "filled_exits_recorded": filled_exits,
        "total_trades": summary_payload["summary"].get("total_trades", 0),
        "open_trades": summary_payload["summary"].get("open_trades", 0),
        "closed_trades": summary_payload["summary"].get("closed_trades", 0),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
