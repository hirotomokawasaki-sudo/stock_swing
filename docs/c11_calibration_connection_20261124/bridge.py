"""Read-only independent-journal -> existing C11/U calibration input bridge.

No strategy, price acquisition, path simulation, adopted U or outcome study.
The accepted comparison book and exposure-only selector remain unchanged.
"""
from dataclasses import asdict
from datetime import date
from decimal import Decimal, localcontext
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

PARENT = Path(__file__).resolve().parents[1] / 'c11_minimum_inputs_20261030'
ARMS = ('C11',) + tuple(f'U_grid_{k:03d}' for k in range(1, 101))
_PREP = None


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _hash(value):
    return hashlib.sha256(_encode(value)).hexdigest()


def _prepare():
    global _PREP
    if _PREP is None:
        spec = importlib.util.spec_from_file_location('_accepted_c11_prepare', PARENT/'prepare.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        _PREP = module
    _PREP.verify_sources()
    if Path(sys.modules['comparison_book'].__file__).resolve() != (PARENT/'code/comparison_book.py').resolve():
        raise ValueError('unaccepted accounting import')
    return _PREP


def connect(checkpoints, *, sessions, evaluation_first_session, source_ref):
    """Replay caller-supplied checkpoints and call the unmodified selector.

    Every arm needs the complete, append-only sequence on the same declared
    closing clocks. Declared calendar/source identities do not qualify prices,
    faithful C11/P0/Exit, ETF coverage or economic calibration.
    """
    m = _prepare()
    if not isinstance(source_ref, str) or not source_ref.strip():
        raise ValueError('explicit input source reference required')
    if not isinstance(checkpoints, dict) or set(checkpoints) != set(ARMS):
        raise ValueError('C11 and all 100 independent U paths required')
    if not isinstance(sessions, list) or not sessions:
        raise ValueError('explicit session close receipts required')
    evaluation = date.fromisoformat(evaluation_first_session)
    if evaluation.isoformat() != evaluation_first_session:
        raise ValueError('canonical evaluation date required')
    dates = []; clocks = []
    for row in sessions:
        if not isinstance(row, dict) or set(row) != {'session_date', 'close_at', 'calendar_source_ref'}:
            raise ValueError('complete declared close/calendar receipt required')
        day = date.fromisoformat(row['session_date']); at = m.clock(row['close_at'])
        if (day.isoformat() != row['session_date'] or day >= evaluation
                or at.astimezone(ZoneInfo('America/New_York')).date() != day
                or not isinstance(row['calendar_source_ref'], str) or not row['calendar_source_ref'].strip()):
            raise ValueError('session/date/evaluation/calendar binding required')
        dates.append(row['session_date']); clocks.append(at)
    if dates != sorted(set(dates)) or clocks != sorted(set(clocks)):
        raise ValueError('strictly ordered distinct pre-evaluation sessions required')
    exposure = {'dates': dates, 'C11': [], 'U_grid': {},
                'source_role': 'engineering_replay_of_explicit_journals:' + source_ref}
    common = None; lineage = {}; policies = {}; marks_by_session = [{} for _ in sessions]
    for arm in ARMS:
        texts = checkpoints[arm]
        if not isinstance(texts, list) or len(texts) != len(sessions):
            raise ValueError('every independent path needs all aligned checkpoints')
        previous_events = []; previous_close = None; own_policy = None; values = []; hashes = []
        for index, (text, close) in enumerate(zip(texts, clocks)):
            if not isinstance(text, str):
                raise ValueError('serialized journal required, not a snapshot or exposure proxy')
            raw = json.loads(text)
            book = m.ComparisonBook.loads(text); snapshot = book.snapshot(); p = asdict(book.policy)
            if _encode(raw['payload']['policy']) != _encode(p):
                raise ValueError('explicit complete policy required, not implicit defaults')
            if p['arm_id'] != arm or not isinstance(snapshot['as_of'], str) or m.clock(snapshot['as_of']) != close or snapshot['valuation_qualified'] is not True:
                raise ValueError('arm or close clock differs, or valuation is stale')
            if arm == 'C11':
                if p['atr_sizing'] is not True or p['semiconductor_cap'] != .30 or p['quantity_scale'] != 1:
                    raise ValueError('C11 must retain existing ATR P0/cap30/reduce-only identity')
            else:
                k = int(arm.rsplit('_', 1)[1])
                if p['atr_sizing'] is not False or p['semiconductor_cap'] is not None or Decimal(str(p['quantity_scale'])) != Decimal(k)/100:
                    raise ValueError('U must remain a uniform order multiplier, not a new exposure cap')
            identity = _encode({'policy': p, 'instruments': raw['payload']['instruments']})
            if own_policy is None: own_policy = identity
            if own_policy != identity:
                raise ValueError('path policy/universe changed inside calibration window')
            shared = _encode({'policy': {k:v for k,v in p.items() if k not in {'arm_id','quantity_scale','atr_sizing','semiconductor_cap'}},
                              'instruments': raw['payload']['instruments']})
            if common is None: common = shared
            if shared != common:
                raise ValueError('capital/cost/marks policy/instruments differ between arms')
            events = raw['payload']['events']
            if _encode(events[:len(previous_events)]) != _encode(previous_events):
                raise ValueError('journal reset or historical event rewrite')
            if previous_close is not None and any(m.clock(e['at']) <= previous_close for e in events[len(previous_events):]):
                raise ValueError('new event backdated into an exported session')
            previous_events = events; previous_close = close
            for symbol in {row['symbol'] for row in snapshot['lots'].values()}:
                mark = _encode(book.quotes[symbol]); observed = marks_by_session[index]
                if symbol in observed and observed[symbol] != mark:
                    raise ValueError('different marks for the same held asset/close')
                observed[symbol] = mark
            with localcontext() as ctx:
                ctx.prec = 50
                # Long-only mark-to-market gross exposure, not cash reservation.
                gross = sum((Decimal(str(v)) for v in snapshot['market_value_by_asset_class'].values()), Decimal(0))
                nav = Decimal(str(snapshot['equity']))
                if not nav.is_finite() or nav <= 0 or not gross.is_finite() or gross < 0:
                    raise ValueError('finite positive NAV and nonnegative gross required')
                value = float(gross/nav)
            if not math.isfinite(value):
                raise ValueError('nonfinite exposure')
            values.append(value); hashes.append(_hash(raw))
        if arm == 'C11': exposure['C11'] = values
        else: exposure['U_grid'][str(int(arm.rsplit('_', 1)[1]))] = values
        lineage[arm] = hashes; policies[arm] = hashlib.sha256(own_policy).hexdigest()
    # This accepted function only sees exposures/dates, never PnL or return.
    selected = m.calibration_port(exposure, evaluation_first_session)
    return {'schema': 'c11-journal-calibration-bridge-v1', 'exposure_inputs': exposure,
            'engineering_calibration': selected, 'formal_selected_scale': None,
            'checkpoint_hashes': lineage, 'policy_hashes': policies,
            'session_receipts_sha256': _hash(sessions),
            'bridge_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'accepted_selector_sha256': hashlib.sha256((PARENT/'prepare.py').read_bytes()).hexdigest(),
            'accepted_book_sha256': hashlib.sha256((PARENT/'code/comparison_book.py').read_bytes()).hexdigest(),
            'all_zero_exposure': all(v == 0 for v in exposure['C11']) and all(v == 0 for x in exposure['U_grid'].values() for v in x),
            'qualification': {'calendar_qualified': False, 'price_PIT_qualified': False,
                              'faithful_C11_entry_exit_qualified': False, 'economic_qualified': False,
                              'eligible_to_trade': False},
            'scope': 'read_only_engineering_connection_not_path_generation_or_formal_U'}
