from datetime import datetime, timezone
from pathlib import Path
import json
import pytest

from stock_swing.experiments.candidate_input_capture import CandidateInputCapture, load_candidate_inputs, observe_quote_response
from stock_swing.experiments.decision_input_capture import DecisionInputRecorder, load_input_run
from stock_swing.experiments.measurement_capture import CaptureError
from stock_swing.feature_engine.base_feature import FeatureResult
from stock_swing.strategy_engine.base_strategy import CandidateSignal
from stock_swing.sources.bar_contract import record_bar_response

NOW = datetime(2026, 11, 2, 14, 35, 5, tzinfo=timezone.utc)

def seal(r):
    r.observe('run_end', dict(exit_code=int(bool(r.failures)), observations_before_end=r.committed, capture_failures=r.failures), observed_at=NOW)
    return r.seal()

def feature(s, flags=None):
    return FeatureResult('price_momentum', s, NOW, dict(momentum=0, trend='flat'), quality_flags=flags or [])

def test_real_denominator_not_inferred_from_orders(tmp_path):
    r=DecisionInputRecorder(tmp_path,enabled=True,run_id='test')
    c=CandidateInputCapture(r, ['FLAT','BUY','ERROR','STALE','SHORT','MISSING'], arguments={})
    for s in c.symbols: c.fetched(s, 20, 'fixture', failed=s=='ERROR')
    signal=CandidateSignal(strategy_id='breakout_momentum_v1',symbol='BUY',action='buy',signal_strength=.8,generated_at=NOW,time_horizon='2d',confidence=.8,reasoning='fixture',feature_refs=[])
    c.generation([feature('FLAT'),feature('BUY'),feature('SHORT',['insufficient_bars'])], {'STALE'}, [signal])
    c.prioritized([]);c.finalize();c.finalize()
    result=load_candidate_inputs(tmp_path,seal(r))
    assert [x['status'] for x in result['rows']]==['no_signal','signals_generated','input_error','upstream_excluded','upstream_excluded','upstream_excluded']
    assert all(x['missing_quote'] and x['missing_prior_1min'] for x in result['execution_inputs'])
    assert result['capture_complete'] and not result['full_replay_ready']

def test_early_finish_is_not_no_signal(tmp_path):
    r=DecisionInputRecorder(tmp_path,enabled=True,run_id='early')
    c=CandidateInputCapture(r,['A','B'],arguments={});c.fetched('A',0,'failed',failed=True);c.finalize()
    d=load_candidate_inputs(tmp_path,seal(r))
    assert [x['status'] for x in d['rows']]==['input_error','not_reached']

@pytest.mark.parametrize('interval,adjustment,bar_t,receipt,volume,expected',[
    ('1Min','raw','2026-11-02T14:34:00Z','2026-11-02T14:35:00Z',200,200),
    ('1Min','raw','2026-11-02T14:34:00Z','2026-11-02T14:35:00Z',0,0),
    ('5Min','raw','2026-11-02T14:34:00Z','2026-11-02T14:35:00Z',200,None),
    ('1Min','split','2026-11-02T14:34:00Z','2026-11-02T14:35:00Z',200,None),
    ('1Min','raw','2026-11-02T14:35:00Z','2026-11-02T14:35:00Z',200,None),
    ('1Min','raw','2026-11-02T14:33:00Z','2026-11-02T14:35:00Z',200,None),
    ('1Min','raw','2026-11-02T14:34:00Z','2026-11-02T14:35:06Z',200,None),
    ('1Min','raw','2026-11-02T14:34:00Z','2026-11-02T14:35:00Z',-1,None),
])
def test_consumed_quote_prior_completed_bar_and_clock(tmp_path,interval,adjustment,bar_t,receipt,volume,expected):
    r=DecisionInputRecorder(tmp_path,enabled=True,run_id='pair')
    c=CandidateInputCapture(r,['A'],arguments={});c.finalize()
    record_bar_response(r,provider='fixture',request=dict(symbol='A',interval=interval,adjustment=adjustment),response=dict(bars=[dict(t=bar_t,v=volume)]),received_at=datetime.fromisoformat(receipt.replace('Z','+00:00')))
    observe_quote_response(r,symbol='A',provider='fixture',payload=dict(quote=dict(bp=100,ap=101,t=NOW.isoformat())),raw_bytes=b'fixture',received_at=NOW)
    a=load_candidate_inputs(tmp_path,seal(r))['execution_inputs'][0]['quotes'][0]
    assert a['prior_completed_raw_1min_volume']==expected
    assert a['locally_observed_pair']==(expected is not None)

@pytest.mark.parametrize('kind',['missing','corrupt','symlink'])
def test_normal_reader_refuses_broken_dependencies(tmp_path,kind):
    r=DecisionInputRecorder(tmp_path,enabled=True,run_id='broken');c=CandidateInputCapture(r,['A'],arguments={});c.finalize();ref=seal(r)
    run=load_input_run(tmp_path,ref);blob=tmp_path/'data/audits/measurement_inputs/blobs'/run['observations'][0]['manifest']['payload_sha256']
    if kind=='missing':blob.unlink()
    elif kind=='corrupt':blob.write_bytes(b'{}')
    else:
        copy=tmp_path/'outside';copy.write_bytes(blob.read_bytes());blob.unlink();blob.symlink_to(copy)
    with pytest.raises(CaptureError):load_candidate_inputs(tmp_path,ref)

def test_off_creates_nothing(tmp_path):
    r=DecisionInputRecorder(tmp_path,enabled=False,run_id='off')
    c=CandidateInputCapture(r,['A'],arguments={});c.finalize()
    assert not list(tmp_path.iterdir())

def test_conflicting_prior_volume_versions_are_not_silently_selected(tmp_path):
    r=DecisionInputRecorder(tmp_path,enabled=True,run_id='revised');c=CandidateInputCapture(r,['A'],arguments={});c.finalize()
    for volume in [100,200]:
        record_bar_response(r,provider='fixture',request=dict(symbol='A',interval='1Min',adjustment='raw'),response=dict(bars=[dict(t='2026-11-02T14:34:00Z',v=volume)]),received_at=NOW)
    observe_quote_response(r,symbol='A',provider='fixture',payload=dict(quote=dict(bp=100,ap=101,t=NOW.isoformat())),raw_bytes=b'fixture',received_at=NOW)
    a=load_candidate_inputs(tmp_path,seal(r))['execution_inputs'][0]['quotes'][0]
    assert a['prior_completed_raw_1min_volume'] is None and not a['locally_observed_pair']

@pytest.mark.parametrize('quote',[
    {},dict(bp=100,ap=101,t=None),dict(bp=102,ap=101,t=NOW.isoformat()),
    dict(bp=100,ap=101,t='2026-11-02T14:35:06Z'),dict(bp=True,ap=101,t=NOW.isoformat()),
])
def test_missing_invalid_or_future_quote_is_not_qualified(tmp_path,quote):
    r=DecisionInputRecorder(tmp_path,enabled=True,run_id='badquote');c=CandidateInputCapture(r,['A'],arguments={});c.finalize()
    observe_quote_response(r,symbol='A',provider='fixture',payload=dict(quote=quote),raw_bytes=b'fixture',received_at=NOW)
    d=load_candidate_inputs(tmp_path,seal(r));a=d['execution_inputs'][0]['quotes'][0]
    assert not a['valid_bid_ask_and_local_clocks'] and not a['locally_observed_pair']
    assert d['capture_complete'] and not d['provider_available_at_certified']
