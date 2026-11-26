"""Explicit-policy native entry components for independent C11/U books.

No accounting owner, IO client, actual-account history or environment defaults.
The accepted guard adapter is supplied as a pinned, read-only dependency.
"""
from copy import deepcopy
from dataclasses import asdict, fields
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import path_driver as base


class NativeEntries:
    def __init__(self, policy, *, guard_source, guard_sha256):
        from stock_swing.strategy_engine import breakout_momentum_strategy as generation
        from stock_swing.decision_engine.decision_engine import DecisionEngine
        from stock_swing.decision_engine.risk_validator import RiskValidator
        from stock_swing.risk.entry_filter import EntryFilterConfig, EntryFilterEngine
        from stock_swing.risk import position_sizing as sizing
        from stock_swing.risk.allocation_config import AllocationConfig
        from stock_swing.core.runtime import RuntimeMode
        from stock_swing.feature_engine.base_feature import FeatureResult
        from stock_swing.guardrails.rule_engine import GuardAction

        base.encode(policy)
        if set(policy) != {'generation', 'risk', 'filter', 'sizing', 'allocation', 'guard',
                           'confidence_risk_budget_fix_enabled', 'quarantined_symbols'}:
            raise ValueError('complete native component policy required')
        if set(policy['generation']) != {'min_momentum', 'min_signal_strength'}:
            raise ValueError('explicit common generation policy required')
        if set(policy['risk']) != {'min_signal_strength', 'min_confidence', 'max_position_size'}:
            raise ValueError('explicit native risk policy required')
        if set(policy['filter']) != {f.name for f in fields(EntryFilterConfig)}:
            raise ValueError('complete entry filter policy required')
        if policy['filter']['disabled'] is not False:
            raise ValueError('entry filter must remain enabled')
        if (not isinstance(policy['guard'],dict) or not isinstance(policy['guard'].get('rules'),dict)
                or type(policy['guard'].get('paper_warning_only')) is not bool):
            raise ValueError('explicit native guard policy mapping required')
        if set(policy['allocation']) != {f.name for f in fields(AllocationConfig)}:
            raise ValueError('complete allocation policy required, no file fallback')
        dynamic = {'account_equity', 'current_price', 'current_total_exposure', 'symbol',
                   'asset_class', 'current_sector_exposure', 'confidence'}
        if set(policy['sizing']) != {f.name for f in fields(sizing.PositionSizingInputs)} - dynamic:
            raise ValueError('all non-derived sizing inputs required')
        if policy['sizing']['risk_per_share'] is not None:
            raise ValueError('ATR transform belongs to C11 book, not nominal sizing')
        flag = policy['confidence_risk_budget_fix_enabled']
        if type(flag) is not bool or flag != sizing.SIZING_CONFIDENCE_MULTIPLIER_RISK_BUDGET_FIX_ENABLED:
            raise ValueError('native feature flag differs from explicit policy')
        if (not isinstance(policy['quarantined_symbols'], list)
                or 'ANET' not in policy['quarantined_symbols']):
            raise ValueError('explicit ANET quarantine required')
        for v in policy['generation'].values():
            if base.number(v, zero=True) > 1:
                raise ValueError('invalid generation threshold')
        path = Path(guard_source)
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != guard_sha256:
            raise ValueError('accepted guard dependency changed')
        spec = importlib.util.spec_from_file_location('_accepted_c11_guard', path)
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        self.policy = deepcopy(policy)
        # Immutable capture stores IntEnum values as JSON integers; the existing
        # YAML loader expects enum names. Preserve the caller/source receipt and
        # normalize only this typed boundary, with no unknown-action fallback.
        self.guard_policy = deepcopy(policy['guard'])
        for rule in self.guard_policy['rules'].values():
            action=rule['action']
            if type(action) is int:
                rule['action']=GuardAction(action).name
            elif type(action) is not str or action not in GuardAction.__members__:
                raise ValueError('unknown captured guard action')
            if type(rule.get('enabled')) is not bool:
                raise ValueError('explicit guard rule enabled flag required')
        self.generation, self.Feature = generation, FeatureResult
        self.DecisionEngine, self.RiskValidator, self.RuntimeMode = DecisionEngine, RiskValidator, RuntimeMode
        self.FilterConfig, self.Filter = EntryFilterConfig, EntryFilterEngine
        self.sizing, self.allocation = sizing, AllocationConfig(**policy['allocation'])
        self.guard = guard.evaluate_book_guard
        self.guard_sha256 = guard_sha256

    def candidates(self, frame, universe):
        """Generate once from common features; book-dependent gates run per arm."""
        at = base.aware(frame['at']); features = []; identities = set()
        for f in frame['features']:
            required = {'feature_name', 'symbol', 'computed_at', 'available_at', 'values',
                        'metadata', 'quality_flags', 'source_ref'}
            if (set(f) != required or not isinstance(f['source_ref'], str) or not f['source_ref']
                    or not base.aware(f['computed_at']) <= base.aware(f['available_at']) <= at):
                raise ValueError('causally available complete feature receipt required')
            key = (f['feature_name'], f['symbol'])
            if key in identities:
                raise ValueError('duplicate feature identity')
            identities.add(key)
            features.append(self.Feature(f['feature_name'], f['symbol'], base.aware(f['computed_at']),
                                         deepcopy(f['values']), deepcopy(f['metadata']), deepcopy(f['quality_flags'])))
        if {f.symbol for f in features if f.feature_name == 'price_momentum'} != set(universe):
            raise ValueError('declared price-feature universe must not be silently reduced')
        original = self.generation.datetime
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return at.astimezone(tz) if tz else at.replace(tzinfo=None)
        self.generation.datetime = Clock
        try:
            etfs = {s for s, i in universe.items() if i.asset_class == 'etf'}
            return self.generation.BreakoutMomentumStrategy(**self.policy['generation'], etf_symbols=etfs).generate(features)
        finally:
            self.generation.datetime = original

    def evaluate(self, *, state, frame, candidate, quote):
        """Return native nominal shares; never reserve, multiply U, or apply ATR."""
        b = state['book']; symbol = candidate.symbol; now = base.aware(frame['at'])
        cfg = self.policy['filter'] if frame['filter_policy'] is None else frame['filter_policy']
        if set(cfg) != set(self.policy['filter']) or cfg['disabled'] is not False:
            raise ValueError('complete enabled source filter policy required')
        cfg_hash = hashlib.sha256(base.encode(cfg).encode()).hexdigest()
        def held(reason, **kw):
            return dict(status='held', reason=reason, symbol=symbol,filter_policy_sha256=cfg_hash, **kw)
        if symbol in self.policy['quarantined_symbols']:
            return held('quarantined_symbol')
        if frame['exit_only']:
            return held('exit_only')
        if any(x['symbol'] == symbol for x in list(b.lots.values()) + list(b.pending.values())):
            return held('existing_holding_or_pending')
        if b.instruments[symbol].semiconductor_fraction is None:
            return held('unknown_look_through_fraction')
        if quote is None:
            return held('missing_execution_quote')
        positions = {s:sum(x['qty'] for x in b.lots.values() if x['symbol'] == s) for s in b.instruments}
        # Replay the native PAPER decision component, without any executor.
        # RESEARCH deliberately changes actionable decisions to hold; using it
        # here would test that suppression rather than the existing strategy.
        decision = self.DecisionEngine(runtime_mode=self.RuntimeMode.PAPER,
            risk_validator=self.RiskValidator(**self.policy['risk'])).process(candidate, current_positions=positions)
        if decision.action != 'buy':
            return held('native_risk', details=deepcopy(decision.deny_reasons))
        records = {}
        for s, bars in frame['bars'].items():
            records[s] = []
            for bar in bars:
                if (bar['symbol'] != s or bar['event_type'] != 'bar_daily'
                        or not base.aware(bar['event_time']) <= base.aware(bar['ingested_at']) <= now):
                    raise ValueError('available daily bar evidence required')
                records[s].append(SimpleNamespace(**deepcopy(bar)))
        filtered = self.Filter(self.FilterConfig(**deepcopy(cfg))).filter(
            [decision], records, deepcopy(state['history']),
            {s for s,i in b.instruments.items() if i.asset_class == 'etf'})
        if not filtered.passed:
            return held('native_entry_filter', details=deepcopy(filtered.blocked))
        context = frame['operational'].get(b.policy.arm_id)
        anchor = state.get('day_anchor')
        if context is None or anchor is None or anchor['date'] != now.date().isoformat():
            return held('unqualified_guard_context')
        if (set(context) != {'role', 'source_ref', 'as_of', 'available_at', 'metrics', 'breaker', 'dynamic_exposure_cap'}
                or context['role'] not in {'explicit_model_assumptions', 'observed_source_bound'}
                or not context['source_ref']
                or not base.aware(context['as_of']) <= base.aware(context['available_at']) <= now):
            raise ValueError('explicit operational provenance required')
        guard_context = dict(arm_id=b.policy.arm_id, as_of=context['as_of'],
            day_start_date=anchor['date'], day_start_unrealized=anchor['unrealized'],
            operational_metrics=deepcopy(context['metrics']), breaker=deepcopy(context['breaker']),
            dynamic_exposure_cap=context['dynamic_exposure_cap'])
        guard = self.guard(state, arm_id=b.policy.arm_id, now=now, symbol=symbol,
                           context=guard_context, policy=deepcopy(self.guard_policy))
        state['guard_halt_latched'] = guard['halt_latched']
        if not guard['allowed']:
            return held('native_prebuy_guard', guard=guard)
        sector = self.sizing.SYMBOL_SECTORS.get(symbol)
        if sector is None:
            return held('unknown_native_sector')
        exposures = [(x['symbol'],x['qty']*b._mark(x['symbol'],now,fresh=True)) for x in b.lots.values()]
        exposures += [(x['symbol'],x['qty']*x['max_fill_price']) for x in b.pending.values()]
        settings = deepcopy(self.policy['sizing'])
        cap = guard['effective_exposure_cap']
        if settings['exposure_cap_override'] is None or settings['exposure_cap_override'] > cap:
            settings['exposure_cap_override'] = cap
        inputs = self.sizing.PositionSizingInputs(account_equity=b._equity(now,fresh=True),
            current_price=quote['ask'], current_total_exposure=sum(v for _,v in exposures),
            current_sector_exposure=sum(v for s,v in exposures if self.sizing.SYMBOL_SECTORS.get(s)==sector),
            symbol=symbol, asset_class=b.instruments[symbol].asset_class, confidence=candidate.confidence, **settings)
        sized = self.sizing.PositionSizingPolicy(self.allocation).size(inputs)
        return dict(status='nominal_ready' if sized.final_shares>0 else 'held', reason='native_nominal_sizing',
            symbol=symbol, nominal_qty=sized.final_shares, sizing=asdict(sized), guard=guard,
            operational_role=context['role'], signal_strength=candidate.signal_strength,
            strategy_id=candidate.strategy_id, own_history_count=len(state['history']),filter_policy_sha256=cfg_hash)
