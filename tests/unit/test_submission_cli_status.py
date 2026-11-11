"""FIX-02 2026-11-03/8909e79: unknown submit incorrectly exited 0.
Actual CLI/reader/broker classes; substitute only external HTTP and clock.
"""
from pathlib import Path
import json,shutil,subprocess,sys
import pytest

@pytest.mark.parametrize('mode,expected', [('normal',0),('unknown',1),('found',0),('dry',0)])
def test_ac_actual_cli_submission_result_and_capture_agree(tmp_path, mode, expected):
    source=Path(__file__).resolve().parents[2]
    for name in ['src','config']:
        shutil.copytree(source/name,tmp_path/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    (tmp_path/'config/runtime/current_mode.yaml').write_text('mode: paper\n')
    (tmp_path/'config/guardrails/autonomous_stop.yaml').write_text('paper_warning_only: true\nrules: {}\n')
    p=tmp_path/'data/tracking/pnl_state.json';p.parent.mkdir(parents=True)
    p.write_text(json.dumps(dict(last_updated='2026-10-28T14:59:00+00:00',trades=[])))
    scenario=dict(capture=True,config_capture=True,submit_timeout=mode in {'unknown','found'},lookup_found=mode=='found',dry_run=mode=='dry')
    (tmp_path/'scenario.json').write_text(json.dumps(scenario))
    shutil.copy2(source/'tests/fixtures/submission_cli_driver.py',tmp_path/'driver.py')
    env=dict(PATH='/usr/bin:/bin',TZ='Asia/Tokyo',PYTHONPATH=str(tmp_path/'src'),PYTHONDONTWRITEBYTECODE='1',BROKER_API_KEY='fixture',BROKER_API_SECRET='fixture',BROKER_BASE_URL='https://paper-fixture.invalid',MASSIVE_API_KEY='fixture')
    run=subprocess.run([sys.executable,'-B',str(tmp_path/'driver.py')],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=45)
    assert run.returncode==0,run.stderr
    result=json.loads(run.stdout)
    assert result['main_exit']==expected,'Unknown submission must not return successful process status'
    assert result['capture_complete'] is True,'Outcome failure must not erase intact engineering capture'
    assert result['declared_exit_success'] is (expected==0),'Capture reader must reflect process status separately from capture completeness'
    assert len(result['posts'])==(0 if mode=='dry' else 1),'No automatic POST retry even when lookup succeeds'
    if mode=='unknown':
        assert 'submission_outcome_unresolved' in result['full_stdout'],'Cron receipt must carry the unresolved reason'
        assert 'WARN unknown:' in result['full_stdout'],'Unknown outcome must not be presented as a rejection'
