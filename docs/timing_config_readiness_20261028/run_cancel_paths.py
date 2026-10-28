from pathlib import Path
import json,shutil,subprocess,sys
j=Path(__file__).resolve().parent
cases={}
for entry in ['buy','sell','manual']:
    for after,filled in [('pending_cancel','0'),('canceled','0'),('canceled','2'),('filled','5'),('404','0')]:
        cases[entry+'_'+after+'_'+filled]=dict(entry=entry,after=after,filled=filled)
cases['main_pending']=dict(entry='main',after='pending_cancel')
cases['manual_preview']=dict(entry='manual',after='pending_cancel',preview=True)
cases['manual_lost_restart']=dict(entry='manual',after='404',lost=True,restart=True)
cases['manual_death_restart']=dict(entry='manual',after='new',die=True,restart=True)
results={}
for case,scenario in cases.items():
    for version in ['baseline','candidate']:
        root=j/'cancel_copies_final'/(version+'_'+case)
        if root.exists():raise ValueError('refuse reused copy')
        root.mkdir(parents=True)
        for name in ['src','config','scripts']:shutil.copytree(j/version/name,root/name)
        (root/'config/runtime/current_mode.yaml').write_text('mode: paper\n')
        p=root/'data/tracking/pnl_state.json';p.parent.mkdir(parents=True);p.write_text(json.dumps(dict(last_updated='2026-10-28T14:59:00+00:00',trades=[])))
        (p.parent/'pending_exit_reasons.json').write_text(json.dumps({'fixture-order':dict(symbol='AMD',exit_reason='breakeven_stop',return_pct=-.07)}))
        (root/'scenario.json').write_text(json.dumps(scenario));shutil.copy2(j/'cancel_driver.py',root/'driver.py')
        env=dict(PATH='/usr/bin:/bin',TZ='Asia/Tokyo',PYTHONPATH=str(root/'src'),PYTHONDONTWRITEBYTECODE='1',BROKER_API_KEY='fixture',BROKER_API_SECRET='fixture')
        outcomes=[]
        for attempt in range(2 if scenario.get('restart') else 1):
            run=subprocess.run(['/usr/bin/sandbox-exec','-f',str(j/'deny.sb'),sys.executable,'-B',str(root/'driver.py')],cwd=root,env=env,capture_output=True,text=True,timeout=50)
            (j/f'cancel_{version}_{case}_{attempt}.stdout').write_text(run.stdout)
            (j/f'cancel_{version}_{case}_{attempt}.stderr').write_text(run.stderr)
            outcomes.append(json.loads(run.stdout) if run.returncode==0 else dict(process_exit=run.returncode))
        calls=[json.loads(line) for line in (root/'http_calls.jsonl').read_text().splitlines()]
        results[version+'_'+case]=dict(outcomes=outcomes,delete_count=sum(v[0]=='DELETE' for v in calls),post_count=sum(v[0]=='POST' for v in calls))
    old,new=(results[v+'_'+case] for v in ['baseline','candidate'])
    assert new['post_count']==0,(case,new)
    assert new['delete_count']==(0 if scenario.get('preview') else 1),(case,new)
    assert old['delete_count']==new['delete_count'],(case,old,new)
    if scenario['entry']=='sell':
        assert new['outcomes'][0]['exit_reason_present'] is not (scenario['after']=='canceled' and scenario.get('filled')=='0'),(case,new)
        assert old['outcomes'][0]['exit_reason_present']==new['outcomes'][0]['exit_reason_present'],(case,old,new)
    if case=='main_pending':
        assert old['outcomes'][0]['result']==1 and new['outcomes'][0]['result']==1,(case,old,new)
        assert '"cancelled_stale_sell_orders": 0' in new['outcomes'][0]['output'],new
    print(case,'baseline/candidate complete',flush=True)
(j/'cancel_path_results.json').write_text(json.dumps(results,sort_keys=True,indent=2))
