"""Narrow paper submission journal over existing fsync TradeEventStore.

Cooperating callers only. No automatic retry, cancellation or historical repair.
SELL capacity is requalified under the account lock, including across decisions.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from stock_swing.tracking.trade_event_store import TradeEvent, TradeEventStore


class SubmissionUncertain(Exception):
    """No new send allowed without qualified resolution/snapshot."""

    submitted_qty: int | None = None


class SubmissionHeld(SubmissionUncertain):
    """Known prior intent or a cooperating caller already owns the lock."""


class SubmissionRejected(Exception):
    """Broker explicitly returned terminal rejected, not a transport failure."""

    submitted_qty: int | None = None


class SubmissionGuard:
    def __init__(self, broker: Any, project_root: Path, account_id: str | None):
        self.snapshot_invalidated = False
        self.broker = broker
        self.account_id = account_id
        route = getattr(broker, "base_url", None)
        self.qualified = isinstance(account_id, str) and bool(account_id.strip()) and isinstance(route, str) and bool(route)
        self.namespace = hashlib.sha256(json.dumps(["paper", route, account_id]).encode()).hexdigest()
        self.store = TradeEventStore(project_root, f"data/tracking/submission_intents/{self.namespace}.jsonl")
        self.marker = self.store.path.with_suffix(".initialized")
        self.lock_path = self.store.path.with_suffix(".lock")

    def __getattr__(self, name: str) -> Any:
        return getattr(self.broker, name)

    def _append(self, event_type: str, **payload: Any) -> None:
        self.store.append(TradeEvent.create(event_type, payload=dict(namespace=self.namespace, **payload)))

    def _load(self) -> dict[str, dict[str, Any]]:
        path = self.store.path
        if path.is_symlink() or self.marker.is_symlink():
            raise ValueError("intent_symlink")
        if not path.exists():
            if self.marker.exists():
                raise ValueError("intent_history_missing")
            self._append("submission_guard_initialized")
            with self.marker.open("x") as fh:
                fh.write(self.namespace + "\n"); fh.flush(); os.fsync(fh.fileno())
        if not self.marker.exists():
            raise ValueError("intent_marker_missing")
        if self.marker.exists() and self.marker.read_text() != self.namespace + "\n":
            raise ValueError("intent_marker_mismatch")
        raw = path.read_bytes()
        if not raw.endswith(b"\n"):
            raise ValueError("intent_partial_line")
        states: dict[str, dict[str, Any]] = {}
        self.sell_snapshots: dict[str, dict[str, Any]] = {}
        rows = raw.decode().splitlines()
        for index, line in enumerate(rows):
            event = TradeEvent(**json.loads(line))
            stamp = datetime.fromisoformat(event.created_at)
            if stamp.tzinfo is None or event.payload.get("namespace") != self.namespace:
                raise ValueError("intent_provenance_invalid")
            kind, payload = event.event_type, event.payload
            if index == 0:
                if kind != "submission_guard_initialized":
                    raise ValueError("intent_initialization_missing")
                continue
            if kind == "submission_sell_snapshot":
                symbol = payload.get("symbol")
                if not isinstance(symbol, str) or not symbol:
                    raise ValueError("sell_snapshot_symbol_invalid")
                snapshot = payload.get("snapshot")
                self._check_sell_snapshot(snapshot, self.sell_snapshots.get(symbol), symbol)
                self.sell_snapshots[symbol] = snapshot
                continue
            key = payload.get("client_order_id")
            if not isinstance(key, str) or not key:
                raise ValueError("intent_id_invalid")
            if kind == "submission_intent_prepared":
                if key in states or not isinstance(payload.get("order"), dict) or not payload.get("decision_id"):
                    raise ValueError("intent_duplicate_or_invalid_prepare")
                expected = self._client_id(payload["decision_id"])
                self._validate_order(payload["order"])
                if "requested_order" in payload:
                    requested = payload["requested_order"]
                    self._validate_order(requested)
                    if (requested["side"] != "sell" or requested["qty"] < payload["order"]["qty"]
                            or dict(requested, qty=payload["order"]["qty"]) != payload["order"]):
                        raise ValueError("intent_requested_quantity_invalid")
                if key != expected:
                    raise ValueError("intent_identity_mismatch")
                states[key] = dict(payload, state="prepared")
            elif kind == "submission_intent_outcome":
                if key not in states or states[key]["state"] not in {"prepared", "unknown"} or payload.get("state") not in {"unknown", "accepted", "rejected"}:
                    raise ValueError("intent_transition_invalid")
                if payload["state"] != "unknown":
                    if payload["state"] == "rejected" and payload.get("response") is None:
                        proof = payload.get("http_rejection")
                        if (not isinstance(proof, dict) or set(proof) != {"status"}
                                or type(proof["status"]) is not int
                                or proof["status"] not in {400, 401, 403, 422}):
                            raise ValueError("intent_rejection_proof_invalid")
                    else:
                        self._validate_response(payload.get("response"), key, states[key]["order"])
                        expected_state = "rejected" if payload["response"]["status"] == "rejected" else "accepted"
                        if expected_state != payload["state"]:
                            raise ValueError("intent_outcome_mismatch")
                states[key].update(state=payload["state"], response=payload.get("response"))
            else:
                raise ValueError("intent_event_unknown")
        return states

    def _client_id(self, decision_id: str) -> str:
        if not isinstance(decision_id, str) or not decision_id:
            raise ValueError("decision_id_invalid")
        return "ss-" + hashlib.sha256((self.namespace + ":" + decision_id).encode()).hexdigest()[:40]

    @staticmethod
    def _validate_order(order: dict[str, Any]) -> None:
        if set(order) != {"symbol", "side", "order_type", "qty", "time_in_force", "limit_price"}:
            raise ValueError("intent_order_shape_invalid")
        if not isinstance(order["symbol"], str) or not order["symbol"] or order["side"] not in {"buy", "sell"} or order["order_type"] not in {"market", "limit"} or order["time_in_force"] not in {"day", "gtc", "opg", "cls", "ioc", "fok"}:
            raise ValueError("intent_order_fields_invalid")
        if isinstance(order["qty"], bool) or not isinstance(order["qty"], int) or order["qty"] < 1:
            raise ValueError("intent_quantity_invalid")
        if order["order_type"] == "limit":
            price = order["limit_price"]
            if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
                raise ValueError("intent_limit_invalid")

    @staticmethod
    def _validate_response(response: Any, key: str, order: dict[str, Any]) -> None:
        if not isinstance(response, dict) or not isinstance(response.get("id"), str) or not response["id"] or response.get("client_order_id") != key:
            raise ValueError("order_lookup_identity_mismatch")
        for field in ["symbol", "side", "time_in_force"]:
            if response.get(field) != order[field]:
                raise ValueError("order_lookup_payload_mismatch")
        if response.get("type") != order["order_type"]:
            raise ValueError("order_lookup_type_mismatch")
        qty = float(response.get("qty"))
        filled = float(response.get("filled_qty"))
        if not math.isfinite(qty) or qty != order["qty"] or not math.isfinite(filled) or not 0 <= filled <= qty or not filled.is_integer():
            raise ValueError("order_lookup_quantity_mismatch")
        if order["order_type"] == "limit" and float(response.get("limit_price")) != float(order["limit_price"]):
            raise ValueError("order_lookup_limit_mismatch")
        if response.get("status") not in {"new", "accepted", "pending_new", "partially_filled", "filled", "canceled", "expired", "rejected", "replaced", "pending_cancel", "pending_replace", "accepted_for_bidding", "held", "done_for_day"}:
            raise ValueError("order_lookup_status_unknown")

    def _lookup(self, key: str, order: dict[str, Any]) -> dict[str, Any] | None:
        try:
            response = self.broker.fetch_order_by_client_id(key).payload
            self._validate_response(response, key, order)
            return response
        except Exception:
            # 404/malformed/timeout is not proof that the first send failed.
            return None

    def _outcome(self, key: str, response: dict[str, Any] | None) -> str:
        state = "unknown" if response is None else ("rejected" if response["status"] == "rejected" else "accepted")
        self._append("submission_intent_outcome", client_order_id=key, state=state, response=response)
        return state

    _SELL_ACTIVE = {"new", "accepted", "pending_new", "partially_filled",
                    "pending_cancel", "held", "accepted_for_bidding", "done_for_day"}
    _SELL_TERMINAL = {"filled", "canceled", "expired", "rejected"}

    @staticmethod
    def _number(value: Any) -> Decimal:
        if value is None or isinstance(value, bool):
            raise ValueError("sell_number_missing")
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError("sell_number_nonfinite")
        return number

    @classmethod
    def _sell_order(cls, raw: Any, symbol: str, previous: dict | None = None) -> dict:
        if not isinstance(raw, dict):
            raise ValueError("sell_order_missing")
        fields = ("id", "client_order_id", "symbol", "side", "type", "time_in_force")
        if any(not isinstance(raw.get(k), str) or not raw[k] for k in fields):
            raise ValueError("sell_order_identity_missing")
        if (raw["symbol"] != symbol or raw["side"] != "sell"
                or raw["status"] not in cls._SELL_ACTIVE | cls._SELL_TERMINAL
                or raw["type"] not in {"market", "limit", "stop", "stop_limit", "trailing_stop"}
                or raw["time_in_force"] not in {"day", "gtc", "opg", "cls", "ioc", "fok"}
                or raw.get("legs") or raw.get("order_class", "simple") not in {"simple", ""}):
            raise ValueError("sell_order_unqualified")
        qty, filled = cls._number(raw.get("qty")), cls._number(raw.get("filled_qty"))
        if qty <= 0 or not 0 <= filled <= qty or (raw["status"] == "filled" and filled != qty):
            raise ValueError("sell_order_quantity_invalid")
        result = {k: raw[k] for k in fields}
        result.update(qty=str(qty), filled_qty=str(filled), status=raw["status"])
        if previous:
            if (any(result[k] != previous[k] for k in fields)
                    or qty != cls._number(previous["qty"])
                    or filled < cls._number(previous["filled_qty"])
                    or (previous["status"] in cls._SELL_TERMINAL and result != previous)):
                raise ValueError("sell_order_transition_invalid")
        return result

    @classmethod
    def _sell_capacity(cls, raw: Decimal, orders: dict, previous: dict | None) -> tuple[Decimal, Decimal | None]:
        old_orders = previous["orders"] if previous else {}
        if not set(old_orders) <= set(orders):
            raise ValueError("sell_history_disappeared")
        delta = sum((cls._number(o["filled_qty"]) - cls._number(old_orders.get(k, {}).get("filled_qty", 0))
                     for k, o in orders.items()), Decimal(0))
        if delta < 0:
            raise ValueError("sell_fill_regressed")
        prior_barrier = previous.get("barrier") if previous else None
        if delta or prior_barrier is not None:
            limit = max(Decimal(0), (cls._number(previous["effective"]) if previous else raw) - delta)
            return min(raw, limit), (limit if raw > limit else None)
        return raw, None

    @classmethod
    def _check_sell_snapshot(cls, snapshot: Any, previous: dict | None, symbol: str) -> None:
        if not isinstance(snapshot, dict) or set(snapshot) != {"raw", "effective", "barrier", "orders"}:
            raise ValueError("sell_snapshot_shape_invalid")
        raw, effective = cls._number(snapshot["raw"]), cls._number(snapshot["effective"])
        if raw < 0 or effective < 0 or not isinstance(snapshot["orders"], dict):
            raise ValueError("sell_snapshot_quantity_invalid")
        for identity, order in snapshot["orders"].items():
            old = previous["orders"].get(identity) if previous else None
            if cls._sell_order(order, symbol, old) != order or identity != order["id"]:
                raise ValueError("sell_snapshot_order_invalid")
        expected, barrier = cls._sell_capacity(raw, snapshot["orders"], previous)
        if effective != expected or snapshot["barrier"] != (str(barrier) if barrier is not None else None):
            raise ValueError("sell_snapshot_transition_invalid")

    def _sell_view(self, symbol: str) -> tuple:
        account = self.broker.fetch_account().payload
        if (not isinstance(account, dict) or account.get("id") != self.account_id
                or account.get("status") != "ACTIVE"
                or any(account.get(k, False) is not False for k in ("trading_blocked", "account_blocked", "trade_suspended_by_user"))):
            raise ValueError("sell_account_unqualified")
        positions = self.broker.fetch_positions().payload
        orders = self.broker.fetch_orders(status="open", limit=500).payload
        if not isinstance(positions, list) or not isinstance(orders, list) or len(orders) >= 500:
            raise ValueError("sell_snapshot_incomplete")
        seen = set(); qty = Decimal(0)
        for position in positions:
            if not isinstance(position, dict) or not isinstance(position.get("symbol"), str) or not position["symbol"] or position["symbol"] in seen:
                raise ValueError("sell_positions_identity_invalid")
            seen.add(position["symbol"])
            if position["symbol"] == symbol:
                qty = self._number(position.get("qty"))
                if qty < 0 or position.get("side", "long") != "long":
                    raise ValueError("sell_position_not_long")
        pending = {}; seen = set()
        for order in orders:
            if (not isinstance(order, dict) or not isinstance(order.get("symbol"), str) or not order["symbol"]
                    or not isinstance(order.get("id"), str) or not order["id"] or order["id"] in seen):
                raise ValueError("sell_orders_identity_invalid")
            seen.add(order["id"])
            if order["symbol"] == symbol:
                normalized = self._sell_order(order, symbol)
                if normalized["status"] not in self._SELL_ACTIVE:
                    raise ValueError("sell_open_order_not_active")
                pending[order["id"]] = normalized
        return qty, pending

    def _available_sell(self, symbol: str, states: dict) -> int:
        first = self._sell_view(symbol)
        previous = self.sell_snapshots.get(symbol)
        tracked = dict(previous["orders"]) if previous else {}
        current = dict(first[1])
        for identity, old in tracked.items():
            if identity in current:
                current[identity] = self._sell_order(current[identity], symbol, old)
            elif old["status"] in self._SELL_TERMINAL:
                current[identity] = old
            else:
                current[identity] = self._sell_order(self.broker.fetch_order(identity).payload, symbol, old)
                if current[identity]["status"] not in self._SELL_TERMINAL:
                    raise ValueError("sell_missing_open_order")
        for state in states.values():
            order, response = state["order"], state.get("response")
            if order["symbol"] != symbol or order["side"] != "sell" or response is None:
                continue
            old = self._sell_order(response, symbol)
            identity = old["id"]
            if identity in current:
                current[identity] = self._sell_order(current[identity], symbol, old)
            else:
                got = self.broker.fetch_order_by_client_id(response["client_order_id"]).payload
                current[identity] = self._sell_order(got, symbol, old)
                if current[identity]["status"] not in self._SELL_TERMINAL:
                    raise ValueError("sell_ack_order_not_in_open_snapshot")
        if self._sell_view(symbol) != first:
            raise ValueError("sell_snapshot_changed")
        effective, barrier = self._sell_capacity(first[0], current, previous)
        snapshot = dict(raw=str(first[0]), effective=str(effective),
                        barrier=str(barrier) if barrier is not None else None, orders=current)
        self._check_sell_snapshot(snapshot, previous, symbol)
        self._append("submission_sell_snapshot", symbol=symbol, snapshot=snapshot)
        remaining = sum((self._number(o["qty"]) - self._number(o["filled_qty"])
                         for o in current.values() if o["status"] in self._SELL_ACTIVE), Decimal(0))
        return max(0, int(effective - remaining))

    def submit_intent(self, decision_id: str, **order: Any) -> dict[str, Any]:
        if not self.qualified:
            raise SubmissionUncertain("paper_account_identity_unavailable")
        sent_qty = None
        try:
            self._validate_order(order)
            with self.lock_path.open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise SubmissionHeld("submission_guard_busy") from None
                from stock_swing.execution.cancellation_guard import pending_cancellations
                cancellations = pending_cancellations(self)
                if any(order["side"] == "buy" or r["order"]["symbol"] == order["symbol"] for r in cancellations):
                    raise SubmissionUncertain("cancellation_unresolved_reservation_retained")
                states = self._load()
                key = self._client_id(decision_id)
                previous_unknown = False
                for old_key, state in states.items():
                    if state["state"] in {"prepared", "unknown"}:
                        previous_unknown = True
                        response = self._lookup(old_key, state["order"])
                        if response is not None:
                            state["state"] = self._outcome(old_key, response)
                states = self._load()
                if key in states:
                    if states[key].get("requested_order", states[key]["order"]) != order:
                        raise SubmissionUncertain("same_intent_payload_changed")
                    raise SubmissionHeld("intent_already_recorded:" + states[key]["state"])
                unresolved = [s for s in states.values() if s["state"] in {"prepared", "unknown"}]
                self.snapshot_invalidated = self.snapshot_invalidated or previous_unknown
                if (order["side"] == "buy" and self.snapshot_invalidated) or any(s["order"]["symbol"] == order["symbol"] for s in unresolved):
                    raise SubmissionUncertain("prior_intent_unknown_or_snapshot_refresh_required")
                requested = dict(order)
                if order["side"] == "sell":
                    available = self._available_sell(order["symbol"], states)
                    if available < 1:
                        raise SubmissionHeld("sell_position_fully_reserved_or_unreflected")
                    order = dict(order, qty=min(order["qty"], available))
                # Persist before the external side effect, under cooperating lock.
                self._append("submission_intent_prepared", client_order_id=key, decision_id=decision_id, order=order,
                             **({"requested_order": requested} if order["side"] == "sell" else {}))
                try:
                    sent_qty = order["qty"]
                    response = self.broker.submit_order(**order, client_order_id=key)
                    self._validate_response(response, key, order)
                except Exception:
                    response = self._lookup(key, order)
                state = self._outcome(key, response)
                if state == "unknown":
                    uncertain = SubmissionUncertain("submission_outcome_unknown:" + key)
                    uncertain.submitted_qty = order["qty"]
                    raise uncertain
                if state == "rejected":
                    raise SubmissionRejected("broker_terminal_rejected:" + key)
                return response
        except SubmissionUncertain as exc:
            exc.submitted_qty = sent_qty
            raise
        except SubmissionRejected as exc:
            exc.submitted_qty = sent_qty
            raise
        except Exception as exc:
            uncertain = SubmissionUncertain("intent_store_unavailable:" + type(exc).__name__)
            uncertain.submitted_qty = sent_qty
            raise uncertain from exc
