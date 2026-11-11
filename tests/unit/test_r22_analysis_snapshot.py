"""Acceptance: descriptive readers preserve versions and never recover writes."""
import hashlib
import json

import pytest

from stock_swing.tracking.compatibility import read_analysis_snapshot
from stock_swing.tracking.history_migration import apply_migration
from stock_swing.tracking.ledger_transaction import FILES, LedgerConflict
from tests.unit.test_r22_history_migration import fixture_plan


def test_ac_snapshot_hashes_same_epoch_and_never_qualifies_corrected_history(tmp_path):
    _, _, plan = fixture_plan(tmp_path)
    apply_migration(tmp_path, plan)
    path=tmp_path/'data/tracking/pnl_state.json'
    before={n:(path.parent/n).read_bytes() for n in FILES}
    state, context=read_analysis_snapshot(path)
    assert context['ledger_revision']==state['measurement_lineage']['ledger_revision']
    assert context['state_sha256']==hashlib.sha256(before['pnl_state.json']).hexdigest()
    assert context['events_sha256']==hashlib.sha256(before['trade_events.jsonl']).hexdigest()
    assert context['promotion_ready'] is False
    assert context['measurement_status']=='historical_correction_unqualified'
    assert before=={n:(path.parent/n).read_bytes() for n in FILES}
    state['trades'].clear()
    assert read_analysis_snapshot(path)[0]['trades'], 'caller mutation cannot change another read'


def test_ac_legacy_snapshot_explicitly_unqualified_not_an_empty_fallback(tmp_path):
    path=tmp_path/'data/tracking/pnl_state.json';path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'trades':[]}))
    state, context=read_analysis_snapshot(path)
    assert state=={'trades':[]}
    assert context['ledger_revision']=='legacy' and context['promotion_ready'] is False
    assert context['events_sha256'] is None


@pytest.mark.parametrize('status', ['open','closed','quarantined','reconciled_removed'])
def test_ac_known_legacy_statuses_are_preserved_not_silently_filtered(tmp_path,status):
    path=tmp_path/'data/tracking/pnl_state.json';path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'trades':[{'status':status}]}))
    state,_=read_analysis_snapshot(path)
    assert state['trades']==[{'status':status}]


def test_ac_typo_status_cannot_be_a_successful_empty_observation(tmp_path):
    path=tmp_path/'data/tracking/pnl_state.json';path.parent.mkdir(parents=True)
    path.write_text('{"trades":[{"status":"clsoed"}]}')
    with pytest.raises(LedgerConflict,match='status'):
        read_analysis_snapshot(path)


@pytest.mark.parametrize('damage',['missing','json','shape','schema','collection','status','lineage','events','prepared'])
def test_ac_bad_read_cannot_become_success_or_finish_a_prepared_writer(tmp_path,damage):
    _,_,plan=fixture_plan(tmp_path);apply_migration(tmp_path,plan)
    path=tmp_path/'data/tracking/pnl_state.json'
    if damage=='missing':path.unlink()
    if damage=='json':path.write_text('{')
    if damage=='shape':path.write_text('[]')
    if damage=='schema':path.write_text('{}')
    if damage=='status':path.write_text('{"trades":[{}]}')
    if damage=='collection':
        state=json.loads(path.read_text());state['trades']={};path.write_text(json.dumps(state))
    if damage=='lineage':
        state=json.loads(path.read_text());state['measurement_lineage']=None;path.write_text(json.dumps(state))
    if damage=='events':(path.parent/'trade_events.jsonl').write_text('not json\n')
    if damage=='prepared':(path.parent/'.ledger_transaction.json').write_text('{"state":"prepared"}')
    before={p.name:p.read_bytes() for p in path.parent.iterdir() if p.is_file()}
    with pytest.raises((LedgerConflict,ValueError,FileNotFoundError)):
        read_analysis_snapshot(path)
    assert before=={p.name:p.read_bytes() for p in path.parent.iterdir() if p.is_file()}
