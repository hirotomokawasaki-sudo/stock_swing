"""Narrow paper submission journal over existing fsync TradeEventStore.

Cooperating callers only. No automatic retry, cancellation or historical repair.
SELL capacity is requalified under the account lock, including across decisions.
An owner-directed Paper quarantine may isolate a prior-session unknown BUY;
it never classifies that order as rejected or authorizes its symbol again.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

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
        self.project_root = Path(project_root)
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
        self.quarantines: dict[str, dict[str, Any]] = {}
        self._prepared_at: dict[str, str] = {}
        self._outcome_hashes: dict[str, str] = {}
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
                self._prepared_at[key] = event.created_at
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
                self._outcome_hashes[key] = hashlib.sha256(line.encode()).hexdigest()
            elif kind == "submission_intent_quarantined":
                if (key not in states or states[key]['state'] != 'unknown'
                        or key in self.quarantines or self.quarantines
                        or payload.get('target_outcome_sha256') != self._outcome_hashes.get(key)):
                    raise ValueError('quarantine_target_changed_or_duplicate')
                self._check_quarantine(payload, states[key], event.created_at)
                self.quarantines[key] = payload
            elif kind == "submission_quarantine_revoked":
                if key not in self.quarantines:
                    raise ValueError('quarantine_revocation_without_activation')
                self._check_authority(payload.get('authority'))
                self.quarantines.pop(key)
            else:
                raise ValueError("intent_event_unknown")
        self.quarantines = {k:v for k,v in self.quarantines.items() if states[k]['state']=='unknown'}
        if any(v['target_outcome_sha256']!=self._outcome_hashes[k] for k,v in self.quarantines.items()):
            raise ValueError('quarantine_outcome_changed')
        return states

    @staticmethod
    def _check_authority(authority: Any) -> None:
        if (not isinstance(authority, dict)
                or set(authority) != {'kind','requester_id','reference','instruction_sha256'}
                or authority['kind'] != 'owner_instruction'
                or any(not isinstance(authority[k], str) or not authority[k].strip()
                       for k in ('requester_id','reference'))
                or not isinstance(authority['instruction_sha256'], str)
                or len(authority['instruction_sha256']) != 64
                or any(c not in '0123456789abcdef' for c in authority['instruction_sha256'])):
            raise ValueError('quarantine_owner_authority_missing')

    def _paper_quarantine_only(self) -> None:
        from stock_swing.core.runtime import read_runtime_mode
        if (not self.qualified or getattr(self.broker, 'paper_mode', None) is not True
                or urlsplit(self.broker.base_url).hostname != 'paper-api.alpaca.markets'
                or read_runtime_mode(self.project_root) != 'paper'):
            raise ValueError('quarantine_paper_only')
        for rel in ('data','data/tracking','data/tracking/submission_intents'):
            if (self.project_root/rel).is_symlink():
                raise ValueError('quarantine_symlink')

    @staticmethod
    def _q_time(value: str) -> datetime:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            raise ValueError('quarantine_ambiguous_time')
        return stamp.astimezone(timezone.utc)

    def _q_view(self) -> dict:
        account = self.broker.fetch_account().payload
        if (not isinstance(account, dict) or account.get('id') != self.account_id
                or account.get('status') != 'ACTIVE' or account.get('currency') != 'USD'
                or any(account.get(k, False) is not False for k in
                       ('trading_blocked','account_blocked','trade_suspended_by_user'))):
            raise ValueError('quarantine_account_unqualified')
        funds = {k:str(self._number(account[k])) for k in
                 ('cash','buying_power','non_marginable_buying_power')}
        if (any(Decimal(v) < 0 for v in funds.values())
                or Decimal(funds['buying_power'])<=0 or Decimal(funds['non_marginable_buying_power'])<=0):
            raise ValueError('quarantine_negative_funds')
        positions = self.broker.fetch_positions().payload
        orders = self.broker.fetch_orders(status='open', limit=500).payload
        if not isinstance(positions,list) or not isinstance(orders,list) or len(orders)>=500:
            raise ValueError('quarantine_incomplete_snapshot')
        pos = []; seen = set()
        for row in positions:
            symbol = row.get('symbol')
            if not isinstance(symbol,str) or not symbol or symbol in seen:
                raise ValueError('quarantine_position_identity')
            seen.add(symbol)
            qty = self._number(row.get('qty'))
            if qty <= 0 or row.get('side','long') != 'long':
                raise ValueError('quarantine_position_unqualified')
            pos.append(dict(symbol=symbol, qty=str(qty), avg_entry_price=str(self._number(row.get('avg_entry_price')))))
        return dict(account_id=self.account_id, funds=funds,
                    positions=sorted(pos,key=lambda r:r['symbol']),
                    open_orders=self._q_orders(orders))

    def _q_orders(self, rows: list) -> list:
        result = []; seen = set()
        for row in rows:
            if (not isinstance(row,dict) or not isinstance(row.get('id'),str)
                    or not row['id'] or row['id'] in seen
                    or not isinstance(row.get('symbol'),str) or not row['symbol']
                    or any(not isinstance(row.get(k),str) or not row[k]
                           for k in ('client_order_id','type','time_in_force'))
                    or row.get('side') not in {'buy','sell'}):
                raise ValueError('quarantine_order_identity')
            seen.add(row['id'])
            qty, filled = self._number(row.get('qty')), self._number(row.get('filled_qty'))
            if qty<=0 or not 0<=filled<=qty or row.get('status') not in self._SELL_ACTIVE|self._SELL_TERMINAL|{'replaced','pending_replace'}:
                raise ValueError('quarantine_order_state')
            result.append({**{k:row.get(k) for k in ('id','client_order_id','symbol','side','status','type','time_in_force')},
                           'qty':str(qty),'filled_qty':str(filled)})
        return sorted(result,key=lambda r:r['id'])

    def _quarantine_snapshot(self, key: str, state: dict) -> dict:
        from stock_swing.sources.errors import SourceNotFoundError
        self._paper_quarantine_only()
        start = datetime.now(timezone.utc)
        first = self._q_view()
        try:
            self.broker.fetch_order_by_client_id(key)
        except SourceNotFoundError:
            pass  # Qualified observed lookup miss, NEVER a terminal outcome.
        else:
            raise ValueError('quarantined_order_now_visible')
        since = (self._q_time(self._prepared_at[key])-timedelta(minutes=5)).isoformat()
        history = self.broker.fetch(endpoint='v2/orders',status='all',direction='asc',after=since,limit=500).payload
        fills = self.broker.fetch(endpoint='v2/account/activities/FILL',direction='asc',after=since,page_size=100).payload
        if not isinstance(history,list) or len(history)>=500 or not isinstance(fills,list) or len(fills)>=100:
            raise ValueError('quarantine_history_incomplete')
        history = self._q_orders(history)
        if any(r['client_order_id']==key for r in history):
            raise ValueError('quarantined_order_in_history')
        symbol = state['order']['symbol']
        relevant_fills = [];seen = set()
        for row in fills:
            if (not isinstance(row,dict) or not isinstance(row.get('id'),str) or not row['id']
                    or row['id'] in seen or not isinstance(row.get('symbol'),str)
                    or row.get('side') not in {'buy','sell'}):
                raise ValueError('quarantine_fill_identity')
            seen.add(row['id'])
            if row['symbol']==symbol:
                qty,price=self._number(row.get('qty')),self._number(row.get('price'))
                if qty<=0 or price<=0 or not isinstance(row.get('order_id'),str) or not row['order_id']:
                    raise ValueError('quarantine_fill_invalid')
                self._q_time(row['transaction_time'])
                relevant_fills.append(dict(id=row['id'],order_id=row.get('order_id'),symbol=symbol,
                    side=row['side'],qty=str(qty),price=str(price),transaction_time=row.get('transaction_time')))
        second = self._q_view()
        end = datetime.now(timezone.utc)
        if first!=second or not 0<=(end-start).total_seconds()<=30:
            raise ValueError('quarantine_snapshot_changed_or_slow')
        if any(r['symbol']==symbol for r in first['positions']+first['open_orders']):
            raise ValueError('quarantined_symbol_exposure')
        symbol_orders=[r for r in history if r['symbol']==symbol]
        if any(r['side']=='buy' for r in symbol_orders+relevant_fills):
            raise ValueError('quarantined_symbol_buy_observed')
        return dict(schema_version=1,namespace=self.namespace,symbol=symbol,since=since,
            started_at=start.isoformat(),ended_at=end.isoformat(),view=first,
            symbol_orders=symbol_orders,symbol_fills=sorted(relevant_fills,key=lambda r:r['id']),
            lookup_status=404,history_complete=True,meaning='operator_quarantine_not_terminal_resolution')

    def _check_quarantine(self, payload: dict, state: dict, event_time: str) -> None:
        self._paper_quarantine_only()
        self._check_authority(payload.get('authority'))
        proof=payload.get('snapshot');order=state['order'];key=payload['client_order_id']
        if (order['side']!='buy' or order['time_in_force']!='day' or not isinstance(proof,dict)
                or proof.get('schema_version')!=1 or proof.get('namespace')!=self.namespace
                or proof.get('symbol')!=order['symbol'] or proof.get('lookup_status')!=404
                or proof.get('history_complete') is not True
                or proof.get('meaning')!='operator_quarantine_not_terminal_resolution'
                or proof['view']['account_id']!=self.account_id
                or proof['view']['positions'] or proof['view']['open_orders']):
            raise ValueError('quarantine_initial_proof_invalid')
        if (set(proof['view']['funds'])!={'cash','buying_power','non_marginable_buying_power'}
                or any(self._number(v)<0 for v in proof['view']['funds'].values())
                or proof.get('since')!=(self._q_time(self._prepared_at[key])-timedelta(minutes=5)).isoformat()
                or not isinstance(proof.get('symbol_orders'),list) or not isinstance(proof.get('symbol_fills'),list)
                or self._q_orders(proof['symbol_orders'])!=proof['symbol_orders']
                or any(r['symbol']!=order['symbol'] or r['side']=='buy' or r['client_order_id']==key
                       for r in proof['symbol_orders'])
                or any(r.get('symbol')!=order['symbol'] or r.get('side')!='sell'
                       or self._number(r.get('qty'))<=0 or self._number(r.get('price'))<=0
                       for r in proof['symbol_fills'])):
            raise ValueError('quarantine_initial_history_invalid')
        start,end,recorded=map(self._q_time,(proof['started_at'],proof['ended_at'],event_time))
        prepared=self._q_time(self._prepared_at[key])
        if (not 0<=(end-start).total_seconds()<=30 or not 0<=(recorded-end).total_seconds()<=30
                or prepared.astimezone(ZoneInfo('America/New_York')).date()>=start.astimezone(ZoneInfo('America/New_York')).date()):
            raise ValueError('quarantine_not_prior_session_or_stale')

    def qualify_quarantine(self, key: str, authority: dict, *, apply: bool=False,
                           expected_journal_sha256: str|None=None) -> dict:
        """Owner-directed Paper isolation, not a rejected/filled adjudication."""
        self._paper_quarantine_only();self._check_authority(authority)
        if not self.store.path.exists() or not self.marker.exists() or self.lock_path.is_symlink():
            raise ValueError('quarantine_existing_journal_required')
        with self.lock_path.open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            states=self._load();raw=self.store.path.read_bytes()
            if [k for k,s in states.items() if s['state'] in {'unknown','prepared'}]!=[key] or self.quarantines:
                raise ValueError('quarantine_single_unknown_required')
            if expected_journal_sha256 is not None and hashlib.sha256(raw).hexdigest()!=expected_journal_sha256:
                raise ValueError('quarantine_journal_cas')
            proof=self._quarantine_snapshot(key,states[key])
            payload=dict(client_order_id=key,authority=authority,snapshot=proof,
                         target_outcome_sha256=self._outcome_hashes.get(key))
            self._check_quarantine(payload,states[key],datetime.now(timezone.utc).isoformat())
            if self.store.path.read_bytes()!=raw:raise ValueError('quarantine_journal_changed')
            if apply:
                if expected_journal_sha256 is None:raise ValueError('quarantine_apply_requires_cas')
                self._append('submission_intent_quarantined',**payload)
                self._load()
            return dict(applied=apply,journal_sha256=hashlib.sha256(self.store.path.read_bytes()).hexdigest(),
                        snapshot=proof,original_outcome='unknown',blocked_symbol=states[key]['order']['symbol'])

    def quarantine_status(self) -> dict:
        """Read the explicit symbol hold before batch funding is reserved.

        Missing new-account history is absent, not initialized by this reader.
        An unavailable read never grants a bypass; submit_intent still validates.
        """
        if not self.store.path.exists() and not self.marker.exists():
            return dict(status='absent',symbols=[])
        try:
            if self.lock_path.is_symlink():raise ValueError('quarantine_lock_symlink')
            with self.lock_path.open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                self._load()
                symbols=sorted({q['snapshot']['symbol'] for q in self.quarantines.values()})
            return dict(status='active' if symbols else 'inactive',symbols=symbols)
        except Exception as exc:
            return dict(status='unavailable',symbols=[],error_type=type(exc).__name__)

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
                if any(q['snapshot']['symbol']==order['symbol'] for q in self.quarantines.values()):
                    raise SubmissionUncertain('operator_quarantine_symbol_held')
                previous_unknown = False
                for old_key, state in states.items():
                    if state["state"] in {"prepared", "unknown"}:
                        if old_key in self.quarantines:
                            if order['side']=='buy':
                                try:
                                    fresh=self._quarantine_snapshot(old_key,state)
                                except Exception as exc:
                                    code=str(exc) if (type(exc) is ValueError and str(exc).startswith(('quarantine_','quarantined_'))
                                        and str(exc).replace('_','').isalnum()) else type(exc).__name__
                                    raise SubmissionUncertain('operator_quarantine_recheck_failed:'+code) from exc
                                baseline=self.quarantines[old_key]['snapshot']
                                if any(fresh[k]!=baseline[k] for k in ('symbol_orders','symbol_fills')):
                                    raise SubmissionUncertain('quarantine_symbol_history_changed')
                            continue
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
