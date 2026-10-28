"""Acceptance: actual opt-in CLI callsite -> persistence -> normal run reader."""
from datetime import datetime,timezone
import hashlib,json,os,shutil,subprocess,sys
from pathlib import Path
import pytest

def launch_copy(source_root,root,*,enabled,zone='UTC',missing_env=False,blocked_capture=False):
    source_root=Path(source_root);root=Path(root);root.mkdir(parents=True)
    shutil.copytree(source_root/'src',root/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    driver=source_root/'tests/fixtures/provider_contract_cli_driver.py'
    shutil.copyfile(driver,root/'driver.py')
    for p in (source_root/'src').rglob('*.py'):
        assert hashlib.sha256(p.read_bytes()).digest()==hashlib.sha256((root/p.relative_to(source_root)).read_bytes()).digest()
    for name,text in {'config/runtime/current_mode.yaml':'mode: paper\n',
        'config/guardrails/autonomous_stop.yaml':'paper_warning_only: true\nrules: {}\n'}.items():
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
    path=root/'data/guardrails/day_start_snapshot.json';path.parent.mkdir(parents=True)
    now=datetime.now(timezone.utc)
    path.write_text(json.dumps(dict(market_date=now.date().isoformat(),captured_at=now.isoformat(),source='controlled_fixture_baseline',day_start_equity=100000.,day_start_unrealized=0.,missing_fields=[])))
    env=dict(PATH=os.environ.get('PATH','/usr/bin:/bin'),PYTHONPATH=str(root/'src'),PYTHONDONTWRITEBYTECODE='1',
             TZ=zone,BROKER_API_KEY='fixture',BROKER_API_SECRET='fixture',BROKER_BASE_URL='https://paper-fixture.invalid',
             MASSIVE_API_KEY='fixture',FIXTURE_RECORDING='1' if enabled else '0')
    if blocked_capture:
        blocked=root/'data/audits/measurement_inputs';blocked.parent.mkdir(parents=True);blocked.write_text('blocked')
    if missing_env:del env['BROKER_API_KEY']
    process=subprocess.run([sys.executable,'-B',str(root/'driver.py')],env=env,cwd=root,capture_output=True,text=True,timeout=40)
    assert process.returncode==0,process.stderr[-1500:]
    result=json.loads(process.stdout);result['driver_exit']=process.returncode
    return result

@pytest.mark.parametrize('zone',['UTC','Asia/Tokyo'])
def test_ac_actual_cli_off_on_same_decisions_http_and_no_trades(tmp_path,zone):
    source=Path(__file__).resolve().parents[2]
    off=launch_copy(source,tmp_path/'off',enabled=False,zone=zone)
    on=launch_copy(source,tmp_path/'on',enabled=True,zone=zone)
    assert off['main_exit']==on['main_exit']==0,(off,on)
    assert off['http_calls']==on['http_calls']
    assert off['business_decision_lines']==on['business_decision_lines']
    assert all(method=='GET' for method,_ in on['http_calls'])
    assert off['origin_is_copy'] and on['origin_is_copy']
    assert not off['store_exists'] and on['indices']==1
    assert on['capture_complete'] and on['declared_exit_success']
    assert on['stage_counts']['provider_response']==2 and on['stage_counts']['canonical_provider_bars']==1
    assert on['full_replay_ready'] is False


def test_ac_missing_env_sealed_run_is_not_application_success(tmp_path):
    result=launch_copy(Path(__file__).resolve().parents[2],tmp_path/'copy',enabled=True,missing_env=True)
    assert result['driver_exit']==0 and result['main_exit']==1
    assert result['capture_complete'] and not result['declared_exit_success']
    assert result['http_calls']==[] and result['stage_counts']=={'run_end':1}


def test_ac_failed_capture_keeps_business_output_but_refuses_success(tmp_path):
    source=Path(__file__).resolve().parents[2]
    off=launch_copy(source,tmp_path/'off',enabled=False)
    on=launch_copy(source,tmp_path/'on',enabled=True,blocked_capture=True)
    assert off['main_exit']==0 and on['main_exit']==1
    assert off['http_calls']==on['http_calls']
    assert off['business_decision_lines']==on['business_decision_lines']
    assert on['indices']==0
