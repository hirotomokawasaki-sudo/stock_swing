from pathlib import Path
import json
j=Path(__file__).resolve().parent;raw=json.loads((j/'cli_results.json').read_text());prior=json.loads((j/'previous_safety_expected.json').read_text());normalized={}
def norm(d):
 return dict(main_exit=d['main_exit'],posts=[{k:v for k,v in p.items() if k!='client_order_id'} for p in d['posts']],run_status=d.get('run_status'),funnel={k:d.get('funnel',{}).get(k) for k in ('submitted','rejected','unknown','held')},config=[dict(kind=r['kind'],status=r['status'],issues=r['issues'],unused_keys=r.get('unused_keys',[])) for r in d.get('effective_config',[])],alert_codes=sorted(a['code'] for a in d.get('alerts',[])),hold_reasons=sorted(set(x.get('reason','') for report in d.get('preflight',[]) for x in report.get('checks',report.get('receipts',[])))))
assert len(raw)==40,len(raw)
for key,d in raw.items():
 assert d['origin_is_copy'],key
 version,name=key.rsplit('_',1) if False else (None,None)
 if key.startswith('integrated_off_'):
  name=key.removeprefix('integrated_off_');n=norm(d)
  assert n==prior['candidate_'+name],(key,n,prior['candidate_'+name])
  assert d['indices']==0 and not d['store_exists'],key
 elif key.startswith('integrated_on_'):
  name=key.removeprefix('integrated_on_');n=norm(d)
  assert n==norm(raw['integrated_off_'+name]),key
  assert d['indices']==1 and d['capture_complete'] and d['declared_exit_success'],key
  assert not d['full_replay_ready'],key
  assert d['stage_counts']['run_end']==1 and d['stage_counts']['provider_response']>=1 and d['stage_counts']['canonical_provider_bars']>=1,key
 else:
  name=key.removeprefix('blocked_capture_');n=norm(d);comparison=norm(raw['integrated_off_'+name]);n['main_exit']=comparison['main_exit']
  assert n==comparison,key
  assert d['main_exit']==1 and d['indices']==0,key
  n['main_exit']=d['main_exit']
 normalized[key]=dict(business=n,indices=d['indices'],capture_complete=d.get('capture_complete'),stage_counts=d.get('stage_counts'),full_replay_ready=d.get('full_replay_ready'))
assert raw['integrated_on_lost_not_found']['run_status']=='DEGRADED'
(j/'expected.json').write_text(json.dumps(normalized,sort_keys=True,indent=2))
print(json.dumps(dict(cases=len(raw),off_matches_previous_safety=19,on_off_business_equal=19,capture_failure_business_equal_main1=2,full_replay_qualified=False)))
