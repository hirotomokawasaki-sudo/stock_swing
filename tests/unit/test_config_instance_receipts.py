"""Acceptance K04/K05: observations do not activate shadow policies."""
import importlib,json
from pathlib import Path
import pytest
from stock_swing.risk.config_instance_specs import SPECS
from stock_swing.risk.config_instance_receipts import instance_receipt,ConfigInstanceRecorder


@pytest.mark.parametrize('name',list(SPECS))
def test_ac_nine_constructed_config_families_are_exact_copies(name):
    cls=getattr(importlib.import_module(SPECS[name]['module']),name)
    cfg=cls.from_env();before=repr(cfg)
    result=instance_receipt(cfg,'paper_demo:'+name)
    assert result['status']=='observed',result
    assert set(result['effective'])==set(SPECS[name]['fields']),result
    assert repr(cfg)==before,'observing must not mutate strategy config'


def test_ac_override_presence_not_raw_environment(monkeypatch):
    from stock_swing.risk.volatility_gate import VolatilityGateConfig
    monkeypatch.setenv('VOLATILITY_GATE_MAX_3M_STD_PCT','3.25')
    monkeypatch.setenv('BROKER_API_SECRET','PRIVATE-CANARY-NOT-A-CREDENTIAL')
    result=instance_receipt(VolatilityGateConfig.from_env(),'paper_demo:VolatilityGateConfig')
    assert result['effective']['max_3m_return_std_pct']==3.25,result
    assert result['environment_keys_present']==['VOLATILITY_GATE_MAX_3M_STD_PCT'],result
    assert 'PRIVATE-CANARY' not in json.dumps(result),result


@pytest.mark.parametrize('value',[float('nan'),float('inf'),'PRIVATE-CANARY',None,True])
def test_ac_malformed_and_secret_like_values_are_not_serialized(value):
    from stock_swing.risk.volatility_gate import VolatilityGateConfig
    result=instance_receipt(VolatilityGateConfig(max_3m_return_std_pct=value),'paper_demo:VolatilityGateConfig')
    assert result['status']=='unavailable',result
    assert result['effective'] is None,result
    assert 'PRIVATE-CANARY' not in json.dumps(result),result


def test_ac_mode_secret_refused():
    from stock_swing.risk.volatility_gate import VolatilityGateConfig
    result=instance_receipt(VolatilityGateConfig(mode='PRIVATE-CANARY'),'paper_demo:VolatilityGateConfig')
    assert result['effective'] is None,result


def test_ac_missing_receipt_directory_created_and_json_persisted(tmp_path):
    from stock_swing.risk.volatility_gate import VolatilityGateConfig
    recorder=ConfigInstanceRecorder(tmp_path,'fixture-run')
    recorder.capture(VolatilityGateConfig(),'paper_demo:VolatilityGateConfig')
    event=json.loads((tmp_path/'reports/config_instances/fixture-run.jsonl').read_text())
    assert event['payload']==recorder.receipts[0],event
    assert recorder.failures==0,recorder.receipts


def test_ac_receipt_write_failure_is_explicit_not_a_config_mutation(tmp_path):
    from stock_swing.risk.volatility_gate import VolatilityGateConfig
    (tmp_path/'reports').write_text('fixture blocked')
    cfg=VolatilityGateConfig();before=repr(cfg);recorder=ConfigInstanceRecorder(tmp_path,'fixture-run')
    recorder.capture(cfg,'paper_demo:VolatilityGateConfig')
    assert recorder.failures==1,recorder.receipts
    assert recorder.receipts[0]['recorded'] is False,recorder.receipts
    assert repr(cfg)==before,'recording failure must not change decisions'
