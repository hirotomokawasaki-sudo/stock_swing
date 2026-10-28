from pathlib import Path
import fcntl,hashlib,json,select,shutil,subprocess,sys
j=Path(__file__).resolve().parent

def pos(symbol,qty):return dict(symbol=symbol,qty=str(qty),unrealized_pl='0',unrealized_plpc='0')
def order(symbol,side):return dict(id='pending-fixture',symbol=symbol,side=side,type='market',qty='6',filled_qty='2',status='partially_filled')
scenarios={}
for label,script,symbol,qty,side in [('sell','emergency_sell.py','NOW',5,'sell'),('cover','close_hpe_short.py','HPE',-13,'buy')]:
 base=dict(script=script,positions=[pos(symbol,qty)])
 for name,extra in {
  'normal':{},'flat':dict(positions=[]),'opposite':dict(positions=[pos(symbol,-qty)]),
  'missing_qty':dict(positions=[dict(symbol=symbol)]),'nan_qty':dict(positions=[pos(symbol,'NaN')]),'bad_shape':dict(positions=[None]),
  'fractional':dict(positions=[pos(symbol,'-13.7' if qty<0 else '3.7')]),
  'pending_partial':dict(orders=[order(symbol,side)]),'pending_cancel':dict(orders=[dict(order(symbol,side),status='pending_cancel')]),
  'unknown_order_type':dict(orders=[dict(order(symbol,side),type=None)]),
  'unknown_replace_qty':dict(orders=[dict(order(symbol,side),status='pending_replace')]),
  'full_orders_page':dict(orders=[dict(order(symbol,side),id=str(i)) for i in range(500)]),
  'pending_opposite':dict(orders=[order(symbol,'buy' if side=='sell' else 'sell')]),
  'position_changed':dict(positions_after=[pos(symbol,qty+1)]),'orders_changed':dict(orders_after=[order(symbol,side)]),
  'ack_missing_repeat':dict(ack_lost=True,lookup='missing',repeat=2),'ack_found_repeat':dict(ack_lost=True,repeat=2),
  'lookup_mismatch':dict(ack_lost=True,lookup='mismatch',repeat=2),'accepted_repeat':dict(repeat=2),
  'http400_repeat':dict(post_status=400,repeat=2),'http422_repeat':dict(post_status=422,repeat=2),
  'terminal_rejected_repeat':dict(response_status='rejected',repeat=2),
  'malformed_ack_found':dict(malformed_ack=True),'get401':dict(get_status=401),
  'account_missing':dict(account=dict(status='ACTIVE')),'account_blocked':dict(account=dict(id='fixture-account',status='ACTIVE',trading_blocked=True)),
  'runtime_missing':dict(runtime=None),'runtime_research':dict(runtime='mode: research\n'),
  'journal_before_fsync':dict(fsync_failure='before'),'journal_after_fsync':dict(fsync_failure='after',repeat=2),
  'journal_missing_repeat':dict(damage='missing',repeat=2),'journal_partial_repeat':dict(damage='partial',repeat=2),
  'journal_marker_repeat':dict(damage='marker',repeat=2),'symlink_journal':dict(symlink=True),
  'busy_lock':dict(busy=True),'death_after_accept':dict(die_after_accept=True,repeat=2),
 }.items():scenarios[label+'_'+name]=dict(base,**extra) if not set(base)&set(extra) else {**base,**extra}
scenarios['cover_decline']=dict(script='close_hpe_short.py',positions=[pos('HPE',-13)],confirm='no')
scenarios['sell_independent_after_unknown']=dict(script='emergency_sell.py',positions=[pos('NOW',3),pos('IBM',2)],ack_lost=True,lookup='missing',repeat=2)
results={}
for version in ['baseline','candidate']:
 for name,s in scenarios.items():
  root=j/'script_copies'/(version+'_'+name)
  if root.exists():raise RuntimeError('refuse reused fixture')
  root.mkdir(parents=True)
  # Baseline is previous integrated closure, only scripts/helper differences are not applied.
  source=j/version
  for folder in ['src','scripts','config']:shutil.copytree(source/folder,root/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
  runtime=root/'config/runtime/current_mode.yaml'
  if s.get('runtime','mode: paper\n') is None:runtime.unlink()
  else:runtime.write_text(s.get('runtime','mode: paper\n'))
  (root/'scenario.json').write_text(json.dumps(s));shutil.copy2(j/'script_driver.py',root/'driver.py')
  if s.get('symlink'):
   (root/'data/tracking').mkdir(parents=True);(root/'elsewhere').mkdir();(root/'data/tracking/submission_intents').symlink_to(root/'elsewhere')
  lock=None
  if s.get('busy'):
   namespace=hashlib.sha256(json.dumps(['paper','https://paper-fixture.invalid','fixture-account']).encode()).hexdigest();path=root/('data/tracking/submission_intents/'+namespace+'.lock');path.parent.mkdir(parents=True,exist_ok=True);lock=path.open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  env=dict(PATH='/usr/bin:/bin',TZ='Asia/Tokyo',PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(root/'src'),BROKER_API_KEY='fixture',BROKER_API_SECRET='fixture',BROKER_BASE_URL='https://paper-fixture.invalid')
  rows=[]
  for iteration in range(s.get('repeat',1)):
   if iteration and s.get('damage'):
    logs=list((root/'data/tracking/submission_intents').glob('*.jsonl'))
    if logs:
     if s['damage']=='missing':logs[0].unlink()
     elif s['damage']=='partial':logs[0].write_bytes(logs[0].read_bytes()+b'{')
     else:logs[0].with_suffix('.initialized').unlink()
   process=subprocess.run(['/usr/bin/sandbox-exec','-f',str(j/'deny.sb'),sys.executable,'-B',str(root/'driver.py'),str(iteration)],cwd=root,env=env,capture_output=True,text=True,timeout=30)
   if process.returncode==73:rows.append(dict(abrupt_exit=73));continue
   if process.returncode:raise RuntimeError(process.stderr[-1200:])
   rows.append(json.loads(process.stdout))
  if lock:lock.close()
  all_posts=json.loads((root/'fixture_broker.json').read_text())['posts'] if (root/'fixture_broker.json').exists() else []
  results[version+'_'+name]=dict(runs=rows,all_posts=all_posts)
  print(json.dumps(dict(version=version,case=name,processes=len(rows),posts=len(all_posts),exit_codes=[r.get('exit_code',r.get('abrupt_exit')) for r in rows])),flush=True)
(j/'script_results.json').write_text(json.dumps(results,indent=2,sort_keys=True))
(j/'script_scenarios.json').write_text(json.dumps(scenarios,indent=2,sort_keys=True))
