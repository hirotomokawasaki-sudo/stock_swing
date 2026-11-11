"""Acceptance: opt-in actual arguments, durable complete IDs, no execution relabel.

R22 2026-10-21: audit context was dropped by the seven-column formatter.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_swing.experiments.decision_input_capture import (
    DecisionInputRecorder,load_decision_input,capture_value)
from stock_swing.experiments.measurement_capture import CaptureError
from stock_swing.safety.audit_logger import AuditLogger

NOW=datetime(2026,10,21,17,tzinfo=timezone.utc)


def recorder(root,enabled=True):
    return DecisionInputRecorder(root,enabled=enabled,run_id='test-run')


def observe(root):
    r=recorder(root)
    ref=r.record('state','selection',dict(cash=10,lots=[dict(qty=2)],pending=None),observed_at=NOW)
    return r,ref


def test_ac_disabled_capture_is_zero_storage_io_and_accepts_uninspected_payload(tmp_path):
    root=tmp_path/'not-created';r=recorder(root,False)
    assert r.record(None,None,object(),observed_at=None) is None
    assert r.observe(None,object()) is None
    assert not root.exists(), 'default OFF must not publish empty measurement evidence'


def test_ac_exact_typed_values_and_incomplete_contract_persist(tmp_path):
    r,ref=observe(tmp_path);saved=load_decision_input(tmp_path,ref)
    assert saved['payload']==dict(cash=10,lots=[dict(qty=2)],pending=None)
    assert saved['manifest']['full_replay_ready'] is False
    assert saved['manifest']['provider_available_at_certified'] is False
    assert r.record('state','selection',saved['payload'],observed_at=NOW)==ref
    with pytest.raises(CaptureError):r.record('state','selection',dict(cash=11),observed_at=NOW)
    assert load_decision_input(tmp_path,ref)==saved


@pytest.mark.parametrize('fault',['missing_manifest','corrupt_manifest','missing_blob','corrupt_blob','unsafe_ref','symlink_dir','symlink_blob'])
def test_ac_missing_corrupt_or_escaped_observation_is_not_evidence(tmp_path,fault):
    _,ref=observe(tmp_path);path=tmp_path/ref;manifest=json.loads(path.read_bytes());blob=path.parents[1]/'blobs'/manifest['payload_sha256']
    if fault=='missing_manifest':path.unlink()
    elif fault=='corrupt_manifest':path.write_text('{}')
    elif fault=='missing_blob':blob.unlink()
    elif fault=='corrupt_blob':blob.write_text('{"cash":999}')
    elif fault=='unsafe_ref':ref='../'+ref
    elif fault=='symlink_dir':
        folder=path.parent;other=folder.with_name('outside');folder.rename(other);folder.symlink_to(other,target_is_directory=True)
    else:
        other=blob.with_suffix('.outside');blob.rename(other);blob.symlink_to(other)
    with pytest.raises(CaptureError):load_decision_input(tmp_path,ref)


@pytest.mark.parametrize('bad',[dict(api_key='never-write'),dict(nested=dict(authorization='never-write')),
                              dict(x=float('nan')),dict(x=object()),dict(x=datetime(2026,1,1))])
def test_ac_invalid_or_credential_inputs_refuse_before_storage(tmp_path,bad):
    root=tmp_path/'new';r=recorder(root)
    with pytest.raises(CaptureError):r.record('state','x',bad,observed_at=NOW)
    assert not root.exists(), 'unusable input must not be serialized'
    assert r.observe('state',bad) is None
    assert r.failures==1 and r.committed==0


def test_ac_symlinked_publish_directory_never_writes_outside_store(tmp_path):
    folder=tmp_path/'data/audits/measurement_inputs/decision_manifests';folder.parent.mkdir(parents=True)
    outside=tmp_path/'outside';outside.mkdir();folder.symlink_to(outside,target_is_directory=True)
    with pytest.raises(CaptureError):recorder(tmp_path).record('state','x',{},observed_at=NOW)
    assert not list(outside.iterdir())












def test_ac_symlinked_blob_directory_refuses_publish_and_load(tmp_path):
    _,ref=observe(tmp_path);folder=tmp_path/'data/audits/measurement_inputs/blobs'
    outside=tmp_path/'outside';folder.rename(outside);folder.symlink_to(outside,target_is_directory=True)
    before={p.name:p.read_bytes() for p in outside.iterdir()}
    with pytest.raises(CaptureError):load_decision_input(tmp_path,ref)
    with pytest.raises(CaptureError):recorder(tmp_path).record('state','other',{},observed_at=NOW)
    assert before=={p.name:p.read_bytes() for p in outside.iterdir()}


def test_ac_circular_input_does_not_interrupt_automatic_instrumentation(tmp_path):
    payload={};payload['cycle']=payload;r=recorder(tmp_path)
    assert r.observe('state',payload) is None
    assert r.failures==1 and r.committed==0
