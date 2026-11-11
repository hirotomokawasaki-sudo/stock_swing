"""Strict, offline order-completion FIFO, with confirmed noncash split evidence.

This is a post-hoc accounting reconstruction, NOT an execution-level or PIT
backtest. Completion VWAP cannot identify interleaved individual executions.
Date-only splits are placed before that UTC day's orders; availability is kept
separately. A missing lot/evidence is an error, never a future buy or market-price
estimate. Fractional-share accounting is deliberately unsupported.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from .execution_cost import decimal_value, whole_quantity


def utc_time(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError('timezone required')
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError('invalid/naive evidence timestamp') from exc


def day_time(value):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError('date must be YYYY-MM-DD')
        return datetime(parsed.year, parsed.month, parsed.day, tzinfo=timezone.utc)
    except (ValueError, TypeError) as exc:
        raise ValueError('invalid effective date') from exc


def _identity(*parts):
    return hashlib.sha256(json.dumps(parts, separators=(',', ':')).encode()).hexdigest()[:24]


def _confirmed_splits(activities, overrides):
    groups, seen = defaultdict(list), set()
    for row in activities:
        if row.get('activity_type') != 'SPLIT':
            continue
        if any(not row.get(k) for k in ('id', 'symbol', 'group_id', 'corporate_action_id')):
            raise ValueError('missing split identity')
        if row['id'] in seen:
            raise ValueError('duplicate split activity')
        seen.add(row['id'])
        groups[row['group_id']].append(row)
    if set(overrides) - set(groups):
        raise ValueError('unknown split date override group')
    confirmed = []
    for group, rows in groups.items():
        if len(rows) != 2:
            raise ValueError('confirmed split evidence requires remove/add pair')
        for key in ('symbol', 'date', 'corporate_action_id', 'activity_sub_type'):
            if len({r.get(key) for r in rows}) != 1:
                raise ValueError('conflicting split identity/date/subtype')
        if rows[0].get('activity_sub_type') not in {'FSPLIT', 'RSPLIT'}:
            raise ValueError('unsupported split subtype')
        if any(r.get('status') != 'executed' or decimal_value(r.get('net_amount'), 'net amount', positive=False) != 0 for r in rows):
            raise ValueError('split must be executed and noncash')
        instant = day_time(rows[0].get('date'))
        available = max(utc_time(r.get('created_at')) for r in rows)
        try:
            qty = [Decimal(str(r.get('qty'))) for r in rows]
        except InvalidOperation as exc:
            raise ValueError('invalid split quantity') from exc
        if any(not q.is_finite() or not q for q in qty) or not (min(qty) < 0 < max(qty)):
            raise ValueError('split pair quantity sign ambiguity')
        removed = whole_quantity(-min(qty), 'removed quantity')
        added = whole_quantity(max(qty), 'added quantity')
        ratio = Decimal(added) / removed
        if (rows[0]['activity_sub_type'] == 'FSPLIT' and ratio <= 1) or (rows[0]['activity_sub_type'] == 'RSPLIT' and ratio >= 1):
            raise ValueError('split subtype/ratio conflict')
        registry_date = overrides.get(group, rows[0]['date'])
        day_time(registry_date)
        confirmed.append(dict(symbol=rows[0]['symbol'], group_id=group,
            corporate_action_id=rows[0]['corporate_action_id'], effective_date=rows[0]['date'],
            registry_ex_date=registry_date, effective_time_precision='date',
            effective_ordering='before_orders_on_UTC_effective_date',
            available_at=available.isoformat(), activity_ids=sorted(r['id'] for r in rows),
            removed_qty=removed, added_qty=added, ratio=str(ratio), instant=instant))
    return confirmed


def match_order_completion_fifo(filled_orders, corporate_actions=None, *, split_activities=None, split_date_overrides=None):
    timeline, seen, at_time = [], set(), defaultdict(set)
    for row in filled_orders:
        if not row.get('id') or not row.get('symbol') or row.get('side') not in {'buy', 'sell'}:
            raise ValueError('missing/unsupported order identity')
        if row['id'] in seen:
            raise ValueError('duplicate order observation')
        seen.add(row['id'])
        instant = utc_time(row.get('filled_at'))
        lot = dict(symbol=row['symbol'], side=row['side'], order_id=row['id'],
                   qty=whole_quantity(row.get('filled_qty'), 'filled quantity'),
                   price=decimal_value(row.get('filled_avg_price'), 'order VWAP'),
                   time=instant.isoformat(), adjustments=[])
        at_time[(row['symbol'], instant)].add(row['side'])
        timeline.append((instant, 1, row['id'], 'order', lot))
    if any(len(sides) > 1 for sides in at_time.values()):
        raise ValueError('ambiguous same-instant opposite orders; individual executions required')

    splits = _confirmed_splits(split_activities or [], split_date_overrides or {})
    for split in splits:
        timeline.append((split['instant'], 0, split['group_id'], 'split', split))
    horizon = max((t[0] for t in timeline), default=None)
    registry_seen = set()
    matched_overrides = set()
    for action in corporate_actions or []:
        if action.get('type') != 'split':
            continue
        symbol, ex_date = action.get('symbol'), action.get('ex_date')
        instant = day_time(ex_date)
        ratio = decimal_value(action.get('ratio'), 'registry split ratio')
        key = (symbol, ex_date)
        if key in registry_seen:
            raise ValueError('duplicate registry split')
        registry_seen.add(key)
        matches = [s for s in splits if (s['symbol'], s['registry_ex_date']) == key and Decimal(s['ratio']) == ratio]
        if len(matches) > 1:
            raise ValueError('ambiguous registry split match')
        if matches:
            matched_overrides.add(matches[0]['group_id'])
        elif horizon is not None and instant <= horizon:
            timeline.append((instant, -1, str(key), 'unconfirmed', dict(symbol=symbol)))
    if set(split_date_overrides or {}) - matched_overrides:
        raise ValueError('split date override has no exact registry symbol/date/ratio match')

    lots, closed = defaultdict(deque), []
    for _, _, identity, kind, event in sorted(timeline, key=lambda t: t[:3]):
        inventory = lots[event['symbol']]
        if kind == 'unconfirmed':
            if inventory:
                raise ValueError('missing confirmed split evidence for held inventory')
            continue
        if kind == 'split':
            if sum(lot['qty'] for lot in inventory) != event['removed_qty']:
                raise ValueError('split inventory does not match broker removal')
            ratio = Decimal(event['ratio'])
            cost_before = sum(lot['qty'] * lot['price'] for lot in inventory)
            adjustment = {k: v for k, v in event.items() if k != 'instant'}
            adjustment['preserved_cost'] = str(cost_before)
            for lot in inventory:
                lot['qty'] = whole_quantity(lot['qty'] * ratio, 'split lot quantity')
                lot['price'] /= ratio
                lot['adjustments'] = lot['adjustments'] + [adjustment]
            if abs(sum(lot['qty'] * lot['price'] for lot in inventory) - cost_before) > Decimal('.00000001'):
                raise ValueError('split cost conservation failed')
            continue
        if event['side'] == 'buy':
            inventory.append(event)
            continue
        remaining = event['qty']
        if sum(lot['qty'] for lot in inventory) < remaining:
            raise ValueError('sell exceeds known earlier inventory; individual executions/history required')
        while remaining:
            lot = inventory[0]
            qty = min(lot['qty'], remaining)
            closed.append(_trade(lot, qty, event))
            lot['qty'] -= qty
            remaining -= qty
            if not lot['qty']:
                inventory.popleft()
    opened = [_trade(lot, lot['qty']) for symbol in sorted(lots) for lot in lots[symbol]]
    return closed, opened


def _trade(lot, qty, sell=None):
    closed = sell is not None
    identity = _identity(lot['order_id'], sell['order_id'] if closed else None)
    pnl = qty * (sell['price'] - lot['price']) if closed else None
    return dict(trade_id=('broker_match_' if closed else 'broker_open_') + identity,
        symbol=lot['symbol'], strategy_id='broker_reconstructed', side='buy', qty=qty,
        entry_price=float(lot['price']), exit_price=float(sell['price']) if closed else None,
        entry_time=lot['time'], exit_time=sell['time'] if closed else None,
        pnl=float(pnl.quantize(Decimal('.01'))) if closed else None,
        return_pct=float((sell['price'] - lot['price']) / lot['price']) if closed else None,
        status='closed' if closed else 'open', account_id=None,
        strategy_version_id='broker_reconstructed', broker_order_id=lot['order_id'],
        exit_broker_order_id=sell['order_id'] if closed else None,
        execution_leg_id='broker_leg_' + identity if closed else None,
        original_strategy_id='broker_reconstructed',
        exit_strategy_id='broker_reconstructed' if closed else None,
        exit_reason='broker_fill' if closed else None,
        corporate_action_adjustments=lot['adjustments'])
