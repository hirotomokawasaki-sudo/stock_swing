"""Regression 2026-10-28/8909e79: failed/skipped constructors were invisible."""
import json
from dataclasses import FrozenInstanceError
import pytest
from stock_swing.risk.config_instance_receipts import ConfigInstanceRecorder
from stock_swing.risk.volatility_gate import VolatilityGateConfig
from stock_swing.risk.config_instance_specs import SPECS

def events(root):
 p=root/'reports/config_instances/fixture-run.jsonl'
 return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

def test_ac_constructor_failure_persisted_without_error_value(tmp_path):
 r=ConfigInstanceRecorder(tmp_path,'fixture-run')
 class Failure(VolatilityGateConfig):
  pass
 # Real factory error is an external constructor test seam, not an altered CLI policy.
 def fail():raise ValueError('PRIVATE-CANARY-DO-NOT-RECORD')
 with pytest.raises(ValueError,match='PRIVATE-CANARY'):
  r.construct(VolatilityGateConfig,factory=fail)
 assert r.failures==1,r.receipts
 assert r.receipts[0]['status']=='construction_failed',r.receipts
 assert r.receipts[0]['recorded'] is True,r.receipts
 assert 'PRIVATE-CANARY' not in json.dumps(events(tmp_path)),events(tmp_path)

def test_ac_finalize_records_unreached_without_instantiating(tmp_path):
 r=ConfigInstanceRecorder(tmp_path,'fixture-run');r.construct(VolatilityGateConfig);r.finalize()
 assert len(r.receipts)==11,r.receipts
 skipped=[x for x in r.receipts if x['status']=='not_reached']
 assert len(skipped)==10 and all(x['effective'] is None for x in skipped),r.receipts
 assert r.failures==0,r.receipts
 before=events(tmp_path);r.finalize();assert events(tmp_path)==before,'finalization must be idempotent'

def test_ac_mutation_detected_without_changing_effective_instance(tmp_path):
 r=ConfigInstanceRecorder(tmp_path,'fixture-run');cfg=r.construct(VolatilityGateConfig)
 object.__setattr__(cfg,'max_3m_return_std_pct',4.25)
 r.finalize();changed=[x for x in r.receipts if x['status']=='changed_since_capture']
 assert len(changed)==1 and changed[0]['effective']['max_3m_return_std_pct']==4.25,r.receipts
 assert cfg.max_3m_return_std_pct==4.25,'observer must not undo override'
 assert r.failures==1,r.receipts

def test_ac_secret_like_mutation_never_serialized(tmp_path):
 r=ConfigInstanceRecorder(tmp_path,'fixture-run');cfg=r.construct(VolatilityGateConfig)
 object.__setattr__(cfg,'mode','PRIVATE-CANARY-DO-NOT-RECORD');r.finalize()
 assert r.failures==1,r.receipts
 assert 'PRIVATE-CANARY' not in json.dumps(events(tmp_path)),events(tmp_path)

def test_ac_failed_write_preserves_original_constructor_error(tmp_path):
 (tmp_path/'reports').write_text('blocked')
 r=ConfigInstanceRecorder(tmp_path,'fixture-run')
 def fail():raise KeyError('private-value')
 with pytest.raises(KeyError):r.construct(VolatilityGateConfig,factory=fail)
 assert r.failures>=1 and r.receipts[0]['recorded'] is False,r.receipts
