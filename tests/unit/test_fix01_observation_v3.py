"""Regression FIX-01 2026-11-03 / base 8909e79: explicit post-clock namespace.
Acceptance: no repin/reset/mixing; corrupted, locked, unsupported paths fail closed.
All state I/O and definition logic is real, with temporary storage only.
"""
import copy
import fcntl
import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from pathlib import Path
import pytest
from stock_swing.risk import entry_restriction_review as r
from stock_swing.risk.entry_filter import EntryFilterConfig

NOW = datetime(2026,11,3,15,0,tzinfo=timezone.utc)

def capture(root, **kwargs):
    decision=SimpleNamespace(symbol='IBM', action='buy', decision_id='fix01-ibm',
        generated_at=NOW, strategy_id='fixture',strategy_version_id='fixture-v1',
        evidence={'pf_history_receipt': {'fixture':'receipt-preserved'}})
    return r.observe_restricted_entries(root=root, decisions=[decision],
        blocked=[('IBM','rolling_pf_gate: fixture')],stop_list=[{'symbol':'IBM'}],
        records_by_symbol={},entry_config=EntryFilterConfig(),run_id='fix01-fixture',
        config_hash='fixture-config',observed_at=NOW,**kwargs)

def saved(root):
    return json.loads((root/'data/analysis/entry_restriction_review_v3.json').read_text())

@pytest.fixture(autouse=True)
def explicit(monkeypatch):
    monkeypatch.setenv('ENTRY_RESTRICTION_REVIEW_VERSION','v3')
    monkeypatch.delenv('ENTRY_RESTRICTION_REVIEW_ENABLED',raising=False)

@pytest.mark.parametrize('version,path,protocol',[
    ('v1','entry_restriction_review_v1.json','pf-review-v1-20261028'),
    ('v2','entry_restriction_review_v2.json','pf-review-v2-20261029'),
    ('v3','entry_restriction_review_v3.json','pf-review-v3-20261103')])
def test_ac_explicit_selectors_keep_separate_fixed_paths(monkeypatch,version,path,protocol):
    monkeypatch.setenv('ENTRY_RESTRICTION_REVIEW_VERSION',version)
    p,n=r._study()
    assert n.name==path and p['version']==protocol,'explicit version must select only its own namespace'

def test_ac_new_namespace_preserves_old_bytes_and_keeps_bound_identity(tmp_path):
    folder=tmp_path/'data/analysis';folder.mkdir(parents=True)
    before={}
    retained=Path(__file__).resolve().parents[1]/'fixtures/observation_history'
    for version in ('v1','v2'):
        name=f'entry_restriction_review_{version}.json'
        before[name]=(retained/name).read_bytes();(folder/name).write_bytes(before[name])
    result=capture(tmp_path)
    assert result['status']=='observing' and result['observations']==1,result
    assert result['eligible_to_trade'] is False and result['automatic_release'] is False,result
    state=saved(tmp_path)['state'];item=state['observations'][0]
    assert len(state['observations'])==1 and item['decision_id']=='fix01-ibm','no inherited old observations'
    assert item['protocol']=='pf-review-v3-20261103' and item['study_definition_hash']==state['definition_hash'],'cohort must bind new definition'
    assert item['pf_history_receipt']=={'fixture':'receipt-preserved'},'PF receipt propagation must survive namespace transition'
    src=Path(r.__file__).resolve().parents[1]/'sources/massive_client.py'
    assert state['definition']['source_hashes']['sources/massive_client.py']==hashlib.sha256(src.read_bytes()).hexdigest(),'v3 binds epoch decoder bytes'
    assert all((folder/name).read_bytes()==data for name,data in before.items()),'historical stores must be byte-identical'
    frozen=(folder/'entry_restriction_review_v3.json').read_bytes()
    again=capture(tmp_path)
    assert again['observations']==1 and (folder/'entry_restriction_review_v3.json').read_bytes()==frozen,'repeated run must not inflate or reset'

@pytest.mark.parametrize('version',['v999','V3','../v3',''])
def test_ac_unknown_version_refuses_without_storage(tmp_path,monkeypatch,version):
    monkeypatch.setenv('ENTRY_RESTRICTION_REVIEW_VERSION',version)
    result=capture(tmp_path)
    assert result['status']=='error' and result['reason']=='unsupported_version',result
    assert not (tmp_path/'data').exists(),'unknown version cannot initialize state'

@pytest.mark.parametrize('case',['corrupt','wrong_definition','old_v2_in_new_path','clock_backwards'])
def test_ac_invalid_state_never_repins_or_resets(tmp_path,case):
    assert capture(tmp_path)['status']=='observing'
    path=tmp_path/'data/analysis/entry_restriction_review_v3.json'
    envelope=saved(tmp_path)
    if case=='corrupt': path.write_text('{broken')
    elif case=='old_v2_in_new_path':
        path.write_bytes((Path(__file__).resolve().parents[1]/'fixtures/observation_history/entry_restriction_review_v2.json').read_bytes())
    else:
        if case=='wrong_definition':
            envelope['state']['definition']['source_hashes']['sources/massive_client.py']='0'*64
            envelope['state']['definition_hash']=r._hash(envelope['state']['definition'])
        else: envelope['state']['last_observed_at']='2099-01-01T00:00:00+00:00'
        envelope['checksum']=r._hash(envelope['state']);path.write_text(json.dumps(envelope))
    before=path.read_bytes();result=capture(tmp_path)
    assert result['status']=='error' and result['candidates']==[],result
    assert path.read_bytes()==before,'failure must not rewrite or bless invalid prior state'

def test_ac_lock_defers_then_resumes_same_namespace(tmp_path):
    capture(tmp_path);path=tmp_path/'data/analysis/entry_restriction_review_v3.json'
    before=path.read_bytes()
    with path.with_suffix('.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        result=capture(tmp_path)
        assert result['status']=='error' and result['reason']=='BlockingIOError',result
        assert path.read_bytes()==before,'contention must not write state'
    assert capture(tmp_path)['status']=='observing','same explicit namespace must resume after contention'

@pytest.mark.parametrize('kwargs,status',[({'dry_run':True},'dry_run'),({'mode':'live'},'unsupported_mode')])
def test_ac_nonwriting_modes_do_not_initialize(tmp_path,kwargs,status):
    assert capture(tmp_path,**kwargs)['status']==status
    assert not (tmp_path/'data').exists(),'nonwriting mode must not create store'

def test_ac_disabled_does_not_initialize(tmp_path,monkeypatch):
    monkeypatch.setenv('ENTRY_RESTRICTION_REVIEW_ENABLED','false')
    assert capture(tmp_path)['status']=='disabled'
    assert not (tmp_path/'data').exists(),'disabled capture must not create store'
