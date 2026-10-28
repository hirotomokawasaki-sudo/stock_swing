"""Extra real CLI observations: no internal strategy/filter/executor mocks."""
from pathlib import Path
import json,shutil,subprocess,sys
j=Path(__file__).resolve().parent
cases={
    'normal':{},
    'sell_and_buy':dict(symbols='MSFT,NVDA',positions=[dict(symbol='NVDA',qty='1',market_value='50',current_price='50',avg_entry_price='200',unrealized_pl='-150',unrealized_plpc='-.75',asset_class='us_equity')]),
    'override':dict(env={'VOLATILITY_GATE_MAX_3M_STD_PCT':'3.25','SECTOR_SHOCK_BENCHMARK_SYMBOLS':'SMH,SOXX'}),
    'write_blocked':dict(block_config=True),
    'refused_mode':dict(env={'VOLATILITY_GATE_MODE':'PRIVATE-CANARY-NOT-A-CREDENTIAL'}),
    'nonfinite':dict(env={'VOLATILITY_GATE_MAX_3M_STD_PCT':'NaN'}),
}
results={}
for case,body in cases.items():
    for version in ['baseline','candidate_off','candidate_on']:
        root=j/'config_copies'/(version+'_'+case)
        if root.exists():raise ValueError('refuse reused copy')
        root.mkdir(parents=True)
        source=j/('baseline' if version=='baseline' else 'candidate')
        for name in ['src','config']:shutil.copytree(source/name,root/name)
        (root/'config/runtime/current_mode.yaml').write_text('mode: paper\n')
        (root/'config/guardrails/autonomous_stop.yaml').write_text('paper_warning_only: true\nrules: {}\n')
        p=root/'data/tracking/pnl_state.json';p.parent.mkdir(parents=True);p.write_text(json.dumps(dict(last_updated='2026-10-28T14:59:00+00:00',trades=[])))
        if body.get('block_config'):
            p=root/'reports/config_instances';p.parent.mkdir(parents=True);p.write_text('fixture write blocked')
        scenario=dict(body,config_capture=version=='candidate_on')
        (root/'scenario.json').write_text(json.dumps(scenario));shutil.copy2(j/'cli_driver.py',root/'driver.py')
        env=dict(PATH='/usr/bin:/bin',TZ='Asia/Tokyo',PYTHONPATH=str(root/'src'),PYTHONDONTWRITEBYTECODE='1',BROKER_API_KEY='fixture',BROKER_API_SECRET='fixture',BROKER_BASE_URL='https://paper-fixture.invalid',MASSIVE_API_KEY='fixture',**body.get('env',{}))
        run=subprocess.run(['/usr/bin/sandbox-exec','-f',str(j/'deny.sb'),sys.executable,'-B',str(root/'driver.py')],cwd=root,env=env,capture_output=True,text=True,timeout=65)
        (j/f'config_{version}_{case}.stdout').write_text(run.stdout)
        (j/f'config_{version}_{case}.stderr').write_text(run.stderr)
        assert run.returncode==0,(case,version,run.stderr[-1000:])
        data=json.loads(run.stdout)
        normalized_posts=[{k:v for k,v in p.items() if k!='client_order_id'} for p in data['posts']]
        instances=[r for r in data['effective_config'] if r['kind'].startswith('instance:')]
        results[version+'_'+case]=dict(main_exit=data['main_exit'],posts=normalized_posts,orders=data['orders'],business=data['business_decision_lines'],instances=instances,event_count=len(data['config_events']),recording_alert=any(a['code']=='config_instance_recording_unavailable' for a in data['alerts']))
    group=[results[v+'_'+case] for v in ['baseline','candidate_off','candidate_on']]
    for key in ['posts','orders','business']:
        assert group[0][key]==group[1][key]==group[2][key],(case,key)
    assert group[0]['main_exit']==group[1]['main_exit'],case
    assert not group[0]['instances'] and not group[1]['instances'],case
    assert len(group[2]['instances'])==9,(case,group[2])
    failed=case in {'write_blocked','refused_mode','nonfinite'}
    assert group[2]['main_exit']==(1 if failed else group[0]['main_exit']),(case,group[2])
    assert group[2]['recording_alert'] is failed,(case,group[2])
    # No canary value may be published in the allowlisted receipts.
    assert 'PRIVATE-CANARY' not in json.dumps(group[2]['instances']),case
    print(case,'3 versions: policy/quantity invariant, observation status verified',flush=True)
(j/'config_cli_results.json').write_text(json.dumps(results,indent=2,sort_keys=True))
