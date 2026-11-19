"""Acceptance: Paper0.50/Shadow0.60, same sealed input, no order route."""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import json
import sys
import copy
import shutil
import subprocess
import pytest

ROOT=Path(__file__).parents[2]
spec=importlib.util.spec_from_file_location('strength_shadow_tested',ROOT/'scripts/entry_strength_shadow.py')
shadow=importlib.util.module_from_spec(spec);spec.loader.exec_module(shadow)
rspec=importlib.util.spec_from_file_location('strength_wrapper_tested',ROOT/'scripts/cron/run_gateway_command.py')
runner=importlib.util.module_from_spec(rspec);rspec.loader.exec_module(runner)
from stock_swing.experiments.decision_input_capture import DecisionInputRecorder
from stock_swing.experiments.candidate_input_capture import CandidateInputCapture
from stock_swing.feature_engine.base_feature import FeatureResult
from stock_swing.strategy_engine.breakout_momentum_strategy import BreakoutMomentumStrategy
from stock_swing.risk.pf_history_receipt import PFHistoryCapture
from stock_swing.risk.entry_filter import EntryFilterConfig,EntryFilterEngine

NOW=datetime(2026,11,18,15,tzinfo=timezone.utc)
RID='paper_demo-20261118T150000Z-fixture'


def capture(root, *, primary=.50, momentum=.10, flags=(), pf_loss=False, exit_code=0):
    recorder=DecisionInputRecorder(root,enabled=True,run_id=RID)
    cap=CandidateInputCapture(recorder,['TEST'],arguments=dict(min_momentum=.05,min_signal_strength=primary,timeframe='1Day',bar_limit=20))
    cap.fetched('TEST',15,'fixture',failed=False)
    features=[FeatureResult('price_momentum','TEST',NOW,dict(momentum=momentum,trend='bullish',bars_used=15),quality_flags=list(flags)),FeatureResult('macro_regime',None,NOW,dict(regime='expansion'))]
    signals=BreakoutMomentumStrategy(.05,primary).generate(features)
    cap.generation(features,set(),signals);cap.prioritized(signals)
    cfg=EntryFilterConfig();history=[dict(status='closed',symbol='TEST',pnl=-10,trade_id=f'fixture-{i}') for i in range(5)] if pf_loss else []
    decisions=[SimpleNamespace(decision_id='fixture-d',symbol=s.symbol,action=s.action,generated_at=NOW) for s in signals]
    pf=PFHistoryCapture(root=root,run_id=RID,experiment_config_hash='fixture',decisions=decisions,closed_trades=history,entry_config=cfg,etf_symbols=set(),observed_at=NOW)
    result=EntryFilterEngine(cfg).filter(decisions,{},history,set())
    recorder.observe('entry_filter_result',dict(pf_history_receipt=pf.finish(result)))
    cap.finalize()
    recorder.observe('run_end',dict(exit_code=exit_code,observations_before_end=recorder.committed,capture_failures=recorder.failures))
    ref=recorder.seal()
    return ref


@pytest.mark.parametrize('momentum,primary,reference',[(.07,0,0),(.10,1,0),(.13,1,1)])
def test_ac_actual_input_thresholds_and_immutable_restart(tmp_path,momentum,primary,reference):
    capture(tmp_path,momentum=momentum)
    result=shadow.build_strength_comparison(tmp_path,RID)
    assert len(result['arms']['paper_policy_050']['entry_passed_symbols'])==primary
    assert len(result['arms']['shadow_reference_060']['entry_passed_symbols'])==reference
    assert result['virtual_portfolio_PnL'] is None and not result['economic_qualified']
    ref=shadow.save_strength_comparison(tmp_path,result)
    before=(tmp_path/ref['path']).read_bytes()
    assert shadow.save_strength_comparison(tmp_path,result)==ref
    assert (tmp_path/ref['path']).read_bytes()==before
    assert shadow.load_strength_comparison(tmp_path,ref['path'])==result
    assert not (tmp_path/'data/tracking').exists()


def test_pf_rejection_is_preserved_not_released(tmp_path):
    capture(tmp_path,pf_loss=True)
    result=shadow.build_strength_comparison(tmp_path,RID)
    assert result['arms']['paper_policy_050']['entry_passed_symbols']==[]
    assert result['arms']['paper_policy_050']['entry_blocked'][0][1].startswith('rolling_pf_gate:')


@pytest.mark.parametrize('flags',[['stale_data'],['insufficient_bars'],['insufficient_price_data']])
def test_quality_does_not_become_shadow_candidate(tmp_path,flags):
    capture(tmp_path,flags=flags)
    assert shadow.build_strength_comparison(tmp_path,RID)['entry_added_050_symbols']==[]


@pytest.mark.parametrize('kind',['missing','corrupt','wrong_primary','ambiguous_identity'])
def test_bad_source_is_error_not_zero_success(tmp_path,kind):
    ref=capture(tmp_path,primary=.6 if kind=='wrong_primary' else .5)
    if kind=='missing':(tmp_path/ref).unlink()
    if kind=='corrupt':(tmp_path/ref).write_text('{}')
    with pytest.raises(Exception):shadow.build_strength_comparison(tmp_path,'../outside' if kind=='ambiguous_identity' else RID)
    assert not (tmp_path/shadow.FOLDER).exists()


@pytest.mark.parametrize('kind',['missing','corrupt','symlink','conflict','bad_ref'])
def test_result_reader_and_write_reject_bad_state(tmp_path,kind):
    capture(tmp_path);result=shadow.build_strength_comparison(tmp_path,RID)
    ref=shadow.save_strength_comparison(tmp_path,result);p=tmp_path/ref['path']
    if kind=='missing':p.unlink()
    elif kind=='corrupt':p.write_text('{}')
    elif kind=='symlink':
        target=tmp_path/'outside';p.rename(target);p.symlink_to(target)
    elif kind=='conflict':
        other=copy.deepcopy(result);other['requested_symbols']=999
        with pytest.raises(Exception):shadow.save_strength_comparison(tmp_path,other)
        assert shadow.load_strength_comparison(tmp_path,ref['path'])['requested_symbols']==1
        return
    with pytest.raises(Exception):shadow.load_strength_comparison(tmp_path,'../outside' if kind=='bad_ref' else ref['path'])


def test_failed_actual_exit_is_explicit_not_forged_success(tmp_path):
    capture(tmp_path,exit_code=1)
    assert shadow.build_strength_comparison(tmp_path,RID)['source_exit_success'] is False


@pytest.mark.parametrize('workflow',[{'status':'skipped'},{'status':'ok','dry_run':True}])
def test_wrapper_skipped_or_dry_has_no_shadow_io(tmp_path,workflow):
    assert runner.strength_shadow_diagnostic('',workflow,tmp_path)['status']=='not_run'
    assert list(tmp_path.iterdir())==[]


@pytest.mark.parametrize('text',['','CONSOLE_SUMMARY_JSON broken', 'CONSOLE_SUMMARY_JSON {}'])
def test_wrapper_missing_output_never_claims_success(tmp_path,text):
    result=runner.strength_shadow_diagnostic(text,dict(status='ok'),tmp_path)
    assert result['status']=='error' and result['retry_workflow'] is False


def test_shadow_error_does_not_repeat_actual_workflow(tmp_path):
    marker=tmp_path/'actual_calls'
    source=f"from pathlib import Path; p=Path({str(marker)!r}); p.write_text(p.read_text()+'x' if p.exists() else 'x'); print('CRON_SUMMARY_JSON=\"bad\"')"
    code,report=runner.run_logged([sys.executable,'-c',source],root=tmp_path,name='stock_swing_paper_demo_midday',entry_strength_shadow=True)
    assert code==1 and report['entry_strength_shadow']['status']=='error'
    assert marker.read_text()=='x'


def test_shadow_flag_cannot_apply_to_unrelated_job(tmp_path):
    with pytest.raises(ValueError):runner.run_logged(['never-execute'],root=tmp_path,name='other',entry_strength_shadow=True)


def test_v22_has_explicit_separate_source_bound_namespace(monkeypatch):
    from stock_swing.risk import entry_restriction_review as review
    monkeypatch.setenv('ENTRY_RESTRICTION_REVIEW_VERSION','v22')
    protocol,store=review._study()
    assert store.name=='entry_restriction_review_v22.json'
    assert protocol['primary_min_signal_strength']==.50
    definition=review._definition(protocol)
    assert 'cli/paper_demo.py' in definition['source_hashes']
    assert protocol['automatic_release'] is False


def test_own_child_cli_shadow_is_confined_and_replayable(tmp_path):
    """Own nested sandbox, run in the disjoint own_cli suite."""
    capture(tmp_path)
    (tmp_path/'data/analysis').mkdir(exist_ok=True)
    (tmp_path/'logs/gateway_workflows').mkdir(parents=True)
    text='CONSOLE_SUMMARY_JSON '+json.dumps({'run':{'run_id':RID,'dry_run':False}})
    result=runner.strength_shadow_diagnostic(text,dict(status='ok'),tmp_path)
    assert result['status']=='recorded', result
    assert result['primary_entry_count']==1 and result['shadow_entry_count']==0
    assert result['orders_submitted']==0 and not result['portfolio_PnL_available']
    assert runner.strength_shadow_diagnostic(text,dict(status='ok'),tmp_path)['sha256']==result['sha256']
    profile=next((tmp_path/'logs/gateway_workflows').glob('strength-shadow-*.sb'))
    # Attempt both a local socket and a financial/out-of-store write. A refused
    # connection without PermissionError would not prove network confinement.
    probe="""import socket,json,sys
from pathlib import Path
r={}
try: socket.create_connection(('127.0.0.1',9),timeout=.2);r['network']=False
except PermissionError:r['network']=True
except OSError:r['network']=False
try:Path(sys.argv[1]).write_text('forbidden');r['write']=False
except PermissionError:r['write']=True
print(json.dumps(r))
"""
    checked=subprocess.run(['/usr/bin/sandbox-exec','-f',str(profile),sys.executable,'-B','-c',probe,str(tmp_path/'finance_forbidden')],capture_output=True,text=True,check=True)
    assert json.loads(checked.stdout)==dict(network=True,write=True)


@pytest.mark.parametrize('strength,scenario,expected_posts',[(.50,{},1),(.60,{},0),(.50,{'state':'missing'},0),(.50,{'submit_timeout':True},1)])
def test_own_cli_actual_primary_and_guard_paths(tmp_path,strength,scenario,expected_posts):
    """Actual native CLI, generator/risk/executor; only HTTP and clock fixtures."""
    for name in ['src','config']:shutil.copytree(ROOT/name,tmp_path/name)
    (tmp_path/'config/runtime/current_mode.yaml').write_text('mode: paper\n')
    (tmp_path/'config/guardrails/autonomous_stop.yaml').write_text('paper_warning_only: true\nrules: {}\n')
    state=tmp_path/'data/tracking/pnl_state.json';state.parent.mkdir(parents=True)
    if scenario.get('state')!='missing':state.write_text(json.dumps(dict(last_updated='2026-10-28T14:59:00+00:00',trades=[])))
    (tmp_path/'scenario.json').write_text(json.dumps(dict(scenario,capture=True,config_capture=True)))
    driver=(ROOT/'tests/fixtures/k03_cli_driver.py').read_text()
    driver=driver.replace("'--min-momentum','0.01','--min-signal-strength','0.1'",f"'--min-momentum','0.05','--min-signal-strength','{strength}'")
    driver=driver.replace('close=100+i*1.6','close=100+i*0.55')
    (tmp_path/'driver.py').write_text(driver)
    profile=tmp_path/'cli.sb';profile.write_text('(version 1)\n(allow default)\n(deny network*)\n(deny file-write*)\n(allow file-write* (subpath '+json.dumps(str(tmp_path))+'))\n(allow file-write* (literal "/dev/null"))\n(deny file-read* (subpath '+json.dumps(str(ROOT))+'))\n')
    env=dict(PATH='/usr/bin:/bin',TZ='Asia/Tokyo',PYTHONPATH=str(tmp_path/'src'),PYTHONDONTWRITEBYTECODE='1',BROKER_API_KEY='fixture',BROKER_API_SECRET='fixture',BROKER_BASE_URL='https://paper-fixture.invalid',MASSIVE_API_KEY='fixture')
    done=subprocess.run(['/usr/bin/sandbox-exec','-f',str(profile),sys.executable,'-B',str(tmp_path/'driver.py')],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=35)
    assert done.returncode==0,done.stderr
    data=json.loads(done.stdout)
    assert data['origin_is_copy'] and len(data['posts'])==expected_posts,data.get('diagnostic_tail')
    if scenario.get('state')=='missing' or scenario.get('submit_timeout'):
        assert data['main_exit']==1
    else:assert data['main_exit']==0,data.get('diagnostic_tail')
