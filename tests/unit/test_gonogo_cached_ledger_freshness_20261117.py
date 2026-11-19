"""Nov17 incident: cached VALID must not renew its own evidence date.

Real config/summary readers and report writer; no internal business mocks.
"""
from pathlib import Path
import importlib.util,json
from datetime import datetime,timezone
import pytest

def setup(root,config):
    script=Path(__file__).resolve().parents[2]/'scripts/check_go_no_go.py'
    spec=importlib.util.spec_from_file_location('freshness_gonogo',script)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    m.PROJECT_ROOT=root;m.CURRENT_MODE_PATH=root/'config/runtime/current_mode.yaml'
    m.CURRENT_MODE_PATH.parent.mkdir(parents=True)
    if config is not None:m.CURRENT_MODE_PATH.write_text(config)
    f=root/'reports/console/latest_console_summary.json';f.parent.mkdir(parents=True)
    f.write_text(json.dumps(dict(health=dict(ledger_gate_status='VALID'))))
    (root/'docs').mkdir()
    return m

@pytest.mark.parametrize('config',[None,'{broken', 'mode: paper\n',
    'mode: paper\nledger_quality_gate:\n  current_status: VALID\n  last_checked: "2026-09-14"\n',
    'mode: paper\nledger_quality_gate:\n  current_status: INVALID\n  last_checked: "'+datetime.now(timezone.utc).date().isoformat()+'"\n'])
def test_ac_stale_missing_invalid_evidence_is_not_renewed(tmp_path,config):
    m=setup(tmp_path,config);before=m.CURRENT_MODE_PATH.read_bytes() if config is not None else None
    result=m.check();assert result['ledger_quality']['pass'] is False
    m.format_report(result,save=True)
    assert (m.CURRENT_MODE_PATH.read_bytes() if m.CURRENT_MODE_PATH.exists() else None)==before

def test_ac_fresh_saved_config_and_matching_summary_is_evidence_only(tmp_path):
    text='mode: paper\nledger_quality_gate:\n  current_status: VALID\n  last_checked: "'+datetime.now(timezone.utc).date().isoformat()+'"\n'
    m=setup(tmp_path,text);before=m.CURRENT_MODE_PATH.read_bytes()
    assert m.check()['ledger_quality']['pass'] is True
    m._update_ledger_gate_last_checked(True,datetime.now(timezone.utc))
    assert m.CURRENT_MODE_PATH.read_bytes()==before

def test_ac_legacy_boolean_cannot_stamp_expired_config(tmp_path):
    m=setup(tmp_path,'mode: paper\nledger_quality_gate:\n  current_status: VALID\n  last_checked: "2026-09-14"\n')
    before=m.CURRENT_MODE_PATH.read_bytes()
    m._update_ledger_gate_last_checked(True,datetime.now(timezone.utc))
    assert m.CURRENT_MODE_PATH.read_bytes()==before
