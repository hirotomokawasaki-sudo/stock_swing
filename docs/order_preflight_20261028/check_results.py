from pathlib import Path
import hashlib,json,re,subprocess
j=Path(__file__).parent
r=json.loads((j/'cli_results.json').read_text())
assert len(r)==18
buys=lambda key:[p for p in r[key]['posts'] if p['side']=='buy']
sells=lambda key:[p for p in r[key]['posts'] if p['side']=='sell']
assert buys('baseline_normal')==buys('candidate_normal')
for name in ['cluster','pending','same_symbol_pending','order_page_unknown','duplicate_buy','buy_sell_conflict']:
 assert buys('baseline_'+name) and not buys('candidate_'+name), name
for name in ['cluster','pending','batch','buy_sell_conflict']:
 assert sells('baseline_'+name)==sells('candidate_'+name), name
assert len(buys('baseline_batch'))==2 and [p['symbol'] for p in buys('candidate_batch')]==['MSFT']
assert 25000+61*130*2==40860 and 25000+61*130==32930
assert [p['symbol'] for p in buys('baseline_response_lost')]==['MSFT']*3+['CRM']*3
assert [p['symbol'] for p in buys('candidate_response_lost')]==['MSFT']*3
assert 'submission_outcome_unknown' in str(r['candidate_response_lost']['preflight'])
assert all(data['main_exit']==0 and data['origin_is_copy'] for data in r.values())
assert all(method in {'GET','POST'} for data in r.values() for method,path in data['http_calls'])
def normalize(data):
 receipts=[]
 for report in data['preflight']:
  receipts.append({'snapshot_available':report['snapshot_available'],'snapshot_reason':report['snapshot_reason'],
                   'receipts':[{k:v for k,v in row.items() if k not in {'decision_id','related_decision_ids'}} for row in report['receipts']]})
 return {'exit':data['main_exit'],'posts':data['posts'],'preflight':receipts,'copy_origin':data['origin_is_copy']}
(j/'expected.json').write_text(json.dumps({key:normalize(value) for key,value in r.items()},indent=2,sort_keys=True))
print(json.dumps({'cli_cases':len(r),'all_assertions_passed':True,'known_unfixed_first_intent_retries':3}))
