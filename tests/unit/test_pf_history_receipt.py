"""Acceptance: reproduce the actual PF input, not the cleaner report history."""
import copy
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from stock_swing.risk.entry_filter import EntryFilterConfig, EntryFilterEngine
from stock_swing.risk.pf_history_receipt import PFHistoryCapture, load_pf_history, replay_pf_history

NOW=datetime(2026,10,29,15,tzinfo=timezone.utc)


def fixture():
    trades=[dict(status='closed',symbol='IBM',pnl=p,execution_leg_id=f'leg-{i}',
                 trade_id='same-position',exit_time='2026-10-28T15:00:00+00:00')
            for i,p in enumerate([10,-20,-30,-40,-50])]
    # Retain duplicates, missing PnL and quarantine annotations exactly as consumed.
    trades += [dict(status='closed',symbol='IBM',pnl=None,quarantined=True),
               dict(status='open',symbol='IBM',pnl=999)]
    decisions=[SimpleNamespace(decision_id='decision-IBM',symbol='IBM',action='buy',generated_at=NOW),
               SimpleNamespace(decision_id='decision-SELL',symbol='MSFT',action='sell',generated_at=NOW)]
    return trades,decisions,EntryFilterConfig()


def capture(root, *, dry=False):
    trades,decisions,cfg=fixture()
    rec=PFHistoryCapture(root=root,run_id='run-1',experiment_config_hash='a'*16,
        decisions=decisions,closed_trades=trades,entry_config=cfg,etf_symbols=set(),
        observed_at=NOW,dry_run=dry)
    result=EntryFilterEngine(cfg).filter(decisions,{},trades,set())
    ref=rec.finish(result)
    return ref, trades, decisions, result


def test_ac_actual_input_roundtrip_and_independent_arithmetic(tmp_path):
    ref,trades,decisions,result=capture(tmp_path)
    assert ref['status']=='recorded'
    doc=load_pf_history(tmp_path,ref,decision_id='decision-IBM')
    assert doc['input_source']=='pnl_tracker.state.trades'
    assert doc['clean_history_certified'] is False
    assert len(doc['history'])==7 and doc['history'][5]['consumed']['pnl'] is None
    assert doc['history'][5]['lineage']['quarantined'] is True
    replay=replay_pf_history(doc)
    assert replay['IBM']['closed_count']==5
    assert replay['IBM']['profit_factor']==pytest.approx(round(10/140,3))
    assert replay['IBM']['gate3_would_block'] is True
    assert doc['outputs']['passed_ids']==['decision-SELL']
    assert doc['outputs']['blocked']==[list(row) for row in result.blocked]
    assert doc['experiment_config_hash']=='a'*16 and len(doc['entry_config_sha256'])==64


def test_snapshot_does_not_reopen_or_follow_later_mutations(tmp_path):
    trades,decisions,cfg=fixture();original=copy.deepcopy(trades)
    rec=PFHistoryCapture(root=tmp_path,run_id='run',experiment_config_hash='fixture',
        decisions=decisions,closed_trades=trades,entry_config=cfg,etf_symbols=set(),observed_at=NOW)
    result=EntryFilterEngine(cfg).filter(decisions,{},trades,set())
    trades[0]['pnl']=999;cfg.rolling_pf_gate=999
    ref=rec.finish(result);doc=load_pf_history(tmp_path,ref)
    assert doc['history'][0]['consumed']['pnl']==original[0]['pnl']
    assert doc['entry_config']['rolling_pf_gate']==.7


@pytest.mark.parametrize('mutation', ['byte','missing','wrong_decision','wrong_hash','symlink'])
def test_reader_refuses_corrupt_or_unjoined_receipt(tmp_path,mutation):
    ref,*_=capture(tmp_path);path=tmp_path/ref['path']
    identity='decision-IBM'
    if mutation=='byte':path.write_bytes(path.read_bytes()+b' ')
    if mutation=='missing':path.unlink()
    if mutation=='wrong_hash':ref['sha256']='0'*64
    if mutation=='wrong_decision':identity='other-decision'
    if mutation=='symlink':
        target=tmp_path/'original';path.rename(target);path.symlink_to(target)
    with pytest.raises((ValueError,FileNotFoundError)):
        load_pf_history(tmp_path,ref,decision_id=identity)


def test_dry_run_never_creates_store(tmp_path):
    ref,*_=capture(tmp_path,dry=True)
    assert ref['status']=='dry_run' and not (tmp_path/'data/audits/pf_history').exists()


@pytest.mark.parametrize('bad', [float('nan'),float('inf'),'credential=fixture-secret'])
def test_bad_consumed_input_reports_gap_without_changing_business(tmp_path,bad):
    trades,decisions,cfg=fixture();trades[0]['pnl']=bad
    rec=PFHistoryCapture(root=tmp_path,run_id='fixture',experiment_config_hash='fixture',
        decisions=decisions,closed_trades=trades,entry_config=cfg,etf_symbols=set(),observed_at=NOW)
    ref=rec.finish(SimpleNamespace(blocked=[],passed=decisions))
    assert ref['status']=='unavailable' and 'path' not in ref
    assert not (tmp_path/'data/audits/pf_history').exists()


def test_write_failure_keeps_decisions_and_existing_receipt(tmp_path):
    ref,*_=capture(tmp_path);path=tmp_path/ref['path'];before=path.read_bytes()
    trades,decisions,cfg=fixture();trades[0]['pnl']=20
    rec=PFHistoryCapture(root=tmp_path,run_id='run-1',experiment_config_hash='a'*16,
        decisions=decisions,closed_trades=trades,entry_config=cfg,etf_symbols=set(),observed_at=NOW)
    result=EntryFilterEngine(cfg).filter(decisions,{},trades,set())
    assert rec.finish(result)['status']=='unavailable'
    assert path.read_bytes()==before and result.passed==[decisions[1]]


def test_identical_retry_is_idempotent_and_path_traversal_refused(tmp_path):
    ref,*_=capture(tmp_path);assert capture(tmp_path)[0]==ref
    bad=dict(ref,path='../outside.json')
    with pytest.raises(ValueError):load_pf_history(tmp_path,bad)


def test_persisted_decision_link_is_checked_without_optional_argument(tmp_path):
    ref,*_=capture(tmp_path)
    with pytest.raises(ValueError):load_pf_history(tmp_path,dict(ref,decision_id='not-in-receipt'))
    with pytest.raises(ValueError):
        load_pf_history(tmp_path,dict(ref,decision_id='decision-IBM'),decision_id='decision-SELL')


def test_unused_free_text_is_never_copied_or_used_to_relabel_clean_history(tmp_path):
    trades,decisions,cfg=fixture();trades[0]['notes']='Bearer synthetic-secret-do-not-retain'
    rec=PFHistoryCapture(root=tmp_path,run_id='fixture',experiment_config_hash='fixture',
        decisions=decisions,closed_trades=trades,entry_config=cfg,etf_symbols=set(),observed_at=NOW)
    result=EntryFilterEngine(cfg).filter(decisions,{},trades,set());ref=rec.finish(result)
    raw=(tmp_path/ref['path']).read_text()
    assert 'synthetic-secret' not in raw and 'notes' not in raw
    assert load_pf_history(tmp_path,ref)['clean_history_certified'] is False
