"""Requested-universe accounting on the existing opt-in input recorder.

These are observations, not eligibility rules or a full-replay certificate.
No fetching, strategy recomputation, empty-history substitution or new store.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib

from .decision_input_capture import capture_value, load_input_run
from .measurement_capture import CaptureError

BLOCKING = {'stale_data', 'insufficient_bars', 'insufficient_price_data'}


class CandidateInputCapture:
    def __init__(self, recorder, symbols, *, arguments):
        self.recorder = recorder
        self.symbols = list(symbols)
        self.fetches = {}
        self.features = {}
        self.stale = set()
        self.generated = None
        self.final = None
        self.done = False
        self._observe('candidate_universe', dict(symbols=self.symbols,
            arguments=arguments, scope='requested_entry_universe_not_shadow_or_held_only',
            provider_available_at_certified=False, full_replay_ready=False))

    def _observe(self, stage, payload):
        # Callbacks must not prevent an original SELL or change broker requests.
        try:
            return self.recorder.observe(stage, payload)
        except Exception:
            self.recorder.note_failure()
            return None

    def fetched(self, symbol, count, source, *, failed):
        self.fetches[symbol] = dict(record_count=count, source=source,
            status='input_error' if failed or not count else 'returned')

    def generation(self, features, stale_symbols, signals):
        try:
            frozen = capture_value(features)
            self.features = {f['symbol']: f for f in frozen
                             if f.get('feature_name') == 'price_momentum'}
            self.stale = set(stale_symbols)
            self.generated = Counter(s.symbol for s in signals)
            self._observe('entry_generation_inputs', dict(features=frozen,
                stale_symbols=sorted(self.stale), generated=capture_value(signals),
                scope='actual_daily_entry_generation_inputs_not_shadow'))
        except Exception:
            self.recorder.note_failure()

    def prioritized(self, signals):
        self.final = Counter(s.symbol for s in signals)

    def decision_result(self, signal, current_positions, decision, *, runtime_mode, validator):
        """Observe the actual engine call/output without mutating the decision.

        This is a decision-engine boundary, not a post-filter/order/fill join.
        The recorder run ID is a call-site association; a missing business
        run/config field is not silently populated or certified here.
        """
        try:
            self._observe('decision_engine_result', dict(
                run_id=self.recorder.run_id, decision_id=decision.decision_id,
                runtime_mode=runtime_mode, input_signal=capture_value(signal),
                input_current_positions=capture_value(current_positions),
                validator={k: getattr(validator, k) for k in
                           ('min_signal_strength', 'min_confidence', 'max_position_size')},
                output=capture_value(decision), scope='decision_engine_only',
                full_replay_ready=False))
        except Exception:
            self.recorder.note_failure()

    def finalize(self):
        if self.done:
            return
        self.done = True
        rows = []
        for ordinal, symbol in enumerate(self.symbols):
            data = self.fetches.get(symbol, dict(status='not_reached', record_count=None, source=None))
            feature = self.features.get(symbol)
            flags = sorted(set((feature or {}).get('quality_flags') or []))
            generated = self.generated.get(symbol, 0) if self.generated is not None else None
            final = self.final.get(symbol, 0) if self.final is not None else None
            if data['status'] == 'input_error':
                status, reason = 'input_error', 'bars_failed_or_empty'
            elif symbol in self.stale:
                status, reason = 'upstream_excluded', 'stale_data'
            elif self.generated is None:
                status, reason = 'not_reached', 'generation_not_reached'
            elif feature is None or set(flags) & BLOCKING:
                status, reason = 'upstream_excluded', 'missing_or_blocked_momentum_feature'
            elif generated:
                status, reason = 'signals_generated', 'retained' if final else 'priority_filtered_or_not_reached'
            else:
                status, reason = 'no_signal', 'actual_entry_strategies_returned_none'
            rows.append(dict(ordinal=ordinal, symbol=symbol, data=data, status=status,
                reason=reason, quality_flags=flags, generated_entry_count=generated,
                prioritized_entry_count=final))
        self._observe('candidate_coverage', dict(rows=rows,
            generation_reached=self.generated is not None,
            prioritization_reached=self.final is not None,
            scope='entry_universe_only_not_order_or_fill_coverage',
            full_replay_ready=False))


def observe_quote_response(recorder, *, symbol, provider, payload, raw_bytes, received_at):
    """Only the response already consumed by fetch_latest_quote; no new HTTP."""
    quote = payload.get('quote') if isinstance(payload, dict) else None
    quote = quote if isinstance(quote, dict) else {}
    return recorder.observe('consumed_quote', dict(symbol=symbol, provider=provider,
        feed='iex', price_basis='raw_quote_no_adjustment',
        bid=quote.get('bp'), ask=quote.get('ap'), provider_event_at=quote.get('t'),
        local_received_at=received_at.isoformat(),
        raw_body_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        provider_first_publication_at=None, provider_available_at_certified=False),
        observed_at=received_at)


def _stamp(value):
    if not isinstance(value, str):
        raise ValueError('timestamp text required')
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.utcoffset() is None:
        raise ValueError('aware timestamp required')
    return dt.astimezone(timezone.utc)


def _positive(value):
    if isinstance(value, bool):
        return False
    try:
        return Decimal(str(value)).is_finite() and Decimal(str(value)) > 0
    except (InvalidOperation, ValueError):
        return False


def _volume(value):
    return type(value) in (int, float) and Decimal(str(value)).is_finite() and value >= 0


def load_candidate_inputs(project_root, ref):
    """Normal reader: verify the sealed run before deriving missingness.

    A provider timestamp is not a provider publication/availability certificate.
    The previous-minute test below is a LOCAL-RECEIPT engineering check only.
    """
    run = load_input_run(project_root, ref)
    observations = run['observations']
    universes = [o['payload'] for o in observations if o['manifest']['stage'] == 'candidate_universe']
    coverages = [o['payload'] for o in observations if o['manifest']['stage'] == 'candidate_coverage']
    if len(universes) != 1 or len(coverages) != 1:
        raise CaptureError('candidate universe/coverage missing or duplicated')
    symbols = universes[0].get('symbols')
    rows = coverages[0].get('rows')
    if (not isinstance(symbols, list) or not symbols or
            any(not isinstance(s, str) or not s for s in symbols) or
            not isinstance(rows, list) or len(rows) != len(symbols)):
        raise CaptureError('invalid requested-universe denominator')
    allowed = {'input_error', 'not_reached', 'upstream_excluded', 'signals_generated', 'no_signal'}
    for i, (symbol, row) in enumerate(zip(symbols, rows)):
        if (not isinstance(row, dict) or row.get('ordinal') != i or row.get('symbol') != symbol or row.get('status') not in allowed
                or (row['status'] == 'no_signal' and
                    (coverages[0].get('generation_reached') is not True or
                     row.get('generated_entry_count') != 0 or row.get('data', {}).get('status') != 'returned'))):
            raise CaptureError('invalid candidate coverage row')
    quotes = [o['payload'] for o in observations if o['manifest']['stage'] == 'consumed_quote']
    bars = [o['payload'] for o in observations if o['manifest']['stage'] == 'provider_response']
    inventory = []
    for symbol in dict.fromkeys(symbols):
        qs = [q for q in quotes if q.get('symbol') == symbol]
        assessments = []
        for q in qs:
            valid_quote = False
            prior_volume = None
            volumes = {}
            try:
                receipt, event = _stamp(q['local_received_at']), _stamp(q['provider_event_at'])
                valid_quote = (_positive(q['bid']) and _positive(q['ask']) and
                    Decimal(str(q['ask'])) >= Decimal(str(q['bid'])) and event <= receipt)
                end = event.replace(second=0, microsecond=0)
                for b in bars:
                    contract = b['contract']; request = contract['request']
                    if (contract['requested_interval'] != '1Min' or
                            contract.get('requested_adjustment') != 'raw' or
                            request.get('symbol', request.get('ticker')) != symbol or
                            _stamp(contract['received_at']) > receipt):
                        continue
                    for bar in b['response'].get('bars', []):
                        start = _stamp(bar['t'])
                        if start == end - timedelta(minutes=1) and _volume(bar.get('v')):
                            volumes[Decimal(str(bar['v']))] = bar['v']
                # A consumed revision is not permission to silently pick a
                # convenient capacity. Preserve ambiguous versions as missing.
                if len(volumes) == 1:
                    prior_volume = next(iter(volumes.values()))
            except (ValueError, TypeError, KeyError, InvalidOperation):
                valid_quote = False
            assessments.append(dict(valid_bid_ask_and_local_clocks=valid_quote,
                prior_completed_raw_1min_volume=prior_volume,
                locally_observed_pair=valid_quote and prior_volume is not None))
        inventory.append(dict(symbol=symbol, consumed_quotes=len(qs), quotes=assessments,
            missing_quote=not qs, missing_prior_1min=not any(
                a['prior_completed_raw_1min_volume'] is not None for a in assessments)))
    decisions = []
    seen = set()
    for observation in observations:
        if observation['manifest']['stage'] != 'decision_engine_result':
            continue
        payload = observation['payload']
        try:
            output, signal = payload['output'], payload['input_signal']
            identity = payload['decision_id']
            if (not isinstance(identity, str) or not identity or identity in seen or
                    payload['run_id'] != run['manifest']['run_id'] or
                    output['decision_id'] != identity or output['symbol'] != signal['symbol'] or
                    output['strategy_id'] != signal['strategy_id'] or
                    output['mode'] != payload['runtime_mode'] or
                    payload['scope'] != 'decision_engine_only' or payload['full_replay_ready'] is not False or
                    set(payload['validator']) != {'min_signal_strength', 'min_confidence', 'max_position_size'} or
                    not isinstance(payload['input_current_positions'], dict) or
                    _stamp(output['generated_at']) > _stamp(observation['manifest']['local_observed_at'])):
                raise ValueError('decision binding mismatch')
            seen.add(identity)
            decisions.append(payload)
        except (KeyError, TypeError, ValueError):
            raise CaptureError('invalid recorded decision-engine binding')
    return dict(run_id=run['manifest']['run_id'], capture_complete=run['capture_complete'],
        declared_exit_success=run['declared_exit_success'], rows=rows, execution_inputs=inventory,
        recorded_decisions=decisions,
        status_counts=dict(Counter(r['status'] for r in rows)),
        provider_available_at_certified=False, full_replay_ready=False)
