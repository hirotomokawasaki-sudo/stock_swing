"""Pure nine-case review; private and ID-replaced evidence share this function."""
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal as D
import importlib.util
import json
from pathlib import Path

spec=importlib.util.spec_from_file_location('r22_repair_preview',Path(__file__).with_name('repair_preview.py'))
repair=importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


def review(data):
    ids=[c.get('order_id') for c in data['cases']]
    if not all(ids) or len(ids)!=len(set(ids)):
        raise ValueError('missing/duplicate review case identity')
    state,orders,activities=data['state'],data['orders'],data['activities']
    proof=repair.Evidence(orders,activities)
    changes=[];summary=[];corporate=[];event_review=[]
    for case in data['cases']:
        oid,symbol,kind=case['order_id'],case['symbol'],case['kind']
        sell=proof.order(oid,'sell',symbol)
        if kind=='corporate':
            plan=repair.corporate_plan(state,orders,activities,symbol,'2026-08-24')
            corporate.append(plan)
            row=dict(symbol=symbol,kind=kind,scope='symbol lifecycle before 2026-08-24',
                     old_pnl=plan['old_active_pnl'],new_pnl=plan['new_active_pnl'],pnl_delta=plan['pnl_delta'],
                     old_physical_records=len(plan['retire_records']),new_rows=len(plan['candidate_rows']),
                     total_reconstructed_sell_qty=sum(r['qty'] for r in plan['candidate_rows']),
                     apply_ready=False)
            new_rows=[t for t in plan['candidate_rows'] if t['exit_broker_order_id']==oid]
        else:
            if kind=='precision':
                proposed=repair.group_precision(state,orders,activities,[oid])
            elif kind=='partial':
                proposed=repair.partial_economics(state,orders,activities,data['fill_revisions'],[oid])
            else:raise ValueError('unknown review kind')
            projected=repair.project_rows(state,proposed)
            old_rows=[r for r in state['trades'] if r.get('exit_broker_order_id')==oid]
            new_rows=[r for r in projected if r.get('exit_broker_order_id')==oid]
            old_pnl=sum(D(str(r['pnl'])) for r in old_rows);new_pnl=sum(D(str(r['pnl'])) for r in new_rows)
            new_cost=sum(proof.order(r['broker_order_id'],'buy',symbol)['price']*r['qty'] for r in new_rows)
            row=dict(symbol=symbol,kind=kind,scope='selected SELL order',changed_rows=len(proposed),
                     sell_qty=sell['qty'],old_pnl=str(repair.cents(old_pnl)),new_pnl=str(repair.cents(new_pnl)),
                     pnl_delta=str(repair.cents(new_pnl-old_pnl)),raw_proceeds=str(sell['notional']),
                     raw_allocated_cost=str(new_cost),cash_minus_rounded_legs=str(sell['notional']-new_cost-new_pnl))
            changes.extend(proposed)
        summary.append(row)
        events=[e for e in data.get('events',[]) if e.get('broker_order_id')==oid and e.get('event_type')=='trade_closed']
        duplicates=defaultdict(list)
        for e in events:duplicates[json.dumps(e['payload'],sort_keys=True)].append(e['event_id'])
        desired_qty=sum(r['qty'] for r in new_rows);desired_pnl=sum(D(str(r['pnl'])) for r in new_rows)
        event_review.append(dict(symbol=symbol,old_event_ids=[e['event_id'] for e in events],
            old_event_count=len(events),old_event_qty=sum(e['payload']['exit_qty'] for e in events),
            old_event_pnl=str(repair.cents(sum((D(str(e['payload']['pnl'])) for e in events),D(0)))),
            desired_selected_order_qty=desired_qty,desired_selected_order_pnl=str(repair.cents(desired_pnl)),
            duplicate_payload_groups=[v for v in duplicates.values() if len(v)>1],
            requirement='preserve originals; explicit correction/supersession semantics required before historical event repair'))
    numeric_event_summary=[{k:v for k,v in r.items() if k not in {'old_event_ids','duplicate_payload_groups','requirement'}} |
                           {'duplicate_excess_rows':sum(len(g)-1 for g in r['duplicate_payload_groups'])} for r in event_review]
    summary=dict(cases=summary,case_count=len(summary),ordinary_changed_rows=len(changes),
                 ordinary_pnl_delta=str(repair.cents(sum((D(c['pnl_delta']) for c in changes),D(0)))),
                 all_case_scopes_pnl_delta=str(repair.cents(sum((D(c['pnl_delta']) for c in summary),D(0)))),
                 event_review=numeric_event_summary,
                 status='NUMERIC_PREVIEW_ONLY_NOT_APPLIED; event/supersession/aggregate migration incomplete')
    return dict(summary=summary,row_changes=changes,corporate_plans=corporate,event_plans=event_review,
                original_inputs_unchanged=True)
