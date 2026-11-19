"""Observe existing broker GETs and native guard inputs; never fetch or authorize.

Decoded allowlisted state is not an atomic account snapshot, settled cash,
complete pagination, wire-body archive, or a full execution/replay certificate.
"""
from dataclasses import asdict
import hashlib

from .decision_input_capture import capture_value


ACCOUNT = ('status','currency','cash','equity','buying_power','portfolio_value',
           'trading_blocked','account_blocked','trade_suspended_by_user')
POSITION = ('asset_id','symbol','asset_class','qty','side','avg_entry_price',
            'market_value','cost_basis','unrealized_pl','current_price')
ORDER = ('id','client_order_id','symbol','side','qty','filled_qty','filled_avg_price',
         'status','type','time_in_force','submitted_at','updated_at','canceled_at',
         'replaced_by','replaces','limit_price','stop_price')


def observe_broker_state(recorder, *, endpoint, method, request, payload,
                         raw_bytes, received_at):
    if recorder is None or not recorder.enabled:
        return None
    if method != 'GET' or endpoint not in ('v2/account','v2/positions','v2/orders'):
        return None
    try:
        # Reject credential-bearing data before projection, without retaining it.
        clean=capture_value(payload); params=capture_value(request)
        account_hash=None
        if endpoint=='v2/account':
            if not isinstance(clean,dict): raise ValueError('account object required')
            projection={k:clean[k] for k in ACCOUNT if k in clean}
            if clean.get('id'):
                account_hash=hashlib.sha256(str(clean['id']).encode()).hexdigest()
        else:
            if not isinstance(clean,list) or any(not isinstance(x,dict) for x in clean):
                raise ValueError('explicit response list required')
            fields=POSITION if endpoint=='v2/positions' else ORDER
            projection=[{k:x[k] for k in fields if k in x} for x in clean]
        return recorder.observe('broker_state_response',dict(
            schema='broker-state-observation-v1',endpoint=endpoint,method=method,
            request=params,response=projection,account_id_sha256=account_hash,
            raw_body_sha256=hashlib.sha256(raw_bytes).hexdigest(),raw_body_saved=False,
            received_at=received_at,explicit_empty_response=projection==[],
            pagination_complete_certified=False,settled_cash_certified=False,
            atomic_snapshot_certified=False,full_replay_ready=False,
            scope='actual_GET_response_allowlisted_projection_not_complete_seed'),
            observed_at=received_at)
    except Exception:
        recorder.note_failure()
        return None


def observe_prebuy_guard(recorder, *, snapshot, engine, decision):
    if recorder is None or not recorder.enabled:
        return None
    return recorder.observe('prebuy_guardrail_inputs',dict(
        snapshot=asdict(snapshot),rules=[asdict(r) for r in engine.rules],
        warning_only=engine.warning_only,decision=asdict(decision),
        explicit_callsite_metrics=['equity','unrealized_pnl','prev_unrealized_pnl',
            'stale_price_event_count','broker_tracker_mismatch_count','trades'],
        defaulted_runtime_rates=['api_error_rate_pct','order_rejection_rate_pct','token_spend_spike_pct'],
        date_relative_clock_certified=False,full_replay_ready=False,
        scope='native_prebuy_snapshot_and_rules_not_full_buy_gate'))
