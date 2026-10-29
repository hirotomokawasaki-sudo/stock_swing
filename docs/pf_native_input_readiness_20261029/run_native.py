from pathlib import Path
import json,shutil,subprocess,sys,os
j=Path(__file__).resolve().parent
cases={
 'normal':{},'pf_blocked':{'pf_seed':True},'restricted':{'pf_seed':True,'env':{'ENTRY_FILTER_PURCHASE_RESTRICTED_SYMBOLS':'NVDA'}},
 'volume':{'pf_seed':True,'volume':1},'sell':{'owned':True,'price':50},
 'unknown_account':{'bad_account':True},'dry':{'dry_run':True},
 'halt':{'halt':True},'reduced_skip':{'pf_seed':True,'env':{'ENTRY_FILTER_PF_GATE_SKIP_SYMBOLS':'NVDA','ENTRY_FILTER_STOCK_REDUCED':'true'}},
}
all_results={};out=j/'native_results';out.mkdir(exist_ok=True)
for name,scenario in cases.items():
 group=[]
 for variant in ['native_A','adapter_A','adapter_B']:
  root=j/'native_copies_final'/(name+'_'+variant);root.mkdir(parents=True)
  for folder in ['src','config']:shutil.copytree(j/'candidate'/folder,root/folder)
  state=root/'data/tracking/pnl_state.json';state.parent.mkdir(parents=True);state.write_text(json.dumps(dict(last_updated='2026-11-02T14:34:00+00:00',trades=[])))
  old=root/'data/analysis/entry_restriction_review_v1.json';old.parent.mkdir(parents=True);shutil.copy2(j/'inputs/entry_restriction_review_v1.json',old)
  if scenario.get('halt'):
   # Original persisted HALT input; never reset/clear a live control.
   p=root/'data/guardrails/circuit_breaker.json';p.parent.mkdir(parents=True,exist_ok=True)
   p.write_text(json.dumps(dict(status='halted',halted=True,reason='synthetic-test',triggered_at='2026-11-02T14:30:00+00:00')))
  body=dict(scenario,arm='PF-B' if variant=='adapter_B' else 'PF-A',wrapped=variant!='native_A')
  (root/'scenario.json').write_text(json.dumps(body));shutil.copy2(j/'native_driver.py',root/'driver.py')
  env=dict(PATH='/opt/homebrew/bin:/usr/bin:/bin',TZ='Asia/Tokyo',PYTHONPATH=str(root/'src'),PYTHONDONTWRITEBYTECODE='1',BROKER_API_KEY='fixture',BROKER_API_SECRET='fixture',BROKER_BASE_URL='https://paper-fixture.invalid',MASSIVE_API_KEY='fixture',ENTRY_RESTRICTION_REVIEW_ENABLED='false',ENTRY_RESTRICTION_REVIEW_VERSION='v2');env.update({'ENTRY_FILTER_PF_GATE_SKIP_SYMBOLS':'AMD,HPE',**scenario.get('env',{})})
  p=subprocess.run(['/usr/bin/sandbox-exec','-f',str(j/'deny.sb'),sys.executable,'-B',str(root/'driver.py')],cwd=root,env=env,text=True,capture_output=True,timeout=60)
  (out/(name+'_'+variant+'.stderr')).write_text(p.stderr)
  if p.returncode:raise RuntimeError(name+' '+variant+': '+p.stderr[-1800:])
  d=json.loads(p.stdout);(out/(name+'_'+variant+'.json')).write_text(p.stdout)
  normalized=[{k:v for k,v in order.items() if k!='client_order_id'} for order in d['posts']]
  result=dict(main_exit=d['main_exit'],posts=normalized,http=d['http_calls'],funnel=d['funnel'],bridge=d['bridge_snapshot'],legs=d['bridge_after_intent']['fills'],filters=d['research_filter_receipts'])
  all_results[name+'_'+variant]=result;group.append(result)
 for field in ['main_exit','posts','http']:
  assert group[0][field]==group[1][field],(name,field)
 print(name,[(x['main_exit'],len(x['posts']),len(x['legs'])) for x in group],flush=True)
(j/'NATIVE.json').write_text(json.dumps(dict(cases=len(all_results),A_native_business_HTTP_identical=True,results=all_results),indent=2,sort_keys=True)+'\n')
