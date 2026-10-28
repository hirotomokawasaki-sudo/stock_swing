from pathlib import Path
import json,shutil,subprocess,sys
j=Path(__file__).parent;source=j/'code'
results={}
for version in ['baseline','candidate']:
 for scenario in ['missing','broken','empty','yaml_disabled','threshold_high','exit_missing','exit_null']:
  if version=='baseline' and scenario not in ['missing','broken','empty']:continue
  root=j/'cli_copies'/(version+'_'+scenario);root.mkdir(parents=True,exist_ok=True)
  shutil.copytree(source/'src',root/'src',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
  if version=='baseline':
   for p in (j/'baseline/src').rglob('*.py'):shutil.copy2(p,root/'src'/p.relative_to(j/'baseline/src'))
  shutil.copytree(source/'config',root/'config',dirs_exist_ok=True)
  (root/'config/runtime/current_mode.yaml').write_text('mode: paper\n')
  (root/'config/guardrails/autonomous_stop.yaml').write_text('paper_warning_only: true\nrules: {}\n')
  path=root/'data/tracking/pnl_state.json';path.parent.mkdir(parents=True,exist_ok=True)
  if scenario=='broken':path.write_text('{')
  if scenario in ['empty','yaml_disabled','threshold_high','exit_missing','exit_null']:path.write_text(json.dumps({'last_updated':'2026-10-28T14:59:00+00:00','trades':[]}))
  if scenario=='yaml_disabled':
   for name in ['breakout_momentum_v1','event_swing_v1']:
    (root/f'config/strategy/{name}.yaml').write_text('enabled: false\nmax_hold_days: 999\n')
  if scenario=='exit_missing': (root/'config/strategy/simple_exit_v2.yaml').rename(root/'config/strategy/simple_exit_v2.omitted')
  if scenario=='exit_null': (root/'config/strategy/simple_exit_v2.yaml').write_text('null\n')
  shutil.copyfile(j/'risk_cli_driver.py',root/'driver.py')
  if scenario=='threshold_high':
   p=root/'driver.py';p.write_text(p.read_text().replace("'--min-momentum','0.01'", "'--min-momentum','0.99'"))
  env={'PATH':'/usr/bin:/bin','TZ':'Asia/Tokyo','PYTHONPATH':str(root/'src'),'PYTHONDONTWRITEBYTECODE':'1',
       'BROKER_API_KEY':'fixture','BROKER_API_SECRET':'fixture','BROKER_BASE_URL':'https://paper-fixture.invalid','MASSIVE_API_KEY':'fixture'}
  command=['/usr/bin/sandbox-exec','-f',str(j/'deny.sb'),sys.executable,'-B',str(root/'driver.py')]
  run=subprocess.run(command,cwd=root,env=env,capture_output=True,text=True,timeout=40)
  (j/f'cli_{version}_{scenario}.stdout').write_text(run.stdout)
  (j/f'cli_{version}_{scenario}.stderr').write_text(run.stderr)
  if run.returncode:raise RuntimeError((version,scenario,run.stderr[-1000:]))
  data=json.loads(run.stdout);results[version+'_'+scenario]=data
  print(json.dumps({'version':version,'scenario':scenario,**{key:data.get(key) for key in ['main_exit','business_decision_lines','would_buy_lines','risk_lines','summary_risk','run_status','diagnostic_tail']}}),flush=True)
for kind in ['missing','broken']:
 assert len(results['baseline_'+kind]['would_buy_lines'])==1
 assert results['candidate_'+kind]['would_buy_lines']==[]
 assert results['candidate_'+kind]['summary_risk']['risk_budget_pct'] is None
 assert results['candidate_'+kind]['run_status']=='DEGRADED'
 assert results['candidate_'+kind]['funnel']['stages']['risk_budget_blocked']==1
 assert results['candidate_'+kind]['audit_block_recorded']
assert results['baseline_empty']['would_buy_lines']==results['candidate_empty']['would_buy_lines']
assert results['candidate_empty']['business_decision_lines']==results['candidate_yaml_disabled']['business_decision_lines']
assert results['candidate_threshold_high']['business_decision_lines']==[]
assert results['candidate_exit_missing']['main_exit']==0
assert results['candidate_exit_null']['main_exit']==99
assert all(d['origin_is_copy'] for d in results.values())
assert all(method=='GET' for d in results.values() for method,_ in d['http_calls'])
(j/'cli_results.json').write_text(json.dumps(results,indent=2))
