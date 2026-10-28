from pathlib import Path
import json,shutil,subprocess,sys
j=Path(__file__).parent
driver=(j/'risk_cli_driver.py').read_text()
driver=driver.replace('calls=[]','calls=[]\nposts=[]\nscenario=json.loads((Path(__file__).parent/"scenario.json").read_text())')
driver=driver.replace("if request.url.path.endswith('/positions'):return httpx.Response(200,json=[])","if request.url.path.endswith('/positions'):return httpx.Response(200,json=scenario.get('positions',[]))")
driver=driver.replace("if 'orders' in request.url.path:return httpx.Response(200,json=[])",'''if 'orders' in request.url.path:
        if request.method=='POST':
            body=json.loads(request.content);posts.append(body)
            if scenario.get('submit_timeout'):
                raise httpx.ReadTimeout('fixture response lost after acceptance', request=request)
            return httpx.Response(200,json=dict(id='fixture-order-'+str(len(posts)),status='new',filled_qty='0',created_at='2026-10-28T15:00:00Z',**body))
        if request.url.path.endswith('/orders'):return httpx.Response(200,json=scenario.get('orders',[]))
        return httpx.Response(200,json=dict(id=request.url.path.rsplit('/',1)[-1],symbol='NVDA',side='buy',qty='1',status='new',filled_qty='0',created_at='2026-10-28T15:00:00Z'))''')
driver=driver.replace("'--symbols','NVDA','--dry-run'","'--symbols',scenario.get('symbols','NVDA')")
driver=driver.replace('paper_demo.datetime=FixtureClock','''paper_demo.datetime=FixtureClock
import stock_swing.feature_engine.earnings_event_feature as earnings_clock
earnings_clock.datetime=FixtureClock''')
driver=driver.replace("print(json.dumps(output,sort_keys=True,indent=2))",'''output['posts']=posts
output['preflight']=[json.loads(p.read_text()) for p in (root/'reports/order_preflight').glob('*.json')]
output['submission_lines']=[line.strip() for line in text_output.splitlines() if 'Submitting' in line or 'SKIP BUY' in line]
output['full_stdout']=text_output
print(json.dumps(output,sort_keys=True,indent=2))''')
(j/'cli_driver.py').write_text(driver)
pos=lambda value:dict(symbol='NOW',qty='100',market_value=str(value),current_price=str(value/100),avg_entry_price=str(value/100),unrealized_pl='0',unrealized_plpc='0',asset_class='us_equity')
pending=dict(id='pending-1',symbol='CRM',side='buy',qty='10',filled_qty='0',type='market',status='new',order_class='simple')
scenarios={
 'normal':{},
 'cluster':dict(symbols='MSFT',positions=[pos(34000)]),
 'pending':dict(symbols='MSFT',positions=[pos(30000)],orders=[pending]),
 'batch':dict(symbols='MSFT,CRM',positions=[pos(25000)]),
 'same_symbol_pending':dict(symbols='NVDA',orders=[dict(pending,symbol='NVDA')]),
 'order_page_unknown':dict(orders=[dict(pending,id=str(i)) for i in range(500)]),
 'response_lost':dict(symbols='MSFT,CRM',submit_timeout=True),
 'duplicate_buy':dict(earnings=True),
 'buy_sell_conflict':dict(positions=[dict(pos(50),symbol='NVDA',qty='1',avg_entry_price='200')]),
}
result_file=j/'cli_results.json'
results=json.loads(result_file.read_text()) if result_file.exists() else {}
for version in ['baseline','candidate']:
 for name,scenario in scenarios.items():
  if len(sys.argv)>1 and name not in sys.argv[1:]:continue
  root=j/'cli_copies'/(version+'_'+name)
  root.mkdir(parents=True,exist_ok=True)
  for folder in ['src','config']:
   shutil.copytree(j/version/folder,root/folder,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
  (root/'config/runtime/current_mode.yaml').write_text('mode: paper\n')
  (root/'config/guardrails/autonomous_stop.yaml').write_text('paper_warning_only: true\nrules: {}\n')
  path=root/'data/tracking/pnl_state.json';path.parent.mkdir(parents=True,exist_ok=True)
  path.write_text(json.dumps({'last_updated':'2026-10-28T14:59:00+00:00','trades':[]}))
  if scenario.get('earnings'):
   raw=root/'data/raw/finnhub/finnhub_earnings_calendar_fixture.json';raw.parent.mkdir(parents=True,exist_ok=True)
   raw.write_text(json.dumps(dict(source='finnhub',endpoint='calendar/earnings',fetched_at='2026-10-28T14:59:00+00:00',payload=dict(earningsCalendar=[dict(symbol='NVDA',date='2026-11-02',hour='amc',quarter=3,year=2026)]))))
  (root/'scenario.json').write_text(json.dumps(scenario))
  (root/'driver.py').write_text(driver)
  env={'PATH':'/usr/bin:/bin','TZ':'Asia/Tokyo','PYTHONPATH':str(root/'src'),'PYTHONDONTWRITEBYTECODE':'1',
       'BROKER_API_KEY':'fixture','BROKER_API_SECRET':'fixture','BROKER_BASE_URL':'https://paper-fixture.invalid','MASSIVE_API_KEY':'fixture'}
  run=subprocess.run(['/usr/bin/sandbox-exec','-f',str(j/'deny.sb'),sys.executable,'-B',str(root/'driver.py')],cwd=root,env=env,capture_output=True,text=True,timeout=50)
  (j/f'cli_{version}_{name}.stdout').write_text(run.stdout)
  (j/f'cli_{version}_{name}.stderr').write_text(run.stderr)
  if run.returncode:raise RuntimeError((version,name,run.stderr[-2000:]))
  data=json.loads(run.stdout);results[version+'_'+name]=data
  print(json.dumps(dict(version=version,scenario=name,exit=data['main_exit'],posts=data['posts'],preflight=data['preflight'],tail=data['diagnostic_tail'][-500:])),flush=True)
(j/'cli_results.json').write_text(json.dumps(results,indent=2))
