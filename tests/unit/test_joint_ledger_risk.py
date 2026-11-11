"""Regression: FIX-06 / 63c8c39→fa8159a, merged with FIX-03 in November.

Acceptance: preserve unknown/null risk while refusing prepared or inconsistent
ledger pairs; do not recover a journal or rewrite evidence from a risk read.
"""
import json
from stock_swing.risk.risk_budget import compute_open_risk

def seed(tmp_path, state, events=b''):
    f=tmp_path/'data/tracking';f.mkdir(parents=True)
    (f/'pnl_state.json').write_text(json.dumps(state))
    (f/'trade_events.jsonl').write_bytes(events)
    return f

def test_ac_prepared_journal_cannot_be_read_as_flat_or_recovered(tmp_path):
    f=seed(tmp_path,{'trades':[]})
    journal=f/'.ledger_transaction.json';journal.write_bytes(b'{broken-prepared')
    before={p.name:p.read_bytes() for p in f.iterdir()}
    risk=compute_open_risk(tmp_path,100000)
    assert risk['status']=='unavailable' and risk['total_open_risk'] is None and risk['is_blocked'], 'prepared recovery must not become measured zero'
    assert before=={p.name:p.read_bytes() for p in f.iterdir() if p.name in before}, 'risk reader must preserve all prior bytes'

def test_ac_corrupt_event_pair_cannot_be_read_as_flat(tmp_path):
    f=seed(tmp_path,{'trades':[]},b'{invalid-event\n')
    before={p.name:p.read_bytes() for p in f.iterdir()}
    risk=compute_open_risk(tmp_path,100000)
    assert risk['status']=='unavailable' and risk['pct_of_equity'] is None and risk['is_blocked'], 'invalid pair must hold new BUYs'
    assert before=={p.name:p.read_bytes() for p in f.iterdir() if p.name in before}, 'read must not repair events'

def test_ac_verified_empty_pair_keeps_flat_risk(tmp_path):
    seed(tmp_path,{'trades':[]})
    risk=compute_open_risk(tmp_path,100000)
    assert risk['status']=='ok' and risk['total_open_risk']==0 and not risk['is_blocked'], 'a coherent empty population is different from missing evidence'

def test_ac_missing_state_with_remaining_events_is_unknown(tmp_path):
    f=tmp_path/'data/tracking';f.mkdir(parents=True)
    (f/'trade_events.jsonl').write_bytes(b'{}\n')
    risk=compute_open_risk(tmp_path,100000)
    assert risk['status']=='unavailable' and risk['total_open_risk'] is None and risk['is_blocked'], 'missing state must not erase event history'
    assert not (f/'pnl_state.json').exists(), 'risk read must not create an empty replacement state'
