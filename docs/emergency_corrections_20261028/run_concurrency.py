from pathlib import Path
import json,select,shutil,subprocess,sys
j=Path(__file__).resolve().parent;results={}
for version in ['baseline','candidate']:
 for label,script,symbol,qty in [('sell','emergency_sell.py','NOW','3'),('cover','close_hpe_short.py','HPE','-13')]:
  root=j/'concurrency_copies'/(version+'_'+label)
  if root.exists():raise RuntimeError('refuse reused concurrent fixture')
  root.mkdir(parents=True)
  for folder in ['src','scripts','config']:shutil.copytree(j/version/folder,root/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
  (root/'config/runtime/current_mode.yaml').write_text('mode: paper\n')
  (root/'scenario.json').write_text(json.dumps(dict(script=script,positions=[dict(symbol=symbol,qty=qty)],hold_after_accept=True)))
  shutil.copy2(j/'script_driver.py',root/'driver.py')
  env=dict(PATH='/usr/bin:/bin',TZ='Asia/Tokyo',PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(root/'src'),BROKER_API_KEY='fixture',BROKER_API_SECRET='fixture',BROKER_BASE_URL='https://paper-fixture.invalid')
  def command(n):return ['/usr/bin/sandbox-exec','-f',str(j/'deny.sb'),sys.executable,'-B',str(root/'driver.py'),str(n)]
  first=subprocess.Popen(command(0),cwd=root,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  try:
   ready=select.select([first.stdout],[],[],10)[0]
   if not ready:raise RuntimeError('acceptance barrier not reached')
   assert first.stdout.readline()==b'ACCEPTED_WAITING\n'
   second=subprocess.run(command(1),cwd=root,env=env,capture_output=True,text=True,timeout=20)
   if second.returncode:raise RuntimeError(second.stderr)
   second_data=json.loads(second.stdout)
  finally:first.kill();first.communicate(timeout=5)
  third=subprocess.run(command(2),cwd=root,env=env,capture_output=True,text=True,timeout=20)
  if third.returncode:raise RuntimeError(third.stderr)
  third_data=json.loads(third.stdout)
  posts=json.loads((root/'fixture_broker.json').read_text())['posts']
  results[version+'_'+label]=dict(killed_after_acceptance=True,second=second_data,restarted=third_data,posts=posts)
  expected=3 if version=='baseline' else 1
  assert len(posts)==expected,(version,label,posts)
  if version=='candidate':
   assert second_data['exit_code']==third_data['exit_code']==1
   assert not second_data['posts'] and not third_data['posts']
   assert any(r['reason']=='submission_guard_busy' for r in second_data['summary']['results'])
  print(json.dumps(dict(version=version,script=label,posts=len(posts),concurrent_exit=second_data['exit_code'],restart_exit=third_data['exit_code'])),flush=True)
(j/'concurrency_results.json').write_text(json.dumps(results,indent=2,sort_keys=True))
