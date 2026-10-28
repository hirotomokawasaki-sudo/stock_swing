from pathlib import Path
import json
j=Path(__file__).resolve().parent;raw=json.loads((j/'script_results.json').read_text());scenarios=json.loads((j/'script_scenarios.json').read_text());normalized={}
def states(d):return [r['state'] for run in d['runs'] if run.get('summary') for r in run['summary']['results']]
for key,d in raw.items():
 normalized[key]=dict(posts=d['all_posts'],runs=[dict(abrupt_exit=r['abrupt_exit']) if 'abrupt_exit' in r else dict(exit_code=r['exit_code'],error=r['error'],summary=r['summary'],http_calls=r['http_calls'],origin_is_copy=r['origin_is_copy']) for r in d['runs']])
 if not key.startswith('candidate_'):continue
 name=key.removeprefix('candidate_');label,case=name.split('_',1)
 posts=d['all_posts']
 for r in d['runs']:
  if r.get('abrupt_exit'):continue
  assert r['error'] is None and r['summary'] is not None and r['exit_code']==r['summary']['exit_code'],key
  assert r['origin_is_copy'] and 'Emergency sell complete' not in r['stdout'],key
  if r['exit_code']==0:assert all(x['state'] in {'accepted','flat','not_applicable','cancelled'} for x in r['summary']['results']),key
 if case in {'normal','accepted_repeat','ack_missing_repeat','ack_found_repeat','lookup_mismatch','http400_repeat','http422_repeat','terminal_rejected_repeat','malformed_ack_found','journal_after_fsync','journal_missing_repeat','journal_partial_repeat','journal_marker_repeat','death_after_accept'}:
  assert len(posts)==1,(key,posts)
  assert len({p['client_order_id'] for p in posts})==1,key
 elif case in {'pending_partial','pending_cancel'}:
  assert len(posts)==1 and posts[0]['qty']==(1 if label=='sell' else 9),key
 elif case=='fractional':
  assert len(posts)==1 and posts[0]['qty']==(3 if label=='sell' else 13),key
  assert d['runs'][0]['exit_code']==1,key
 elif name=='sell_independent_after_unknown':
  assert [(p['symbol'],p['qty']) for p in posts]==[('NOW',3),('IBM',2)],key
 else:assert not posts,(key,posts)
 if case in {'ack_missing_repeat','lookup_mismatch'}:assert d['runs'][0]['exit_code']==d['runs'][1]['exit_code']==1,key
 if case in {'http400_repeat','http422_repeat','terminal_rejected_repeat'}:assert 'rejected' in states(d),key
 if case in {'accepted_repeat','ack_found_repeat','journal_missing_repeat','journal_partial_repeat','journal_marker_repeat'}:assert d['runs'][1]['exit_code']==1,key
for label in ['sell','cover']:
 assert len(raw['baseline_'+label+'_ack_missing_repeat']['all_posts'])==2
 assert len(raw['candidate_'+label+'_ack_missing_repeat']['all_posts'])==1
 for case in ['normal','fractional']:
  before=[{k:v for k,v in p.items() if k!='client_order_id'} for p in raw['baseline_'+label+'_'+case]['all_posts']]
  after=[{k:v for k,v in p.items() if k!='client_order_id'} for p in raw['candidate_'+label+'_'+case]['all_posts']]
  assert before==after,(label,case)
concurrency=json.loads((j/'concurrency_results.json').read_text())
for label in ['sell','cover']:
 assert len(concurrency['baseline_'+label]['posts'])==3 and len(concurrency['candidate_'+label]['posts'])==1
normalized['concurrency']=concurrency
(j/'script_expected.json').write_text(json.dumps(normalized,indent=2,sort_keys=True))
summary=dict(scenarios=len(scenarios),version_cases=len(raw),separate_process_invocations=sum(len(d['runs']) for d in raw.values()),concurrency_cases=4,concurrency_processes=12,normal_integer_quantities_unchanged=True,ack_loss_restart_duplicate_prevented=True,concurrency_and_death_duplicate_prevented=True,default_intent_epoch_rotation=False,fractional_policy_changed=False,real_orders=0)
(j/'script_summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True));print(json.dumps(summary))
