"""Regression: 2026-11-09 full-restore migrated-ledger dashboard timeout.

Real canonical files and real reader validation; profiling observes calls without
mocking or replacing internal business logic.
"""
import json
import os
import sys
from datetime import datetime

from console.services.dashboard_service import DashboardService


def service(tmp_path):
    folder=tmp_path/'data/tracking';folder.mkdir(parents=True)
    state=folder/'pnl_state.json';state.write_text(json.dumps({'created_at':'2026-05-12T09:17:00+00:00','trades':[]}))
    events=folder/'trade_events.jsonl';events.write_text('')
    obj=DashboardService.__new__(DashboardService);obj.project_root=tmp_path
    obj._tracking_state_meta_cache=None;obj._current_account_cutoff_cache=None
    return obj,state,events


def test_ac_many_decisions_validate_one_stable_ledger_epoch(tmp_path):
    obj,_,_=service(tmp_path);calls=[]
    old=sys.getprofile()
    def observe(frame,event,arg):
        if event=='call' and frame.f_code.co_name=='read_tracking_evidence':calls.append(frame.f_code.co_filename)
    sys.setprofile(observe)
    try:results=[obj._current_account_cutoff() for _ in range(100)]
    finally:sys.setprofile(old)
    assert len(calls)==1,'100 same-epoch cutoff checks must not validate the entire ledger 100 times'
    assert all(r==datetime.fromisoformat('2026-05-12T09:17:00+00:00') for r in results),'cutoff must remain the recorded account baseline'


def test_ac_atomic_state_replacement_same_mtime_invalidates_cutoff(tmp_path):
    obj,state,_=service(tmp_path);first=obj._current_account_cutoff();mtime=state.stat().st_mtime_ns
    replacement=state.with_suffix('.next');replacement.write_text(state.read_text().replace('05-12','05-13'));os.utime(replacement,ns=(mtime,mtime));os.replace(replacement,state)
    assert obj._current_account_cutoff()!=first,'same-size same-mtime atomic publication must invalidate the cached cutoff'
    assert obj._current_account_cutoff().day==13,'new account metadata must propagate'


def test_ac_corrupt_events_do_not_reuse_cached_metadata(tmp_path):
    obj,_,events=service(tmp_path);first=obj._current_account_cutoff();events.write_text('not-json\n')
    assert obj._current_account_cutoff()==obj.DEFAULT_CURRENT_ACCOUNT_CUTOFF,'damaged event pair must retain the existing fallback, never stale success'
    events.write_text('')
    assert obj._current_account_cutoff()==first,'repaired canonical pair must be freshly validated'


def test_ac_prepared_journal_disables_cache_without_recovery(tmp_path):
    obj,state,_=service(tmp_path);obj._current_account_cutoff();original=state.read_bytes()
    journal=state.parent/'.ledger_transaction.json';journal.write_text('{"state":"prepared"}')
    assert obj._current_account_cutoff()==obj.DEFAULT_CURRENT_ACCOUNT_CUTOFF,'prepared epoch must not return the old cached metadata'
    assert journal.read_text()=='{"state":"prepared"}' and state.read_bytes()==original,'reader must not recover or rewrite financial state'


def test_ac_deleted_state_never_returns_cached_cutoff(tmp_path):
    obj,state,_=service(tmp_path);obj._current_account_cutoff();state.rename(state.with_suffix('.saved'))
    assert obj._current_account_cutoff()==obj.DEFAULT_CURRENT_ACCOUNT_CUTOFF,'missing state must not use a stale successful epoch'


def test_ac_corrupt_state_never_returns_cached_cutoff(tmp_path):
    obj,state,_=service(tmp_path);obj._current_account_cutoff();state.write_text('not-json')
    assert obj._current_account_cutoff()==obj.DEFAULT_CURRENT_ACCOUNT_CUTOFF,'corrupt state must retain the existing safe fallback'


def test_ac_missing_tracking_folder_not_created_by_cutoff(tmp_path):
    obj=DashboardService.__new__(DashboardService);obj.project_root=tmp_path
    assert obj._current_account_cutoff()==obj.DEFAULT_CURRENT_ACCOUNT_CUTOFF,'absent metadata retains the existing fallback'
    assert not (tmp_path/'data').exists(),'a metadata lookup must not create missing financial storage'
