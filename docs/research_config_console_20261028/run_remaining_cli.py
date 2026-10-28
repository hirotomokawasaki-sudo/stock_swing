from pathlib import Path
import json,os,shutil,subprocess,sys
j=Path(__file__).resolve().parent
cases={
 'normal':{},
 'sell_and_buy':dict(symbols='MSFT,NVDA',positions=[dict(symbol='NVDA',qty='1',market_value='50',current_price='50',avg_entry_price='200',unrealized_pl='-150',unrealized_plpc='-.75',asset_class='us_equity')]),
 'entry_override':dict(env={'ENTRY_FILTER_MIN_VOLUME':'12345','ENTRY_FILTER_MIN_ADR_PCT':'0.9','ENTRY_FILTER_PF_GATE_SKIP_SYMBOLS':'MSFT,NVDA'}),
 'entry_restricted':dict(env={'ENTRY_FILTER_PURCHASE_RESTRICTED_SYMBOLS':'NVDA'}),
 'entry_disabled':dict(env={'ENTRY_FILTER_DISABLED':'true'}),
 'entry_failure':dict(env={'ENTRY_FILTER_MIN_VOLUME':'PRIVATE-CANARY'}),
 'entry_nonfinite':dict(env={'ENTRY_FILTER_MIN_VOLUME':'NaN'}),
 'losing_fallback':dict(env={'LOSING_POSITION_ADD_GUARD_MAX_LOSS_PCT':'PRIVATE-CANARY'}),
 'losing_invalid_mode':dict(env={'LOSING_POSITION_ADD_GUARD_MODE':'PRIVATE-CANARY'}),
 'dry_run':dict(dry_run=True),
 'write_blocked':dict(block_config=True),
}
results={}
versions=['baseline_off','baseline_on','candidate_off','candidate_on']
for case,body in cases.items():
 for version in versions:
  root=j/'remaining_cli_copies'/(version+'_'+case);root.mkdir(parents=True)
  source=j/('baseline' if version.startswith('baseline') else 'candidate')
  for name in ['src','config']:shutil.copytree(source/name,root/name)
  (root/'config/runtime/current_mode.yaml').write_text('mode: paper\n')
  (root/'config/guardrails/autonomous_stop.yaml').write_text('paper_warning_only: true\nrules: {}\n')
  p=root/'data/tracking/pnl_state.json';p.parent.mkdir(parents=True);p.write_text(json.dumps(dict(last_updated='2026-10-28T14:59:00+00:00',trades=[])))
  if body.get('block_config'):
   p=root/'reports/config_instances';p.parent.mkdir(parents=True);p.write_text('fixture blocked')
  (root/'scenario.json').write_text(json.dumps(dict(body,config_capture=version.endswith('_on'))))
  shutil.copy2(j/'cli_driver.py',root/'driver.py')
  env=dict(PATH='/usr/bin:/bin',TZ='Asia/Tokyo',PYTHONPATH=str(root/'src'),PYTHONDONTWRITEBYTECODE='1',BROKER_API_KEY='fixture',BROKER_API_SECRET='fixture',BROKER_BASE_URL='https://paper-fixture.invalid',MASSIVE_API_KEY='fixture',**body.get('env',{}))
  run=subprocess.run(['/usr/bin/sandbox-exec','-f',str(j/'deny.sb'),sys.executable,'-B',str(root/'driver.py')],cwd=root,env=env,capture_output=True,text=True,timeout=65)
  (j/(case+'_'+version+'.stderr')).write_text(run.stderr)
  assert run.returncode==0,(case,version,run.stderr[-600:]);data=json.loads(run.stdout)
  (j/(case+'_'+version+'.json')).write_text(run.stdout)
  receipts=[r for r in data['effective_config'] if r['kind'].startswith('instance:')]
  results[case+'_'+version]=dict(exit=data['main_exit'],posts=[{k:v for k,v in p.items() if k!='client_order_id'} for p in data['posts']],orders=data['orders'],business=data['business_decision_lines'],receipts=receipts,events=data['config_events'])
 group=[results[case+'_'+v] for v in versions]
 for key in ['posts','orders','business']:
  assert all(g[key]==group[0][key] for g in group),(case,key)
 assert group[0]['exit']==group[2]['exit'],(case,'OFF behavior drift')
 if case=='entry_failure':
  assert all(g['exit']==99 for g in group),'original failure unchanged'
  assert any(e['payload']['kind']=='instance:EntryFilterConfig' and e['payload']['status']=='construction_failed' for e in group[3]['events']),'missing failure receipt'
 else:
  assert len(group[1]['receipts'])==9 and len(group[3]['receipts'])==11,(case,'family counts')
  for g in [group[1],group[3]]:
   assert 'PRIVATE-CANARY' not in json.dumps(g['receipts']),'do not leak refused environment'
  old={x['kind']:x for x in group[1]['receipts']};new={x['kind']:x for x in group[3]['receipts']}
  assert all(old[k]==new[k] for k in old),'preserve previous nine receipts'
  expected=1 if case in ['entry_nonfinite','losing_invalid_mode','write_blocked'] else group[0]['exit']
  assert group[3]['exit']==expected,(case,expected,group[3]['exit'])
 print(case+': four versions preserve decision/order/quantity',flush=True)
(j/'remaining_cli_results.json').write_text(json.dumps(results,indent=2,sort_keys=True))
print(json.dumps(dict(scenarios=len(cases),version_cases=len(cases)*4,policy_quantities_preserved=True)))
