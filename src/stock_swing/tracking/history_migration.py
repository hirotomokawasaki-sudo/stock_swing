"""Explicit, recoverable historical corrections; no broker I/O or automatic repair.

Caller supplies separately evidenced proposals. A digest binds the exact review
intent, not an approval or proof that the economic assumptions are correct.
Version 1 allows one historical transition. Version 2 permits exactly one
disjoint row-only successor, preserving the first transition byte-for-byte.
Original state bytes are archived
inside the state; original event bytes remain an append-only prefix. Fill and
consumption files are CAS dependencies, never rewritten by this migration.
Legacy bypass writers/raw event readers are NOT supported after a transition.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path

from .execution_cost import decimal_value, whole_quantity
from .execution_fifo import utc_time
from .ledger_transaction import FILES, LedgerConflict, digest, json_revision, ledger_transaction

MARKER = 'history_supersession'
ECONOMIC = {'trade_closed', 'trade_quarantined'}
NUMERIC_FIELDS = {'entry_price', 'exit_price', 'pnl', 'return_pct'}


def _json(data):
    return json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()


def parse_events(raw):
    """Strict evidence parser; corrupt/duplicate IDs cannot silently disappear."""
    events=[];ids=set()
    try:
        for line in (raw or b'').decode().splitlines():
            if not line.strip(): continue
            event=json.loads(line)
            if not event.get('event_id') or event['event_id'] in ids or not isinstance(event.get('payload'),dict):
                raise ValueError('invalid/duplicate event identity')
            if not event.get('event_type') or not event.get('created_at'):
                raise ValueError('missing event envelope')
            ids.add(event['event_id']);events.append(event)
    except (ValueError, TypeError, AttributeError, UnicodeError) as exc:
        raise ValueError('corrupt trade event store') from exc
    return events


def active_events(events):
    """Resolve explicit correction sets; raw originals remain audit evidence."""
    by_id={e['event_id']:e for e in events}
    if len(by_id)!=len(events): raise LedgerConflict('duplicate event identity')
    retired=set();replacements=set();migrations=set()
    for e in events:
        if e['event_type']!=MARKER: continue
        p=e['payload'];mid=p.get('migration_id')
        if p.get('schema_version')!=1 or not mid or mid in migrations:
            raise LedgerConflict('unsupported/duplicate history marker')
        migrations.add(mid)
        old=p.get('old_events');new=p.get('replacement_events')
        if not isinstance(old,dict) or not isinstance(new,dict) or not new:
            raise LedgerConflict('invalid history event sets')
        if set(old)&set(new) or retired&set(old) or replacements&set(new):
            raise LedgerConflict('overlapping supersession')
        for eid,expected in {**old,**new}.items():
            target=by_id.get(eid)
            if not target or target['event_type'] not in ECONOMIC or json_revision(target)!=expected:
                raise LedgerConflict('missing/changed supersession event')
        for eid in new:
            if by_id[eid]['payload'].get('history_migration_id')!=mid:
                raise LedgerConflict('replacement belongs to a different migration')
        retired.update(old);replacements.update(new)
    for e in events:
        if e['event_type'] in ECONOMIC and e['payload'].get('history_migration_id') and e['event_id'] not in replacements:
            raise LedgerConflict('orphan corrected event')
    return [e for e in events if e['event_id'] not in retired and e['event_type']!=MARKER]


def validate_history_pair(state, events):
    """Refuse dropped history metadata, mismatched files or damaged archive."""
    history=state.get('history_migrations',[])
    markers=[e for e in events if e['event_type']==MARKER]
    if not isinstance(history,list) or len(history)>2 or len(markers)!=len(history):
        raise LedgerConflict('state/event history version mismatch')
    active_events(events)
    if not history: return
    try:
        affected=set()
        for index,h in enumerate(history):
            intent=h['intent'];mid=json_revision(intent)
            original=base64.b64decode(h['original_state_b64'],validate=True)
            archived=json.loads(original)
            if (h['migration_id']!=mid or h['before_sha256']!=intent['before_sha256'] or
                    digest(original)!=h['before_sha256']['pnl_state.json'] or
                    markers[index]['payload']['migration_id']!=mid or
                    archived.get('history_migrations',[])!=history[:index]):
                raise ValueError('history digest/ancestry mismatch')
            if index==0:
                if intent['schema_version']!=1:raise ValueError('unsupported initial transition')
            else:
                if (intent['schema_version']!=2 or intent.get('parent_migration_id')!=history[index-1]['migration_id']
                        or intent['corporate_provenance'] or intent['retire_records'] or intent['replacement_rows']):
                    raise ValueError('unsupported successor transition')
                if archived.get('measurement_lineage',{}).get('ledger_revision')!=intent['parent_migration_id']:
                    raise ValueError('successor archive lineage mismatch')
            targets=[r['after'] for r in intent['row_changes']]+intent['replacement_rows']
            scope={r['exit_broker_order_id'] for r in targets}
            scope.update(r['before']['exit_broker_order_id'] for r in intent['retire_records'])
            if affected & scope:raise ValueError('overlapping history transition')
            affected.update(scope)
            for change in intent['row_changes']:
                if archived['trades'][change['row_index']]!=change['before']:
                    raise ValueError('changed row differs from archive')
            # Retired records must never reappear; predecessor targets stay active.
            for ref in intent['retire_records']:
                if ref['before'] in state.get(ref['collection'],[]):
                    raise ValueError('retired record reactivated')
            for expected in targets:
                # A differently-valued copy of the superseded numeric row
                # must not coexist with the corrected economic identity.
                # Partial executions can legitimately share BUY/SELL/lot.
                # Their immutable execution leg and clocks disambiguate them.
                identity=('trade_id','broker_order_id','exit_broker_order_id',
                          'execution_leg_id','entry_time','exit_time')
                matching=[r for r in state['trades']
                          if all(r.get(k)==expected.get(k) for k in identity)]
                if len(matching)!=1 or matching[0]!=expected:
                    raise ValueError('corrected row missing/changed/duplicated')
        if state.get('measurement_lineage',{}).get('ledger_revision')!=history[-1]['migration_id']:
            raise ValueError('latest history lineage mismatch')
    except (ValueError,KeyError,TypeError,IndexError,AttributeError) as exc:
        raise LedgerConflict('corrupt history state') from exc


def _validate_closed(row):
    if row.get('status')!='closed': raise LedgerConflict('only verified closed rows may be inserted')
    for key in ('trade_id','symbol','broker_order_id','exit_broker_order_id'):
        if not row.get(key): raise LedgerConflict('missing closed row identity')
    qty=whole_quantity(row.get('qty'),'closed quantity')
    entry=decimal_value(row.get('entry_price'),'entry price');exit=decimal_value(row.get('exit_price'),'exit price')
    pnl=Decimal(str(row.get('pnl')))
    if not pnl.is_finite() or abs(pnl-(exit-entry)*qty)>Decimal('.010001'):
        raise LedgerConflict('closed row arithmetic mismatch')
    start,end=utc_time(row.get('entry_time')),utc_time(row.get('exit_time'))
    if start>end: raise LedgerConflict('reversed closed row')
    holding=Decimal(str(row.get('holding_days')))
    if not holding.is_finite() or abs(float(holding)-(end-start).total_seconds()/86400)>.00011:
        raise LedgerConflict('holding period mismatch')


def _project(before, intent):
    state=deepcopy(before);seen=set()
    for change in intent['row_changes']:
        index=change['row_index'];ref=('trades',index)
        if type(index) is not int or index<0 or ref in seen or index>=len(state['trades']):
            raise LedgerConflict('invalid/overlapping row change')
        seen.add(ref)
        if state['trades'][index]!=change['before']: raise LedgerConflict('stale proposed row')
        if not {k for k in change['before'].keys()|change['after'].keys() if change['before'].get(k)!=change['after'].get(k)}<=NUMERIC_FIELDS:
            raise LedgerConflict('ordinary correction cannot change identity/attribution')
        _validate_closed(change['after']);state['trades'][index]=deepcopy(change['after'])
    retire={'trades':set(),'quarantined_trades':set()}
    for ref in intent['retire_records']:
        c,i=ref['collection'],ref['row_index']
        if c not in retire or type(i) is not int or i<0 or i>=len(state.get(c,[])) or (c,i) in seen:
            raise LedgerConflict('invalid/overlapping retirement')
        seen.add((c,i))
        if state[c][i]!=ref['before']: raise LedgerConflict('stale retirement')
        if ref['before'].get('status') not in {'closed','quarantined'}: raise LedgerConflict('cannot retire open inventory')
        retire[c].add(i)
    for c,indices in retire.items():state[c]=[r for i,r in enumerate(state.get(c,[])) if i not in indices]
    for row in intent['replacement_rows']:
        _validate_closed(row)
        if row in state['trades']: raise LedgerConflict('duplicate replacement')
        state['trades'].append(deepcopy(row))
    touched={r['after']['exit_broker_order_id'] for r in intent['row_changes']}
    touched.update(r['before']['exit_broker_order_id'] for r in intent['retire_records'])
    touched.update(r['exit_broker_order_id'] for r in intent['replacement_rows'])
    if not touched: raise LedgerConflict('empty migration')
    if any(r.get('exit_broker_order_id') in touched for r in state['quarantined_trades']):
        raise LedgerConflict('unretired quarantine in affected scope')
    keys=[]
    for r in state['trades']:
        if r.get('exit_broker_order_id') not in touched: continue
        if r.get('status')!='closed': raise LedgerConflict('nonclosed affected row')
        _validate_closed(r)
        keys.append((r['trade_id'],r.get('execution_leg_id'),r['broker_order_id'],r['exit_broker_order_id'],r['exit_time']))
    if len(set(keys))!=len(keys):raise LedgerConflict('duplicate affected execution leg')
    return state,sorted(touched)


def prepare_migration(inputs, *, row_changes, corporate_plans, evidence_sha256, recorded_at, reason):
    """Pure plan builder. Inputs are four independent frozen file bytes."""
    if set(inputs)!=FILES or any(not isinstance(b,bytes) for b in inputs.values()):
        raise LedgerConflict('four existing ledger files are required')
    utc_time(recorded_at)
    if not reason or not isinstance(evidence_sha256,str) or len(evidence_sha256)!=64 or any(c not in '0123456789abcdef' for c in evidence_sha256):
        raise LedgerConflict('review evidence digest/reason required')
    try:before=json.loads(inputs['pnl_state.json'])
    except (ValueError,TypeError) as exc:raise LedgerConflict('invalid state') from exc
    old_events=parse_events(inputs['trade_events.jsonl']);validate_history_pair(before,old_events)
    prior=before.get('history_migrations',[])
    if len(prior)>=2:raise LedgerConflict('only one disjoint successor is supported')
    if prior and corporate_plans:raise LedgerConflict('successor must be row-only')
    retire=[];replacement=[]
    for plan in corporate_plans:
        retire.extend(deepcopy(plan['retire_records']))
        replacement.extend(deepcopy(plan['candidate_rows']))
    for row in replacement:
        # Account epoch is known; no strategy/decision lineage is inferred.
        if not row.get('account_id'):row['account_id']=before.get('broker_account_id') or 'legacy_account'
    intent=dict(schema_version=2 if prior else 1,before_sha256={n:digest(b) for n,b in sorted(inputs.items())},
        row_changes=deepcopy(row_changes),retire_records=retire,replacement_rows=replacement,
        evidence_sha256=evidence_sha256,recorded_at=recorded_at,reason=reason,
        corporate_provenance=deepcopy(corporate_plans))
    if prior:intent['parent_migration_id']=prior[-1]['migration_id']
    # Fails on nonfinite values anywhere, including metadata/provenance.
    mid=json_revision(intent);state,affected=_project(before,intent)
    corrections=[]
    for i,r in enumerate(state['trades']):
        if r.get('exit_broker_order_id') not in affected:continue
        corrections.append(dict(event_id=f'history:{mid}:leg:{i}',event_type='trade_closed',created_at=recorded_at,
            symbol=r['symbol'],trade_id=r['trade_id'],broker_order_id=r['exit_broker_order_id'],run_id=None,
            payload=dict(schema_version=2,qty_semantics='incremental_closed_leg',history_migration_id=mid,
                entry_broker_order_id=r['broker_order_id'],exit_broker_order_id=r['exit_broker_order_id'],
                execution_leg_id=r.get('execution_leg_id'),exit_qty=r['qty'],pnl=r['pnl'],exit_price=r['exit_price'],
                original_entry_time=r['entry_time'],original_exit_time=r['exit_time'],
                exit_reason=r.get('exit_reason'),identity_scope='posthoc_corrected_ledger_leg_not_decision_replay')))
    old={e['event_id']:json_revision(e) for e in old_events if e['event_type'] in ECONOMIC and e.get('broker_order_id') in affected}
    marker=dict(event_id=f'history:{mid}:supersession',event_type=MARKER,created_at=recorded_at,
                symbol=None,trade_id=None,broker_order_id=None,run_id=None,
                payload=dict(schema_version=1,migration_id=mid,old_events=old,
                             replacement_events={e['event_id']:json_revision(e) for e in corrections}))
    state['history_migrations']=deepcopy(prior)+[dict(migration_id=mid,intent=intent,before_sha256=intent['before_sha256'],
                                     original_state_b64=base64.b64encode(inputs['pnl_state.json']).decode())]
    state['measurement_lineage']=dict(ledger_revision=mid,measurement_status='historical_correction_unqualified',
        old_snapshot_revision=intent['before_sha256']['pnl_state.json'],
        historical_snapshots='preserved_as_observed_not_recomputed',
        account_drawdown='preserved_not_revalidated',strategy_attribution='reconstructed_lots_unknown',
        promotion_ready=False)
    # Do not silently replace recorded valuation/PF/DD history with hindsight.
    for name in ('daily_snapshots','strategy_daily_snapshots'):
        for snap in state.get(name,[]):
            snap.setdefault('ledger_revision',intent['before_sha256']['pnl_state.json'])
            snap.setdefault('history_basis','pre_correction_as_observed')
    closed=[r for r in state['trades'] if r.get('status')=='closed']
    state['cumulative_realized_pnl']=float(sum((Decimal(str(r['pnl'])) for r in closed),Decimal(0)).quantize(Decimal('.01')))
    state['winning_trades']=sum(r['pnl']>0 for r in closed);state['losing_trades']=sum(r['pnl']<0 for r in closed)
    # total_trades used to be a mixed submission/leg counter. From migration on,
    # it is explicitly the physical active-row count; original remains archived.
    state['total_trades']=len(state['trades']);state['last_updated']=recorded_at
    after_events=inputs['trade_events.jsonl']
    if after_events and not after_events.endswith(b'\n'):after_events+=b'\n'
    after_events+=b''.join(_json(e)+b'\n' for e in corrections+[marker])
    validate_history_pair(state,parse_events(after_events))
    return dict(schema_version=intent['schema_version'],migration_id=mid,intent=intent,affected_sell_orders=affected,
        after_state=state,after_events_b64=base64.b64encode(after_events).decode(),
        stats=dict(changed_rows=len(row_changes),retired_records=len(retire),replacement_rows=len(replacement),
                   superseded_events=len(old),corrected_events=len(corrections),
                   old_active_pnl=float(sum((Decimal(str(r.get('pnl') or 0)) for r in before['trades'] if r.get('status')=='closed'),Decimal(0)).quantize(Decimal('.01'))),
                   new_active_pnl=state['cumulative_realized_pnl']))


def apply_migration(project_root, plan):
    """Explicit opt-in apply API; no CLI/scheduler invokes it automatically.

    Under lock: recover prepared work, compare all four inputs, verify a fresh
    deterministic projection, then commit state+append-only events together.
    """
    root=Path(project_root);folder=root/'data/tracking'
    with ledger_transaction(root) as tx:
        inputs={n:tx.read(folder/n) for n in FILES}
        if any(b is None for b in inputs.values()):raise LedgerConflict('missing ledger dependency')
        try:
            state=json.loads(inputs['pnl_state.json']);events=parse_events(inputs['trade_events.jsonl'])
            validate_history_pair(state,events)
            intent=plan['intent'];mid=json_revision(intent)
            if plan['schema_version'] not in (1,2) or plan['schema_version']!=intent['schema_version'] or plan['migration_id']!=mid:
                raise LedgerConflict('invalid migration plan')
            if any(h['migration_id']==mid for h in state.get('history_migrations',[])):
                return dict(status='already_applied',migration_id=mid)
            if {n:digest(b) for n,b in inputs.items()}!=intent['before_sha256']:
                raise LedgerConflict('stale migration base; all four files must match')
            expected=prepare_migration(inputs,row_changes=intent['row_changes'],corporate_plans=intent['corporate_provenance'],
                evidence_sha256=intent['evidence_sha256'],recorded_at=intent['recorded_at'],reason=intent['reason'])
            if plan!=expected:raise LedgerConflict('altered migration projection')
        except (ValueError,KeyError,TypeError) as exc:
            raise LedgerConflict('invalid migration evidence') from exc
        tx.stage(folder/'pnl_state.json',_json(plan['after_state']))
        tx.stage(folder/'trade_events.jsonl',base64.b64decode(plan['after_events_b64'],validate=True))
    return dict(status='applied',migration_id=mid)
