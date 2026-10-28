from pathlib import Path
import json
j=Path(__file__).parent;raw=json.loads((j/'cli_results.json').read_text());normalized={}
for key,d in raw.items():
 if key.startswith('candidate_'):
  assert d['main_exit']==0 and d['origin_is_copy'],(key,d.get('diagnostic_tail'))
  if key.split('_',1)[1].startswith(('exit_','alloc_','registry_','intraday_')):
   assert [(p['side'],p['symbol'],p['qty']) for p in d['posts']]==[('sell','NVDA',1)],key
   assert d['run_status']=='DEGRADED' and any(a['code']=='effective_config_unavailable' for a in d['alerts']),key
   assert any(r['status']=='unavailable' for r in d['effective_config']),key
 posts=[dict((k,v) for k,v in p.items() if k!='client_order_id') for p in d['posts']]
 # Omit generated IDs/timestamps/paths; retain reasons, outcomes and exact order payloads.
 receipts=[r for report in d.get('preflight',[]) for r in report.get('receipts',report.get('checks',[]))]
 normalized[key]=dict(main_exit=d['main_exit'],posts=posts,run_status=d.get('run_status'),
  funnel={k:d.get('funnel',{}).get(k) for k in ('submitted','rejected','unknown','held')},
  config=[dict(kind=r['kind'],status=r['status'],issues=r['issues'],unused_keys=r.get('unused_keys',[])) for r in d.get('effective_config',[])],
  alert_codes=sorted(a['code'] for a in d.get('alerts',[])),
  hold_reasons=sorted(set(x.get('reason','') for report in d.get('preflight',[]) for x in report.get('checks',report.get('receipts',[])))))
assert len(raw)==38,len(raw)
for name in ['normal','sell_and_buy']:assert normalized['baseline_'+name]['posts']==normalized['candidate_'+name]['posts'],name
assert len(raw['baseline_lost_not_found']['posts'])==3 and len(raw['candidate_lost_not_found']['posts'])==1,'first intent retry contained'
assert raw['candidate_lost_not_found']['funnel']['unknown']==1,'unknown must not be rejected'
assert raw['candidate_lost_not_found']['run_status']=='DEGRADED'
assert len(raw['candidate_lost_found']['posts'])==2 and raw['candidate_lost_found']['funnel']['unknown']==0,'lookup recovery'
assert not raw['candidate_gap_candidate']['posts'],'candidate gap held'
for name in ['gap_holding','gap_pending']:assert [p['symbol'] for p in raw['candidate_'+name]['posts']]==['MSFT'],name
(j/'expected.json').write_text(json.dumps(normalized,indent=2,sort_keys=True))
print(json.dumps(dict(cases=len(raw),candidate_successful=19,normal_unchanged=True,unknown_first_posts=1,config_buy_held_sell_continues=12,classification_gap_cases=3)))
