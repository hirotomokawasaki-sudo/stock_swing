"""Regression 2026-10-28/8909e79+timing candidate: gate configs unobserved."""
from dataclasses import asdict
import json
import pytest
from stock_swing.risk.config_instance_receipts import ConfigInstanceRecorder,instance_receipt
from stock_swing.risk.entry_filter import EntryFilterConfig,EntryFilterEngine,get_permanent_block_summary,get_small_sample_watchlist
from stock_swing.risk.losing_position_add_guard import LosingPositionAddGuardConfig

@pytest.mark.parametrize('cls',[EntryFilterConfig,LosingPositionAddGuardConfig])
def test_ac_consumed_gate_config_is_allowlisted_without_policy_change(tmp_path,cls):
 cfg=cls.from_env();before=asdict(cfg)
 receipt=instance_receipt(cfg,'paper_demo:'+cls.__name__)
 assert receipt['status']=='observed',receipt
 assert receipt['effective']==before,'record actual constructed values, not environment guesses'
 assert asdict(cfg)==before,'observation never changes gate policy'

def test_ac_entry_constructor_error_still_original_and_value_not_leaked(tmp_path,monkeypatch):
 monkeypatch.setenv('ENTRY_FILTER_MIN_VOLUME','PRIVATE-CANARY')
 r=ConfigInstanceRecorder(tmp_path,'fixture-run')
 with pytest.raises(ValueError,match='PRIVATE-CANARY'):r.construct(EntryFilterConfig)
 assert r.receipts[0]['status']=='construction_failed',r.receipts
 assert 'PRIVATE-CANARY' not in json.dumps(r.receipts),'persist exception type only'

def test_ac_entry_config_alias_and_lists_detected_without_reverting(tmp_path):
 r=ConfigInstanceRecorder(tmp_path,'fixture-run');cfg=r.construct(EntryFilterConfig)
 engine=EntryFilterEngine(cfg)
 assert engine.config is cfg,'filter consumes the exact same observed object'
 alias=engine.config;alias.pf_gate_skip_symbols.append('MSFT');alias.min_volume=123
 r.finalize();changed=[x for x in r.receipts if x['status']=='changed_since_capture']
 assert len(changed)==1 and changed[0]['effective']['pf_gate_skip_symbols']==['MSFT'],changed
 assert cfg.min_volume==123,'observer must not reverse consumer mutation'

@pytest.mark.parametrize('value',[['PRIVATE-CANARY-WITH-SECRET'],[True],['MSFT']*65,'MSFT'])
def test_ac_unsafe_entry_symbol_lists_not_recorded(value):
 receipt=instance_receipt(EntryFilterConfig(purchase_restricted_symbols=value),'paper_demo:EntryFilterConfig')
 assert receipt['status']=='unavailable' and receipt['effective'] is None,receipt
 assert 'PRIVATE-CANARY' not in json.dumps(receipt),'refused values never serialized'

def test_ac_losing_guard_records_effective_fallback_not_bad_environment(tmp_path,monkeypatch):
 monkeypatch.setenv('LOSING_POSITION_ADD_GUARD_MAX_LOSS_PCT','PRIVATE-CANARY')
 cfg=ConfigInstanceRecorder(tmp_path,'fixture-run').construct(LosingPositionAddGuardConfig)
 receipt=instance_receipt(cfg,'paper_demo:LosingPositionAddGuardConfig')
 assert receipt['effective']['max_existing_loss_pct']==-.03,'preserve existing fallback'
 assert 'PRIVATE-CANARY' not in json.dumps(receipt),'only effective safe scalar is observed'

def test_ac_entry_helpers_explicit_config_equals_existing_fallback(monkeypatch):
 for name in ['ENTRY_FILTER_STOCK_REDUCED','ENTRY_FILTER_DISABLED','ENTRY_FILTER_PF_GATE_SKIP_SYMBOLS']:
  monkeypatch.delenv(name,raising=False)
 cfg=EntryFilterConfig.from_env()
 for helper in [get_permanent_block_summary,get_small_sample_watchlist]:
  assert helper([],config=cfg)==helper([]),'explicit CLI config and helper default preserve behavior'
