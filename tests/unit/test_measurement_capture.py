"""Acceptance: optional candidate capture never certifies full replay (R22 10/21).

Regression baseline 777396f has no pre-filter durable candidate observation.
Only external I/O is replaced; storage, validation and publication are real.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from stock_swing.experiments.measurement_capture import (
    CaptureError, capture_candidates, load_capture,
)


def signal(symbol='ABC', strength=.8):
    return SimpleNamespace(symbol=symbol, strategy_id='breakout_momentum_v1',
                           action='buy', signal_strength=strength, confidence=.7,
                           notes='DO_NOT_SAVE_PRIVATE_TEXT', metadata={'api_key':'DO_NOT_SAVE_SECRET'})


def capture(root, **changes):
    options=dict(enabled=True, run_id='fixture-run', experiment_id='fixture-exp',
                 stage='generated_daily', observed_at=datetime(2026,10,21,14,tzinfo=timezone.utc),
                 signals=[signal('ABC'),signal('XYZ')], stale_symbols=['XYZ'],
                 cli_settings={'min_momentum':.05,'api_key':'DO_NOT_SAVE_SECRET'},
                 source_revision='fixture-revision')
    options.update(changes)
    return capture_candidates(root, **options)


def test_ac_disabled_is_no_io_even_with_invalid_values(tmp_path):
    assert capture(tmp_path, enabled=False, signals=None, observed_at=None) is None
    assert list(tmp_path.iterdir())==[], 'disabled means no directory creation'


def test_ac_roundtrip_order_allowlist_counts_and_unknowns(tmp_path):
    ref=capture(tmp_path); result=load_capture(tmp_path,ref)
    assert result['payload']['candidates']==[
        dict(ordinal=i,symbol=s,strategy_id='breakout_momentum_v1',action='buy',signal_strength=.8,confidence=.7)
        for i,s in enumerate(['ABC','XYZ'])]
    assert result['payload']['stale_symbols']==['XYZ']
    assert result['payload']['cli_settings']=={'min_momentum':.05}
    assert result['manifest']['scope']=='partial_candidate_measurement_not_F1'
    assert result['manifest']['full_replay_ready'] is False
    assert 'effective_config' in result['manifest']['missing_contract_sections']
    assert result['manifest']['et_calendar_date']=='2026-10-21'
    assert result['manifest']['exchange_session_certified'] is False
    assert 'DO_NOT_SAVE' not in ''.join(p.read_text() for p in tmp_path.rglob('*.json'))


def test_ac_retry_is_byte_identical_and_conflicting_identity_refused(tmp_path):
    ref=capture(tmp_path); before={p:p.read_bytes() for p in tmp_path.rglob('*.json')}
    assert capture(tmp_path)==ref
    with pytest.raises(CaptureError,match='conflict'):
        capture(tmp_path,signals=[signal('DIFFERENT')])
    assert {p:p.read_bytes() for p in before}==before


def test_ac_distinct_stages_and_empty_batch_are_observations(tmp_path):
    first=capture(tmp_path)
    second=capture(tmp_path,stage='prioritized_entry',signals=[])
    assert first!=second
    assert load_capture(tmp_path,second)['payload']['candidates']==[]


@pytest.mark.parametrize('changes',[
    {'run_id':'../../escape'}, {'run_id':''}, {'stage':'invented'},
    {'observed_at':datetime(2026,10,21)}, {'signals':None},
    {'signals':[signal(strength=float('nan'))]}, {'signals':[signal(strength=True)]},
    {'signals':[signal(strength=float('inf'))]}, {'signals':[signal(strength=1.5)]},
    {'signals':[signal('')]}, {'stale_symbols':'XYZ'},
    {'cli_settings':{'min_momentum':float('nan')}},
])
def test_ac_invalid_input_never_publishes(tmp_path,changes):
    with pytest.raises(CaptureError):capture(tmp_path,**changes)
    assert not list(tmp_path.rglob('manifests/*.json'))


@pytest.mark.parametrize('damage',['manifest_missing','manifest_json','blob_missing','blob_changed','traversal','unexpected_field'])
def test_ac_missing_corrupt_or_unsafe_dependency_refused(tmp_path,damage):
    ref=capture(tmp_path); manifest=tmp_path/ref
    saved=json.loads(manifest.read_bytes());blob=manifest.parent.parent/'blobs'/saved['payload_sha256']
    if damage=='manifest_missing':manifest.unlink()
    if damage=='manifest_json':manifest.write_text('{')
    if damage=='blob_missing':blob.unlink()
    if damage=='blob_changed':blob.write_bytes(blob.read_bytes()+b' ')
    if damage=='traversal':ref='../../secret'
    if damage=='unexpected_field':
        saved['full_replay_ready']=True;manifest.write_text(json.dumps(saved))
    with pytest.raises(CaptureError):load_capture(tmp_path,ref)


def test_ac_symlinked_storage_refused(tmp_path):
    outside=tmp_path/'elsewhere';outside.mkdir()
    folder=tmp_path/'data/audits';folder.mkdir(parents=True)
    (folder/'measurement_inputs').symlink_to(outside,target_is_directory=True)
    with pytest.raises(CaptureError):capture(tmp_path)
    assert list(outside.iterdir())==[]


def test_ac_parallel_same_identity_is_one_immutable_observation(tmp_path):
    with ThreadPoolExecutor(max_workers=4) as pool:refs=list(pool.map(lambda _:capture(tmp_path),range(8)))
    assert len(set(refs))==1
    assert len(list(tmp_path.rglob('manifests/*.json')))==1
    assert load_capture(tmp_path,refs[0])['manifest']['full_replay_ready'] is False


def test_ac_failed_publication_leaves_no_readable_observation(tmp_path,monkeypatch):
    import stock_swing.experiments.measurement_capture as module
    real=module.os.link
    def fail_manifest(source,destination):
        if Path(destination).parent.name=='manifests':raise OSError('injected manifest publication failure')
        return real(source,destination)
    monkeypatch.setattr(module.os,'link',fail_manifest)
    with pytest.raises(CaptureError):capture(tmp_path)
    assert not list(tmp_path.rglob('manifests/*.json'))
    monkeypatch.setattr(module.os,'link',real)
    assert load_capture(tmp_path,capture(tmp_path))['payload']['candidates'][0]['symbol']=='ABC'


def test_ac_process_death_after_blob_has_no_observation_then_clean_retry(tmp_path):
    code='''
from pathlib import Path
import os
from tests.unit.test_measurement_capture import capture
import stock_swing.experiments.measurement_capture as m
link=m.os.link
def interrupt(src,dst):
    if Path(dst).parent.name=='manifests':os._exit(73)
    return link(src,dst)
m.os.link=interrupt
capture(Path(os.environ['CAPTURE_FIXTURE_ROOT']))
'''
    process=subprocess.run([sys.executable,'-c',code],env={**os.environ,'CAPTURE_FIXTURE_ROOT':str(tmp_path)},capture_output=True,timeout=15)
    assert process.returncode==73
    assert not list(tmp_path.rglob('manifests/*.json'))
    result=load_capture(tmp_path,capture(tmp_path))
    assert result['manifest']['candidate_count']==2


def test_ac_missing_dependency_retry_refuses_instead_of_healing(tmp_path):
    ref=capture(tmp_path);record=load_capture(tmp_path,ref)
    (tmp_path/'data/audits/measurement_inputs/blobs'/record['manifest']['payload_sha256']).unlink()
    with pytest.raises(CaptureError):capture(tmp_path)


def test_ac_capture_does_not_change_caller_signals_or_trading_settings(tmp_path):
    candidates=[signal()];settings={'min_momentum':.05,'api_key':'DO_NOT_SAVE_SECRET'}
    prior=vars(candidates[0]).copy()
    capture(tmp_path,signals=candidates,cli_settings=settings)
    assert vars(candidates[0])==prior
    assert settings=={'min_momentum':.05,'api_key':'DO_NOT_SAVE_SECRET'}
