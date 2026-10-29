"""New input auditor contracts; temporary copies only, no outcome study."""
from pathlib import Path
from datetime import datetime,timezone
import importlib.util,json,shutil
import pytest
p=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('input_audit',p/'audit_inputs.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

def seedrow(**kw):
 d=dict(status='closed',symbol='X',entry_time='2026-10-01T10:00:00+00:00',exit_time='2026-10-02T10:00:00+00:00',qty=100,entry_price=100,exit_price=101,pnl=100,execution_leg_id='leg');d.update(kw);return d

def test_quantization_is_diagnostic_not_economic_certification():
 rows=[seedrow(pnl=100.5),seedrow(execution_leg_id='second',pnl=200)]
 d=m.audit_seed({'quarantined_trades':[]},rows,datetime(2026,10,29,tzinfo=timezone.utc))
 assert d['closed_strict_2cent_formula_disagreement']==2
 assert d['formula_disagreement_possible_2dp_rounding']==1
 assert d['formula_disagreement_exceeds_2dp_rounding_bound']==1

@pytest.mark.parametrize('changes,key',[
 ({'qty':True},'closed_bad_numeric'),({'pnl':float('nan')},'closed_bad_numeric'),
 ({'entry_time':'2026-10-03T10:00:00+00:00'},'closed_reversed_time'),
 ({'entry_time':'2026-10-01T10:00:00'},'closed_missing_or_naive_clock'),
 ({'exit_time':'2026-11-01T10:00:00+00:00'},'closed_after_capture'),
 ({'execution_leg_id':None},'closed_missing_execution_leg_id')])
def test_seed_invalid_fields_remain_counted(changes,key):
 d=m.audit_seed({},[seedrow(**changes)],datetime(2026,10,29,tzinfo=timezone.utc))
 assert d[key]==1,'invalid evidence must not silently disappear'

def test_duplicate_leg_and_quarantine_overlap_counted_separately():
 rows=[seedrow(trade_id='t'),seedrow(trade_id='t'),dict(status='quarantined',trade_id='t')]
 d=m.audit_seed({'quarantined_trades':[dict(trade_id='t')]},rows,datetime(2026,10,29,tzinfo=timezone.utc))
 assert d['duplicate_nonempty_leg_ids']==1 and d['closed_id_in_separate_quarantine']==2
 assert d['inline_quarantine_matching_separate_id']==1

@pytest.mark.parametrize('kind',['missing','bytes','symlink'])
def test_input_integrity_rejects_before_native_import(tmp_path,kind):
 source=p/'audit_inputs';shutil.copytree(source,tmp_path/'inputs');root=tmp_path/'inputs';f=root/'seed.json'
 if kind=='missing':f.unlink()
 elif kind=='bytes':f.write_text('{}')
 else:f.unlink();f.symlink_to(source/'seed.json')
 with pytest.raises((ValueError,FileNotFoundError)):
  m.run(root,tmp_path/'nonexistent-source')
