"""Regression: R22 bridge corruption acceptance, baseline ac29888 (2026-10-21).

Acceptance: matching log/snapshot copies are not proof of valid consumption;
initial review and retry must reject contradictory or rewritten evidence.
"""
from datetime import datetime,timezone
import json
import pytest
from tests.unit.test_consumption_bridge import setup_bridge,snapshot
from stock_swing.tracking.consumption_bridge import prepare_bridge,apply_bridge
from stock_swing.tracking.ledger_transaction import LedgerConflict


def damage_record(root,mutate):
    folder=root/'data/tracking';path=folder/'fill_ledger.jsonl'
    rows=[json.loads(line) for line in path.read_bytes().splitlines()]
    mutate(rows[-1]);path.write_bytes(b''.join(json.dumps(r).encode()+b'\n' for r in rows))
    snap_path=folder/'fill_consumed_ledger.json';saved=json.loads(snap_path.read_bytes())
    for index,row in enumerate(saved['fills']):
        if row['fill_id']==rows[-1]['fill_id']:saved['fills'][index]=rows[-1]
    snap_path.write_text(json.dumps(saved))


def mutate_record(record,damage):
    if damage=='sum':record['consumption_events'][0]['qty']=999
    if damage=='missing_history':record.pop('consumption_events')
    if damage=='negative':record['consumption_events'][0]['qty']=-1
    if damage=='fractional':record['consumption_events'][0]['qty']=.5
    if damage=='nan':record['consumption_events'][0]['qty']=float('nan')
    if damage=='event_time':record['consumption_events'][0].pop('consumed_at')
    if damage=='latest_consumer':record['consumed_by']='wrong-consumer'
    if damage=='flag':record['consumed']=not record['consumed']
    if damage=='over':record['qty']=1
    if damage=='watermark':record['consumed_qty']=3
    if damage=='latest_time':record['consumed_at']='2026-01-01T00:00:00Z'
    if damage=='prior_identity':record['consumption_events'][0]['trade_id']='rewritten-old-consumer'


@pytest.mark.parametrize('damage',['sum','missing_history','negative','fractional','nan','event_time','latest_consumer','flag'])
def test_ac_initial_conflicting_consumption_refused_without_writes(tmp_path,damage):
    _,order,_=setup_bridge(tmp_path,1)
    damage_record(tmp_path,lambda r:mutate_record(r,damage))
    before=snapshot(tmp_path)
    with pytest.raises(LedgerConflict):
        prepare_bridge(before,[order],evidence_sha256='a'*64,recorded_at=datetime.now(timezone.utc).isoformat())
    assert snapshot(tmp_path)==before, 'invalid initial evidence must not change financial bytes'


@pytest.mark.parametrize('damage',['over','watermark','sum','latest_time','latest_consumer','flag','prior_identity'])
def test_ac_retry_conflicting_consumption_refused_without_writes(tmp_path,damage):
    _,_,plan=setup_bridge(tmp_path,1);apply_bridge(tmp_path,plan)
    damage_record(tmp_path,lambda r:mutate_record(r,damage))
    before=snapshot(tmp_path)
    with pytest.raises(LedgerConflict):apply_bridge(tmp_path,plan)
    assert snapshot(tmp_path)==before, 'invalid retry must not launder contradictory evidence'
