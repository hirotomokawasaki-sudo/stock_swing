"""Engineering C11/U paths, reusing the sealed book and a frozen native Exit.

Explicit caller intents only; no signal/PF replay, market IO or trade authority.
Execution is restricted to an observed exact raw-price/zero-slip model. It is
not a claim that market orders fill at a limit or that real inputs qualify.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
import hashlib
import importlib
import importlib.util
import inspect
import json
import math
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent / 'c11_minimum_inputs_20261030'
ARMS = ('C11',) + tuple(f'U_grid_{i:03}' for i in range(1, 101))
MODEL = 'observed_exact_raw_price_zero_slippage_v1'


def encode(v):
    return json.dumps(v, sort_keys=True, separators=(',', ':'), allow_nan=False)


def aware(v):
    t = datetime.fromisoformat(v.replace('Z', '+00:00'))
    if t.utcoffset() is None:
        raise ValueError('aware clock required')
    return t.astimezone(timezone.utc)


def number(v, *, zero=False):
    if type(v) not in (int, float) or not math.isfinite(v) or (v < 0 if zero else v <= 0):
        raise ValueError('finite positive/nonnegative number required')
    return Decimal(str(v))


def core():
    path = PARENT / 'code/comparison_book.py'
    pin = json.loads((HERE/'SOURCE_PINS.json').read_text())
    expected = pin['docs/c11_minimum_inputs_20261030/code/comparison_book.py']['sha256']
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError('accepted book changed')
    name = '_c11_sealed_accounting'
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec); sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[name]


def native(source_root, pins):
    root = Path(source_root).resolve()
    if not pins:
        raise ValueError('explicit frozen native source pins required')
    for rel, digest in pins.items():
        p = root/'stock_swing'/rel
        if p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            raise ValueError('native source pin mismatch')
    for name, mod in tuple(sys.modules.items()):
        if name.startswith('stock_swing') and getattr(mod, '__file__', None):
            if not Path(mod.__file__).resolve().is_relative_to(root):
                raise ValueError('mixed native package origins')
    sys.path.insert(0, str(root))
    m = importlib.import_module('stock_swing.strategy_engine.simple_exit_v2_strategy')
    f = importlib.import_module('stock_swing.feature_engine.base_feature')
    for name, mod in tuple(sys.modules.items()):
        if name.startswith('stock_swing') and getattr(mod, '__file__', None):
            p = Path(mod.__file__).resolve()
            if not p.is_relative_to(root/'stock_swing') or str(p.relative_to(root/'stock_swing')) not in pins:
                raise ValueError('unpinned native import')
    # Native generate reads this one optional file relative to its frozen root.
    override = root.parent/'data/price_overrides.json'
    if not override.is_file() or json.loads(override.read_text()) != {'overrides': {}}:
        raise ValueError('explicit empty isolated override receipt required')
    return m, f.FeatureResult


def run(initial, frames, *, native_source_root, native_pins, exit_config,
        execution_model, source_ref):
    """Produce independent journals for bridge.connect; never adopt a U.

    All 101 per-arm requested quantities are explicit inputs, not actual-Paper
    gates copied to counterfactual books. The native entry/PF/guard decisions
    that would produce those intents are deliberately NOT certified here.
    """
    encode(frames); encode(exit_config)  # Reject non-finite or non-JSON input before events.
    if execution_model != MODEL or not isinstance(source_ref, str) or not source_ref.strip():
        raise ValueError('explicit supported model/source required')
    if set(initial) != set(ARMS) or not isinstance(frames, list) or not frames:
        raise ValueError('complete independent arms and nonempty frames required')
    c = core(); module, Feature = native(native_source_root, native_pins)
    fields = set(inspect.signature(module.SimpleExitV2Strategy).parameters)
    if set(exit_config) != fields:
        raise ValueError('complete explicit native Exit constructor policy required')
    for key, value in exit_config.items():
        if key.endswith('_enabled') and type(value) is not bool:
            raise ValueError('explicit boolean Exit switches required')
    for key in ('max_hold_days', 'min_hold_days'):
        if type(exit_config[key]) is not int or exit_config[key] < 0:
            raise ValueError('integer hold-day policy required')
    for key in ('stop_loss_pct', 'emergency_stop_bypass_pct'):
        if type(exit_config[key]) not in (int, float) or not -1 < exit_config[key] < 0:
            raise ValueError('negative fractional stop policy required')
    books = {arm: c.ComparisonBook.loads(initial[arm]) for arm in ARMS}
    first = books['C11']; universe = set(first.instruments)
    for arm, b in books.items():
        raw = json.loads(initial[arm])['payload']
        k = 1.0 if arm == 'C11' else float(Decimal(int(arm[-3:]))/100)
        if (raw['events'] or b.lots or b.pending or b.policy.arm_id != arm
                or encode(raw['policy']) != encode(asdict(b.policy))
                or b.policy.quantity_scale != k or b.policy.atr_sizing is not (arm == 'C11')
                or b.policy.semiconductor_cap != (.3 if arm == 'C11' else None)
                or b.policy.slippage_bps != 0):
            raise ValueError('explicit cash-only C11/U policy required; no overlay sizing')
        common = asdict(b.policy); base = asdict(first.policy)
        for x in ('arm_id', 'quantity_scale', 'atr_sizing', 'semiconductor_cap'):
            common.pop(x); base.pop(x)
        if common != base or b.instruments != first.instruments:
            raise ValueError('arm seed/cost/universe mismatch')
    states = {arm: {} for arm in ARMS}  # entry/peak metadata only; money stays in book
    checkpoints = {arm: [] for arm in ARMS}; sessions = []; audit = []; previous = None
    original_clock = module.datetime
    try:
        for i, frame in enumerate(frames):
            if set(frame) != {'at', 'quotes', 'features', 'entries', 'close'}:
                raise ValueError('frame schema differs')
            at = aware(frame['at'])
            if previous is not None and at <= previous:
                raise ValueError('ordered unique observation frames required')
            previous = at
            if set(frame['quotes']) != universe:
                raise ValueError('common quotes must cover the declared universe')
            for q in frame['quotes'].values():
                if set(q) != {'price', 'as_of', 'available_at'} or not aware(q['as_of']) <= aware(q['available_at']) <= at:
                    raise ValueError('causally available observed-price clock required')
                number(q['price'])
            features = []
            for x in frame['features']:
                if set(x) != {'symbol', 'computed_at', 'available_at', 'values', 'quality_flags', 'source_ref'}:
                    raise ValueError('explicit feature provenance required')
                if not aware(x['computed_at']) <= aware(x['available_at']) <= at or not x['source_ref'] or x['quality_flags']:
                    raise ValueError('future/unqualified feature')
                number(x['values']['atr'], zero=True); number(x['values']['latest_close'])
                features.append(Feature('price_momentum', x['symbol'], aware(x['computed_at']),
                                        deepcopy(x['values']), metadata={'available_at':x['available_at'], 'source_ref':x['source_ref']}, quality_flags=[]))
            if len(features) != len(universe) or {x.symbol for x in features} != universe:
                raise ValueError('full common feature universe required')
            fm = {x.symbol: x for x in features}
            class Clock(original_clock):
                @classmethod
                def now(cls, tz=None):
                    return at if tz is None else at.astimezone(tz)
            module.datetime = Clock  # clock input only; native decision code unchanged
            for arm, b in books.items():
                b.apply(dict(kind='mark', event_id=f'{i}:mark', at=frame['at'], quotes={s:{k:q[k] for k in ('price','as_of')} for s,q in frame['quotes'].items()}))
                strategy = module.SimpleExitV2Strategy(**deepcopy(exit_config))
                for lot_id, lot in list(b.lots.items()):
                    meta = states[arm][lot_id]; price = frame['quotes'][lot['symbol']]['price']
                    if meta['entry_price'] > price*3 or (meta['peak_price'] > meta['entry_price']*2.5 and meta['peak_price'] > price*2.5):
                        raise ValueError('corporate-action/peak ambiguity outside model')
                    position = dict(qty=lot['qty'], avg_entry_price=meta['entry_price'],
                                    current_price=price, peak_price=meta['peak_price'],
                                    created_at=lot['bought_at'], entry_signal_strength=meta['strength'])
                    signals = strategy.generate(deepcopy(features), {lot['symbol']: position})
                    meta['peak_price'] = max(meta['peak_price'], price)
                    if signals:
                        if len(signals) != 1 or signals[0].metadata['current_price'] != price:
                            raise ValueError('native price fallback outside exact-price model')
                        b.apply(dict(kind='sell', event_id=f'{i}:exit:{lot_id}', at=frame['at'],
                                     lot_id=lot_id, qty=lot['qty'], raw_price=price))
                        audit.append(dict(frame=i, arm=arm, kind='native_exit', lot_id=lot_id,
                                          trigger=signals[0].metadata['exit_trigger']))
                        del states[arm][lot_id]
                for n, intent in enumerate(frame['entries']):
                    if set(intent) != {'symbol', 'requested_qty', 'strength', 'available_at', 'source_ref'}:
                        raise ValueError('explicit intent schema required')
                    if set(intent['requested_qty']) != set(ARMS) or aware(intent['available_at']) > at or not intent['source_ref']:
                        raise ValueError('complete per-arm causal intents required')
                    qty = intent['requested_qty'][arm]; strength = intent['strength']
                    if type(qty) is not int or qty < 0 or number(strength, zero=True) > 1:
                        raise ValueError('invalid quantity/strength')
                    symbol = intent['symbol']
                    if symbol not in universe:
                        raise ValueError('intent outside declared universe')
                    price = frame['quotes'][symbol]['price']
                    if not qty or any(x['symbol'] == symbol for x in b.lots.values()):
                        audit.append(dict(frame=i, arm=arm, kind='no_entry_or_already_held', symbol=symbol)); continue
                    atr = fm[symbol].values['atr']
                    if arm == 'C11' and number(atr, zero=True) == 0:
                        raise ValueError('sealed book does not support zero ATR; do not fabricate it')
                    planned = int(Decimal(qty)*Decimal(str(b.policy.quantity_scale)))
                    if arm == 'C11':
                        width = max(2*Decimal(str(atr)), Decimal(str(price))*Decimal('.05'))
                        planned = min(planned, int((Decimal(str(b.policy.baseline_equity))*Decimal('.003')/width).to_integral_value(rounding=ROUND_FLOOR)))
                    unit = Decimal(str(price))*(1+Decimal(str(b.policy.fee_bps))/10000)
                    affordable = int((Decimal(str(b.cash-b._reserved_cash()))/unit).to_integral_value(rounding=ROUND_FLOOR))
                    expected = min(planned, affordable)
                    if expected <= 0:
                        audit.append(dict(frame=i, arm=arm, kind='quantity_or_cash_zero', symbol=symbol)); continue
                    order_id = f'{i}:{n}:{arm}'
                    event = dict(kind='reserve', event_id=f'{order_id}:reserve', at=frame['at'],
                                 order_id=order_id, symbol=symbol, qty=qty, max_fill_price=price,
                                 atr=atr, atr_available_at=fm[symbol].metadata['available_at'])
                    try:
                        receipt = b.apply(event)
                    except ValueError as exc:
                        if str(exc) != 'projected semiconductor cap':
                            raise
                        audit.append(dict(frame=i, arm=arm, kind='cap_rejected', symbol=symbol)); continue
                    if receipt['qty'] != expected:
                        raise ValueError('sealed-book numeric sizing differs from Decimal contract')
                    fill = b.apply(dict(kind='fill', event_id=f'{order_id}:fill', at=frame['at'],
                                        order_id=order_id, qty=receipt['qty'], raw_price=price))
                    states[arm][fill['lot_id']] = dict(entry_price=price, peak_price=price, strength=strength)
                    audit.append(dict(frame=i, arm=arm, kind='entry', symbol=symbol, qty=receipt['qty']))
            if frame['close'] is not None:
                close = frame['close']
                if set(close) != {'session_date', 'close_at', 'calendar_source_ref'} or aware(close['close_at']) != at:
                    raise ValueError('explicit same-clock close/calendar receipt required')
                sessions.append(deepcopy(close))
                for arm, b in books.items():
                    checkpoints[arm].append(b.dumps())
    finally:
        module.datetime = original_clock
    if not sessions:
        raise ValueError('at least one explicit session close is required')
    return dict(native_source_sha256=hashlib.sha256(encode(native_pins).encode()).hexdigest(),
                exit_policy_sha256=hashlib.sha256(encode(exit_config).encode()).hexdigest(),
                checkpoints=checkpoints, sessions=sessions, audit=audit,
                execution_model=MODEL, source_ref=source_ref,
                quantity_scope='P0 equals sealed bound only at exact observed raw entry, zero slip, nonzero ATR; mismatch refused',
                entry_gate_scope='caller per-arm intents, not native entry/PF/guard replay',
                exit_scope='frozen native SimpleExitV2, independent entry/peak per lot',
                economic_qualified=False, full_strategy_replay_qualified=False,
                formal_U=None, market_PnL=None)
