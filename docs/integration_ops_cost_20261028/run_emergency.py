from pathlib import Path
import json,shutil,subprocess,sys
j=Path(__file__).resolve().parent

def position(symbol,qty):return dict(symbol=symbol,qty=qty,unrealized_pl='0',unrealized_plpc='0')
em='emergency_sell.py';short='close_hpe_short.py'
longs=[position('NOW','3'),position('IBM','2')];shorts=[position('HPE','-13')]
cases={
 'sell_normal':dict(script=em,positions=longs),
 'sell_flat':dict(script=em,positions=[]),
 'sell_zero_short':dict(script=em,positions=[position('NOW','0'),position('IBM','-2')]),
 'sell_missing_qty':dict(script=em,positions=[{'symbol':'NOW'}]),
 'sell_fractional':dict(script=em,positions=[position('NOW','3.7')]),
 'sell_bad_shape':dict(script=em,positions=[None]),
 'sell_bad_qty':dict(script=em,positions=[position('NOW','NaN')]),
 'sell_ack_lost':dict(script=em,positions=longs,ack_lost=True),
 'sell_ack_lost_repeat':dict(script=em,positions=longs,ack_lost=True,repeat=2),
 'sell_rejected':dict(script=em,positions=longs,reject=True),
 'sell_get401':dict(script=em,positions=longs,get_status=401),
 'short_normal':dict(script=short,positions=shorts),
 'short_flat':dict(script=short,positions=[]),
 'short_long':dict(script=short,positions=[position('HPE','13')]),
 'short_cancel':dict(script=short,positions=shorts,confirm='no'),
 'short_missing_qty':dict(script=short,positions=[{'symbol':'HPE'}]),
 'short_fractional':dict(script=short,positions=[position('HPE','-13.7')]),
 'short_bad_shape':dict(script=short,positions=[None]),
 'short_bad_qty':dict(script=short,positions=[position('HPE','NaN')]),
 'short_ack_lost':dict(script=short,positions=shorts,ack_lost=True),
 'short_ack_lost_repeat':dict(script=short,positions=shorts,ack_lost=True,repeat=2),
 'short_rejected':dict(script=short,positions=shorts,reject=True),
 'short_get401':dict(script=short,positions=shorts,get_status=401)}
results={}
for version in ['safety','integrated']:
 source=j/('safety' if version=='safety' else 'candidate')
 for name,scenario in cases.items():
  root=j/'emergency_copies'/(version+'_'+name)
  if root.exists():raise RuntimeError('refuse reused fixture')
  root.mkdir(parents=True)
  shutil.copytree(source/'src',root/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
  (root/'scripts').mkdir();shutil.copy2(source/'scripts'/scenario['script'],root/'scripts'/scenario['script'])
  shutil.copy2(j/'emergency_driver.py',root/'driver.py');(root/'scenario.json').write_text(json.dumps(scenario))
  env=dict(PATH='/usr/bin:/bin',TZ='Asia/Tokyo',PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(root/'src'),BROKER_API_KEY='fixture',BROKER_API_SECRET='fixture',BROKER_BASE_URL='https://paper-fixture.invalid')
  run=subprocess.run(['/usr/bin/sandbox-exec','-f',str(j/'deny.sb'),sys.executable,'-B',str(root/'driver.py')],cwd=root,env=env,capture_output=True,text=True,timeout=30)
  if run.returncode:raise RuntimeError(run.stderr[-1200:])
  data=json.loads(run.stdout);results[version+'_'+name]=data
  print(json.dumps(dict(version=version,case=name,posts=len(data['posts']),errors=[o['error'] for o in data['outcomes']])),flush=True)
(j/'emergency_results.json').write_text(json.dumps(results,indent=2,sort_keys=True))
# Assertions describe observed boundaries, including known uncorrected gaps.
for name in cases:assert results['safety_'+name]==results['integrated_'+name],name
for version in ['safety','integrated']:
 d=lambda n:results[version+'_'+n]
 assert [(p['symbol'],p['side'],p['qty']) for p in d('sell_normal')['posts']]==[('NOW','sell',3),('IBM','sell',2)]
 assert [(p['symbol'],p['side'],p['qty']) for p in d('short_normal')['posts']]==[('HPE','buy',13)]
 for n in ['sell_flat','sell_zero_short','sell_missing_qty','sell_bad_shape','sell_bad_qty','sell_get401','short_flat','short_long','short_cancel','short_missing_qty','short_bad_shape','short_bad_qty','short_get401']:assert not d(n)['posts'],n
 assert d('sell_fractional')['posts'][0]['qty']==3
 assert d('short_fractional')['posts'][0]['qty']==13
 assert len(d('sell_ack_lost')['posts'])==2 and d('sell_ack_lost')['outcomes'][0]['printed_complete']
 assert len(d('sell_ack_lost_repeat')['posts'])==4
 assert len(d('short_ack_lost')['posts'])==1 and d('short_ack_lost')['outcomes'][0]['error']
 assert len(d('short_ack_lost_repeat')['posts'])==2
 assert all('client_order_id' not in p for n in cases for p in d(n)['posts'])
 assert not any('by_client_order_id' in path for n in cases for method,path in d(n)['http_calls'])
(j/'emergency_summary.json').write_text(json.dumps(dict(cases=len(results),integration_outcomes_unchanged=True,single_attempt_per_submit=True,repeat_business_intent_prevention=False,sell_ack_loss_prints_complete=True,fractional_close_supported=False,production_orders=0),indent=2))
