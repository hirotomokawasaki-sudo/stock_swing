"""Acceptance: real engine input/output -> immutable run -> ordinary reader.

No policy mocks: denied/accepted outcomes come from the existing DecisionEngine.
Malformed but correctly sealed semantic joins must still be rejected.
"""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json

import pytest

from stock_swing.core.runtime import RuntimeMode
from stock_swing.decision_engine import DecisionEngine, RiskValidator
from stock_swing.strategy_engine.base_strategy import CandidateSignal
from stock_swing.experiments.candidate_input_capture import CandidateInputCapture, load_candidate_inputs
from stock_swing.experiments.decision_input_capture import DecisionInputRecorder, capture_value
from stock_swing.experiments.measurement_capture import CaptureError


def _signal(strength=0.9):
    return CandidateSignal(strategy_id='breakout_momentum_v1',symbol='NVDA',action='buy',
        signal_strength=strength,generated_at=datetime.now(timezone.utc)-timedelta(seconds=1),
        time_horizon='3d',confidence=0.9,reasoning='fixture',metadata={'latest_close':130})


def _seal(recorder, capture):
    capture.finalize()
    recorder.observe('run_end',dict(exit_code=1 if recorder.failures else 0,
        observations_before_end=recorder.committed,capture_failures=recorder.failures,
        full_replay_ready=False))
    return recorder.seal()


@pytest.mark.parametrize('strength,action',[(0.9,'buy'),(0.1,'deny')])
def test_ac_actual_engine_result_input_binding_and_deep_snapshot(tmp_path,strength,action):
    recorder=DecisionInputRecorder(tmp_path,enabled=True,run_id='real-engine-binding')
    capture=CandidateInputCapture(recorder,['NVDA'],arguments={})
    validator=RiskValidator(min_signal_strength=0.6,min_confidence=0.4,max_position_size=400)
    signal=_signal(strength);positions={'AAPL':3}
    output=DecisionEngine(runtime_mode=RuntimeMode.PAPER,risk_validator=validator).process(signal,current_positions=positions)
    before=capture_value(output)
    capture.decision_result(signal,positions,output,runtime_mode='paper',validator=validator)
    assert capture_value(output)==before and output.action==action
    positions['AAPL']=99;signal.metadata['latest_close']=999
    loaded=load_candidate_inputs(tmp_path,_seal(recorder,capture))
    saved=loaded['recorded_decisions'][0]
    assert saved['run_id']=='real-engine-binding' and saved['decision_id']==output.decision_id
    assert saved['input_current_positions']=={'AAPL':3}
    assert saved['input_signal']['metadata']['latest_close']==130
    assert saved['output']==before and saved['validator']==dict(min_signal_strength=0.6,min_confidence=0.4,max_position_size=400)
    assert loaded['full_replay_ready'] is False


@pytest.mark.parametrize('fault',['run','identity','symbol','strategy','mode','naive_time','future_time','positions','validator','duplicate'])
def test_ac_sealed_but_conflicting_decision_bindings_refused(tmp_path,fault):
    rec=DecisionInputRecorder(tmp_path,enabled=True,run_id='bad-binding')
    capture=CandidateInputCapture(rec,['NVDA'],arguments={});signal=_signal()
    validator=RiskValidator();output=DecisionEngine(runtime_mode=RuntimeMode.PAPER,risk_validator=validator).process(signal,current_positions={})
    payload=dict(run_id=rec.run_id,decision_id=output.decision_id,runtime_mode='paper',
        input_signal=capture_value(signal),input_current_positions={},validator=dict(min_signal_strength=validator.min_signal_strength,min_confidence=validator.min_confidence,max_position_size=validator.max_position_size),output=capture_value(output),scope='decision_engine_only',full_replay_ready=False)
    if fault=='run':payload['run_id']='other-run'
    elif fault=='identity':payload['decision_id']='other-decision'
    elif fault=='symbol':payload['output']['symbol']='AAPL'
    elif fault=='strategy':payload['output']['strategy_id']='another-strategy'
    elif fault=='mode':payload['runtime_mode']='research'
    elif fault=='naive_time':payload['output']['generated_at']='2026-10-30T13:36:00'
    elif fault=='future_time':payload['output']['generated_at']=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
    elif fault=='positions':payload['input_current_positions']=None
    elif fault=='validator':payload['validator']={}
    rec.observe('decision_engine_result',payload)
    if fault=='duplicate':rec.observe('decision_engine_result',payload)
    ref=_seal(rec,capture)
    with pytest.raises(CaptureError):load_candidate_inputs(tmp_path,ref)


def test_ac_storage_failure_does_not_mutate_or_raise_into_engine(tmp_path):
    rec=DecisionInputRecorder(tmp_path,enabled=True,run_id='failed-recording')
    capture=CandidateInputCapture(rec,['NVDA'],arguments={});validator=RiskValidator()
    signal=_signal();output=DecisionEngine(runtime_mode=RuntimeMode.PAPER,risk_validator=validator).process(signal,current_positions={})
    before=capture_value(output)
    store=tmp_path/'data/audits/measurement_inputs'
    # Existing published store cannot be removed to make the test pass. Force
    # the real writer to reject a secret-shaped input instead.
    signal.metadata['api_secret']='synthetic-fixture'
    capture.decision_result(signal,{},output,runtime_mode='paper',validator=validator)
    assert rec.failures==1 and capture_value(output)==before
    ref=_seal(rec,capture);loaded=load_candidate_inputs(tmp_path,ref)
    assert not loaded['capture_complete'] and not loaded['declared_exit_success']
    assert loaded['recorded_decisions']==[]
    assert all('synthetic-fixture' not in q.read_text(errors='ignore') for q in store.rglob('*.json'))


def test_ac_missing_and_corrupt_run_fail_closed(tmp_path):
    with pytest.raises(CaptureError):load_candidate_inputs(tmp_path,'data/audits/measurement_inputs/run_manifests/missing.json')
    rec=DecisionInputRecorder(tmp_path,enabled=True,run_id='corrupt-run')
    capture=CandidateInputCapture(rec,['NVDA'],arguments={});ref=_seal(rec,capture)
    (tmp_path/ref).write_text('{invalid-json')
    with pytest.raises(CaptureError):load_candidate_inputs(tmp_path,ref)
