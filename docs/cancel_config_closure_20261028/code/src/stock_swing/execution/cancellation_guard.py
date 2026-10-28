"""One cancel request per broker order, with qualified terminal readback.

Only cooperating paper callers share the submission lock. No replace, retry,
fill accounting, snapshot atomicity or global exactly-once guarantee.
"""
from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from stock_swing.core.runtime import read_runtime_mode
from stock_swing.tracking.trade_event_store import TradeEvent, TradeEventStore

OPEN = {'new', 'accepted', 'pending_new', 'partially_filled', 'pending_cancel',
        'held', 'accepted_for_bidding'}
TERMINAL = {'canceled', 'expired', 'rejected', 'filled'}
IDENTITY = ('id', 'symbol', 'side', 'type', 'time_in_force')


def _payload(value):
    return value.payload if hasattr(value, 'payload') else value


def _number(value):
    if value is None or isinstance(value, bool):
        raise ValueError('quantity_missing')
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('quantity_nonfinite')
    return result


def _qualified(raw, expected=None):
    if not isinstance(raw, dict) or any(not isinstance(raw.get(k), str) or not raw[k] for k in IDENTITY):
        raise ValueError('order_identity_unqualified')
    if raw['side'] not in {'buy', 'sell'} or raw['status'] not in OPEN | TERMINAL:
        raise ValueError('order_state_unqualified')
    if raw.get('legs') or raw.get('order_class') not in (None, '', 'simple'):
        raise ValueError('complex_order_unqualified')
    qty, filled = _number(raw.get('qty')), _number(raw.get('filled_qty'))
    if qty <= 0 or not 0 <= filled <= qty or (raw['status'] == 'filled' and filled != qty):
        raise ValueError('order_quantity_unqualified')
    if expected is not None:
        if any(raw[k] != expected[k] for k in IDENTITY) or qty != _number(expected['qty']) or filled < _number(expected['filled_qty']):
            raise ValueError('order_readback_mismatch')
    return {**{k: raw[k] for k in IDENTITY}, 'qty': str(qty),
            'filled_qty': str(filled), 'status': raw['status']}


class _Journal:
    def __init__(self, guard):
        self.guard = guard
        root = guard.store.path.parents[3]
        for rel in ['data', 'data/tracking', 'data/tracking/cancel_intents']:
            if (root / rel).is_symlink():
                raise ValueError('cancel_directory_symlink')
        self.store = TradeEventStore(root, f'data/tracking/cancel_intents/{guard.namespace}.jsonl')
        self.marker = self.store.path.with_suffix('.initialized')

    def append(self, kind, **payload):
        self.store.append(TradeEvent.create(kind, payload=dict(namespace=self.guard.namespace, **payload)))

    def load(self, initialize=False):
        path = self.store.path
        if path.is_symlink() or self.marker.is_symlink():
            raise ValueError('cancel_file_symlink')
        if not path.exists() and not self.marker.exists():
            if not initialize:
                return {}
            self.append('cancel_initialized')
            with self.marker.open('x') as stream:
                stream.write(self.guard.namespace+'\n'); stream.flush(); os.fsync(stream.fileno())
        if not path.exists() or not self.marker.exists() or self.marker.read_text() != self.guard.namespace+'\n':
            raise ValueError('cancel_initialization_missing')
        raw = path.read_bytes()
        if not raw.endswith(b'\n'):
            raise ValueError('cancel_history_partial')
        states = {}
        for index, line in enumerate(raw.decode().splitlines()):
            event = TradeEvent(**json.loads(line)); payload = event.payload
            if datetime.fromisoformat(event.created_at).tzinfo is None or payload.get('namespace') != self.guard.namespace:
                raise ValueError('cancel_history_provenance')
            if index == 0:
                if event.event_type != 'cancel_initialized':
                    raise ValueError('cancel_initialization_invalid')
                continue
            key = payload.get('order_id')
            if not isinstance(key, str) or not key:
                raise ValueError('cancel_identity_invalid')
            if event.event_type == 'cancel_prepared':
                if key in states:
                    raise ValueError('cancel_duplicate_prepare')
                snapshot = _qualified(payload.get('order'))
                if key != snapshot['id']:
                    raise ValueError('cancel_identity_mismatch')
                states[key] = dict(order=snapshot, state='prepared')
            elif event.event_type == 'cancel_invalidated':
                if key not in states or states[key]['state'] != 'terminal' or payload.get('reason') != 'terminal_readback_changed':
                    raise ValueError('cancel_invalidation_invalid')
                states[key]['state'] = 'unknown'
            elif event.event_type == 'cancel_observed':
                if key not in states or states[key]['state'] == 'terminal' or payload.get('state') not in {'requested','unknown','terminal'}:
                    raise ValueError('cancel_transition_invalid')
                previous = states[key]['order']; observed = payload.get('order')
                if observed is not None:
                    observed = _qualified(observed, previous)
                if (payload['state']=='terminal') != bool(observed and observed['status'] in TERMINAL):
                    raise ValueError('cancel_terminal_without_evidence')
                states[key] = dict(order=observed or previous, state=payload['state'])
            else:
                raise ValueError('cancel_event_unknown')
        return states


def pending_cancellations(guard) -> list[dict[str, Any]]:
    """Read under the existing account-route lock; corrupt history refuses send."""
    return [v for v in _Journal(guard).load().values() if v['state'] != 'terminal']


def cancel_order_safely(broker, project_root: Path, expected: dict) -> dict:
    """Cancel only after a durable prepare; retry means readback, never DELETE."""
    result = dict(order_id=expected.get('id') if isinstance(expected,dict) else None,
                  state='held', broker_status=None, cancelled=False,
                  filled_qty=None, reason='unqualified', delete_attempted=False)
    attempted = False
    try:
        from stock_swing.execution.submission_guard import SubmissionGuard
        if read_runtime_mode(project_root) != 'paper' or getattr(broker,'paper_mode',None) is not True or urlsplit(broker.base_url).hostname == 'api.alpaca.markets':
            raise ValueError('paper_runtime_required')
        expected = _qualified(expected)
        for rel in ['data','data/tracking','data/tracking/submission_intents']:
            if (project_root/rel).is_symlink():raise ValueError('journal_directory_symlink')
        account = _payload(broker.fetch_account())
        if not isinstance(account,dict) or account.get('status')!='ACTIVE' or account.get('trading_blocked') not in (None,False) or account.get('account_blocked') not in (None,False):
            raise ValueError('account_unqualified')
        guard = SubmissionGuard(broker,project_root,account.get('id'))
        if not guard.qualified or guard.lock_path.is_symlink():raise ValueError('account_or_lock_unqualified')
        with guard.lock_path.open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                result['reason']='submission_guard_busy'; return result
            journal = _Journal(guard); states = journal.load(initialize=True)
            prior = states.get(expected['id'])
            reference = prior['order'] if prior else expected
            if prior:
                _qualified(expected, {**reference, 'filled_qty':expected['filled_qty']})
            try:observed = _qualified(_payload(broker.fetch_order(expected['id'])), reference)
            except Exception:
                result.update(state='unknown' if prior else 'held',reason='order_readback_unavailable');return result
            if prior and prior['state']=='terminal':
                if observed['status'] != reference['status'] or observed['filled_qty'] != reference['filled_qty']:
                    journal.append('cancel_invalidated',order_id=expected['id'],reason='terminal_readback_changed')
                    result.update(state='unknown',reason='terminal_readback_changed');return result
            elif not prior:
                journal.append('cancel_prepared',order_id=expected['id'],order=observed)
            if observed['status'] in TERMINAL:
                state='terminal'
            elif prior:
                state='unknown' if prior['state'] in {'prepared','unknown'} else 'requested'
            else:
                # Never resend pending_cancel already observed at the broker.
                failed=False
                if observed['status']!='pending_cancel':
                    attempted=True;result['delete_attempted']=True
                    try:broker.cancel_order(expected['id'])
                    except Exception:failed=True
                try:observed = _qualified(_payload(broker.fetch_order(expected['id'])), observed)
                except Exception:observed=None
                state='terminal' if observed and observed['status'] in TERMINAL else 'unknown' if failed or observed is None else 'requested'
            if not prior or prior['state']!='terminal':
                journal.append('cancel_observed',order_id=expected['id'],state=state,order=observed)
            result.update(state=state, broker_status=observed['status'] if observed else None,
                          filled_qty=observed['filled_qty'] if observed else None,
                          cancelled=bool(state=='terminal' and observed['status']=='canceled'),
                          reason='qualified_readback_not_fill_accounting' if state=='terminal' else 'cancel_not_terminal_reservation_retained')
            return result
    except Exception as exc:
        result.update(state='unknown' if attempted else 'held',reason='cancel_unavailable:'+type(exc).__name__)
        return result
