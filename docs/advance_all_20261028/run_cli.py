from pathlib import Path
import json,shutil,subprocess,sys
j=Path(__file__).parent
def pos(symbol='NVDA',value=50,qty='1',entry='200'):
 return dict(symbol=symbol,qty=qty,market_value=str(value),current_price=str(float(value)/float(qty)),avg_entry_price=entry,unrealized_pl='-150',unrealized_plpc='-.75',asset_class='us_equity')
exitpath='config/strategy/simple_exit_v2.yaml';allocpath='config/strategy/portfolio_allocation.yaml';regpath='config/reference/symbol_registry.yaml';intrapath='config/features/intraday_momentum.yaml'
base=dict(symbols='MSFT,NVDA',positions=[pos()])
scenarios={'normal':{},'sell_and_buy':base,
'lost_not_found':dict(symbols='MSFT,CRM',submit_timeout=True),'lost_found':dict(symbols='MSFT,CRM',submit_timeout=True,lookup_found=True),
'gap_candidate':dict(symbols='AVGO'),'gap_holding':dict(symbols='NVDA,MSFT',positions=[pos('AVGO',100,entry='100')]),
'gap_pending':dict(symbols='NVDA,MSFT',orders=[dict(id='pending-1',symbol='AVGO',side='buy',qty='1',filled_qty='0',type='market',status='new')])}
for name,body in dict(null='null',list='[]',broken='[',nan='stop_loss_pct: .nan',bad_bool='min_hold_days_enabled: "false"',missing=None).items():scenarios['exit_'+name]=dict(base,files={exitpath:body})
for name,body in dict(null='null',list='[]',nan='stock_new_buy_multiplier: .nan',bad_bool='portfolio: {use_projected_allocation: "false"}').items():scenarios['alloc_'+name]=dict(base,files={allocpath:body})
scenarios['registry_list']=dict(base,files={regpath:'[]'})
scenarios['intraday_null']=dict(base,intraday=True,files={intrapath:'null'})
result_file=j/'cli_results.json';results=json.loads(result_file.read_text()) if result_file.exists() else {}
for version in ['baseline','candidate']:
 for name,scenario in scenarios.items():
  if len(sys.argv)>1 and name not in sys.argv[1:]:continue
  root=j/'cli_copies'/(version+'_'+name)
  if root.exists():raise RuntimeError('refuse reused financial fixture '+str(root))
  root.mkdir(parents=True)
  for folder in ['src','config']:shutil.copytree(j/version/folder,root/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
  (root/'config/runtime/current_mode.yaml').write_text('mode: paper\n')
  (root/'config/guardrails/autonomous_stop.yaml').write_text('paper_warning_only: true\nrules: {}\n')
  path=root/'data/tracking/pnl_state.json';path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(dict(last_updated='2026-10-28T14:59:00+00:00',trades=[])))
  for rel,body in scenario.get('files',{}).items():
   path=root/rel
   if body is None:path.unlink()
   else:path.write_text(body)
  (root/'scenario.json').write_text(json.dumps(scenario));shutil.copy2(j/'cli_driver.py',root/'driver.py')
  env={'PATH':'/usr/bin:/bin','TZ':'Asia/Tokyo','PYTHONPATH':str(root/'src'),'PYTHONDONTWRITEBYTECODE':'1','BROKER_API_KEY':'fixture','BROKER_API_SECRET':'fixture','BROKER_BASE_URL':'https://paper-fixture.invalid','MASSIVE_API_KEY':'fixture'}
  if scenario.get('intraday'):env['PAPER_DEMO_USE_INTRADAY']='true'
  run=subprocess.run(['/usr/bin/sandbox-exec','-f',str(j/'deny.sb'),sys.executable,'-B',str(root/'driver.py')],cwd=root,env=env,capture_output=True,text=True,timeout=55)
  (j/f'cli_{version}_{name}.stdout').write_text(run.stdout);(j/f'cli_{version}_{name}.stderr').write_text(run.stderr)
  data=json.loads(run.stdout) if run.stdout.strip().startswith('{') else dict(main_exit=-1,posts=[],error=run.stderr[-1800:])
  results[version+'_'+name]=data;result_file.write_text(json.dumps(results,indent=2))
  print(json.dumps(dict(version=version,case=name,exit=data['main_exit'],posts=[(p['side'],p['symbol'],p['qty']) for p in data['posts']],orders=data.get('orders'),tail=data.get('diagnostic_tail',data.get('error',''))[-200:])),flush=True)
