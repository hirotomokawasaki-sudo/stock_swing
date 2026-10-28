"""Narrow paper submission journal over existing fsync TradeEventStore.

Cooperating callers only. No automatic retry, cancellation, historical repair,
or durable identity equivalence for a newly generated decision ID.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from stock_swing.tracking.trade_event_store import TradeEvent, TradeEventStore


class SubmissionUncertain(Exception):
    """No new send allowed without qualified resolution/snapshot."""


class SubmissionHeld(SubmissionUncertain):
    """Known prior intent or a cooperating caller already owns the lock."""


class SubmissionRejected(Exception):
    """Broker explicitly returned terminal rejected, not a transport failure."""


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
            key = payload.get("client_order_id")
            if not isinstance(key, str) or not key:
                raise ValueError("intent_id_invalid")
            if kind == "submission_intent_prepared":
                if key in states or not isinstance(payload.get("order"), dict) or not payload.get("decision_id"):
                    raise ValueError("intent_duplicate_or_invalid_prepare")
                expected = self._client_id(payload["decision_id"])
                self._validate_order(payload["order"])
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

    def submit_intent(self, decision_id: str, **order: Any) -> dict[str, Any]:
        if not self.qualified:
            raise SubmissionUncertain("paper_account_identity_unavailable")
        try:
            self._validate_order(order)
            with self.lock_path.open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise SubmissionHeld("submission_guard_busy") from None
                states = self._load()
                key = self._client_id(decision_id)
                previous_unknown = False
                for old_key, state in states.items():
                    if state["state"] in {"prepared", "unknown"}:
                        previous_unknown = True
                        response = self._lookup(old_key, state["order"])
                        if response is not None:
                            state["state"] = self._outcome(old_key, response)
                if key in states:
                    if states[key]["order"] != order:
                        raise SubmissionUncertain("same_intent_payload_changed")
                    raise SubmissionHeld("intent_already_recorded:" + states[key]["state"])
                unresolved = [s for s in states.values() if s["state"] in {"prepared", "unknown"}]
                self.snapshot_invalidated = self.snapshot_invalidated or previous_unknown
                if (order["side"] == "buy" and self.snapshot_invalidated) or any(s["order"]["symbol"] == order["symbol"] for s in unresolved):
                    raise SubmissionUncertain("prior_intent_unknown_or_snapshot_refresh_required")
                # Persist before the external side effect, under cooperating lock.
                self._append("submission_intent_prepared", client_order_id=key, decision_id=decision_id, order=order)
                try:
                    response = self.broker.submit_order(**order, client_order_id=key)
                    self._validate_response(response, key, order)
                except Exception:
                    response = self._lookup(key, order)
                state = self._outcome(key, response)
                if state == "unknown":
                    raise SubmissionUncertain("submission_outcome_unknown:" + key)
                if state == "rejected":
                    raise SubmissionRejected("broker_terminal_rejected:" + key)
                return response
        except (SubmissionUncertain, SubmissionRejected):
            raise
        except Exception as exc:
            raise SubmissionUncertain("intent_store_unavailable:" + type(exc).__name__) from exc
