from pathlib import Path
import ast,json,shutil,subprocess,sys
j=Path(__file__).resolve().parent
node=ast.parse((j/'candidate/tests/unit/test_cancellation_timing.py').read_text())
rows=next(ast.literal_eval(n.value) for n in node.body if isinstance(n,ast.Assign) and any(isinstance(x,ast.Name) and x.id=='CASES' for x in n.targets))
rows += [('main','2026-07-08T17:00:00Z','2026-07-08T16:00:00',False),('main','2026-07-08T17:00:00Z','2026-07-09T16:00:00Z',False)]
results={}
for i,(entry,now,submitted,expected) in enumerate(rows):
 for version in ['baseline','candidate']:
  root=j/'timing_copies'/f'{version}_{i}';root.mkdir(parents=True)
  for name in ['src','config','scripts']:shutil.copytree(j/version/name,root/name)
  (root/'config/runtime/current_mode.yaml').write_text('mode: paper\n')
  p=root/'data/tracking/pnl_state.json';p.parent.mkdir(parents=True);p.write_text(json.dumps(dict(last_updated='2026-10-28T14:59:00+00:00',trades=[])))
  (p.parent/'pending_exit_reasons.json').write_text(json.dumps({'fixture-order':dict(symbol='AMD',exit_reason='stop_loss',return_pct=-.07)}))
  (root/'scenario.json').write_text(json.dumps(dict(entry=entry,now=now,submitted=submitted,after='canceled')))
  shutil.copy2(j/'timing_driver.py',root/'driver.py')
  env=dict(PATH='/usr/bin:/bin',TZ='Asia/Tokyo',PYTHONPATH=str(root/'src'),PYTHONDONTWRITEBYTECODE='1',BROKER_API_KEY='fixture',BROKER_API_SECRET='fixture')
  run=subprocess.run(['/usr/bin/sandbox-exec','-f',str(j/'deny.sb'),sys.executable,'-B',str(root/'driver.py')],cwd=root,env=env,capture_output=True,text=True,timeout=60)
  (j/f'timing_{version}_{i}.stderr').write_text(run.stderr)
  data=json.loads(run.stdout) if run.returncode==0 else dict(process_exit=run.returncode,exception=run.stderr.strip().splitlines()[-1].split(':')[0])
  calls=[json.loads(x) for x in (root/'http_calls.jsonl').read_text().splitlines()]
  value=dict(entry=entry,now=now,submitted=submitted,expected_delete=int(expected),delete_count=sum(x[0]=='DELETE' for x in calls),post_count=sum(x[0]=='POST' for x in calls),process_exit=run.returncode)
  if run.returncode==0:value.update(result=data['result'],exit_reason_present=data['exit_reason_present'])
  results[f'{version}_{i}']=value
  if version=='candidate':
   assert run.returncode==0,(i,value,run.stderr[-1000:])
   assert value['delete_count']==int(expected) and value['post_count']==0,value
   if entry=='main':assert data['result']==1,value
 print(i,'baseline/candidate time case verified',flush=True)
(j/'timing_path_results.json').write_text(json.dumps(results,indent=2,sort_keys=True))
print(json.dumps(dict(version_cases=len(results),fresh_processes=len(results),baseline_delete_disagreements=sum(results['baseline_'+str(i)]['delete_count']!=int(row[3]) for i,row in enumerate(rows)),candidate_delete_disagreements=0)))
