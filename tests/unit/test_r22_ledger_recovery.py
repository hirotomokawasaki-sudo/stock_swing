"""R22 N2 2026-10-21; baseline 9a98622: stale caches and cross-file commit gaps."""
import json
from pathlib import Path
import pytest
from stock_swing.tracking.pnl_tracker import PnLTracker
from stock_swing.tracking.fill_ledger import FillLedger, FillAlreadyConsumedError
from stock_swing.tracking.trade_event_store import TradeEventStore


def buy(tracker, ident='buy1', qty=10):
    return tracker.record_submission('AAPL','test','buy',qty,100.,ident,ident)


def sell_snapshot(qty=10):
    return dict(id='sell1',symbol='AAPL',side='sell',filled_qty=qty,qty=qty,filled_avg_price=110,filled_at='2026-10-21T14:00:00Z')


def test_stale_tracker_does_not_erase_another_writer(tmp_path):
    first,stale=PnLTracker(tmp_path),PnLTracker(tmp_path)
    buy(first,'buy1');buy(stale,'buy2')
    assert {t['broker_order_id'] for t in PnLTracker(tmp_path).state.trades}=={'buy1','buy2'}


def test_stale_fill_consumer_cannot_overwrite_consumption(tmp_path):
    first=FillLedger(tmp_path);first.ingest(sell_snapshot())
    stale=FillLedger(tmp_path);stale.get('sell1')
    first.consume('sell1','consumer-1',10)
    with pytest.raises(FillAlreadyConsumedError): stale.consume('sell1','consumer-2',10)
    assert FillLedger(tmp_path).get('sell1')['consumption_events'][0]['trade_id']=='consumer-1'


def test_fill_get_cannot_mutate_internal_evidence(tmp_path):
    ledger=FillLedger(tmp_path);ledger.ingest(sell_snapshot())
    ledger.get('sell1')['consumed_qty']=10
    assert ledger.available_qty('sell1')==10


def test_state_and_event_roll_back_together_on_event_io_failure(tmp_path,monkeypatch):
    tracker=PnLTracker(tmp_path);buy(tracker)
    before=tracker.state_path.read_bytes()
    events=tracker.event_store.path
    # A corrupt on-disk event is a real I/O precondition, not a mock of accounting.
    events.write_text('{incomplete\n')
    with pytest.raises(ValueError):
        tracker.record_exit('AAPL',110,10,'sell1','test','test')
    assert tracker.state_path.read_bytes()==before, 'event validation failure must not leave a closed state'


def test_corrupt_state_is_not_reset_to_empty_baseline(tmp_path):
    folder=tmp_path/'data/tracking';folder.mkdir(parents=True)
    (folder/'pnl_state.json').write_text('{incomplete')
    with pytest.raises(ValueError): PnLTracker(tmp_path)
    assert (folder/'pnl_state.json').read_text()=='{incomplete'


def test_direct_stale_state_save_fails_instead_of_erasing_new_trades(tmp_path):
    first=PnLTracker(tmp_path);buy(first,'buy1')
    stale=PnLTracker(tmp_path);buy(first,'buy2')
    stale.state.trades[0]['entry_price']=101
    with pytest.raises(RuntimeError): stale._save_state()
    assert len(PnLTracker(tmp_path).state.trades)==2


def test_buy_submission_retry_does_not_duplicate_lot_or_event(tmp_path):
    tracker=PnLTracker(tmp_path)
    identity=buy(tracker)
    assert buy(PnLTracker(tmp_path))==identity
    assert len(PnLTracker(tmp_path).state.trades)==1
    assert len(TradeEventStore(tmp_path).read_all())==1
    with pytest.raises(RuntimeError): buy(PnLTracker(tmp_path),qty=11)
    assert len(PnLTracker(tmp_path).state.trades)==1


def test_exception_after_staging_rolls_back_all_four_files(tmp_path):
    from stock_swing.tracking.ledger_transaction import ledger_transaction
    from stock_swing.tracking.settle_sell import settle_sell
    buy(PnLTracker(tmp_path))
    before={p.name:p.read_bytes() for p in (tmp_path/'data/tracking').iterdir() if not p.name.startswith('.')}
    with pytest.raises(RuntimeError,match='injected'):
        with ledger_transaction(tmp_path):
            settle_sell(tmp_path,sell_snapshot())
            raise RuntimeError('injected application abort before prepare')
    after={p.name:p.read_bytes() for p in (tmp_path/'data/tracking').iterdir() if not p.name.startswith('.')}
    assert before==after


def test_nested_caught_error_cannot_commit_partial_intent(tmp_path):
    from stock_swing.tracking.ledger_transaction import ledger_transaction, LedgerConflict
    buy(PnLTracker(tmp_path))
    before=(tmp_path/'data/tracking/pnl_state.json').read_bytes()
    with pytest.raises(LedgerConflict,match='nested'):
        with ledger_transaction(tmp_path):
            buy(PnLTracker(tmp_path),'buy2')
            try:
                with ledger_transaction(tmp_path): raise ValueError('nested abort')
            except ValueError: pass
    assert (tmp_path/'data/tracking/pnl_state.json').read_bytes()==before


# Actual subprocess exits at filesystem boundaries. No accounting function is mocked.
WORKER = r'''
import os,sys,time
from pathlib import Path
from stock_swing.tracking.pnl_tracker import PnLTracker
from stock_swing.tracking.settle_sell import settle_sell
root=Path(sys.argv[1]);mode=sys.argv[2];point=sys.argv[3]
tracker=PnLTracker(root)
if mode=='crash':
    real_replace=os.replace
    def interrupted(src,dst):
        name=Path(dst).name
        if point=='before_prepare' and name=='.ledger_transaction.json': os._exit(73)
        result=real_replace(src,dst)
        if name==point: os._exit(73)
        return result
    os.replace=interrupted
    real_unlink=Path.unlink
    def unlink_after(self,*a,**kw):
        result=real_unlink(self,*a,**kw)
        if point=='after_unlink' and self.name=='.ledger_transaction.json': os._exit(73)
        return result
    Path.unlink=unlink_after
else:
    (root/('ready-'+point)).write_text('ready')
    deadline=time.monotonic()+8
    while not (root/'go').exists():
        if time.monotonic()>deadline: raise RuntimeError('barrier timeout')
        time.sleep(.01)
if mode=='buy':
    tracker.record_submission('AAPL','test','buy',1,100,'concurrent-'+point,'concurrent-'+point)
else:
    settle_sell(root,dict(id='sell1',symbol='AAPL',side='sell',filled_qty=10,
        filled_avg_price=110,filled_at='2026-10-21T14:00:00Z'),exit_reason='test')
'''


def run_worker(root,mode,point):
    import os,subprocess,sys
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[2]/'src'))
    return subprocess.Popen([sys.executable,'-c',WORKER,str(root),mode,point],env=env,
                            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)


def verify_settled(root):
    tracker=PnLTracker(root)
    closed=[t for t in tracker.state.trades if t['status']=='closed']
    assert len(closed)==1 and closed[0]['qty']==10 and closed[0]['pnl']==pytest.approx(100)
    fill=FillLedger(root).get('sell1')
    assert fill['consumed_qty']==10 and len(fill['consumption_events'])==1
    snapshot=json.loads((root/'data/tracking/fill_consumed_ledger.json').read_text())
    assert snapshot['fills'][0]['consumed_qty']==10
    events=[e for e in TradeEventStore(root).read_all() if e.event_type=='trade_closed']
    assert len(events)==1 and events[0].payload['exit_qty']==10
    assert not (root/'data/tracking/.ledger_transaction.json').exists()


@pytest.mark.parametrize('point',['before_prepare','.ledger_transaction.json','fill_consumed_ledger.json',
    'fill_ledger.jsonl','pnl_state.json','trade_events.jsonl','after_unlink'])
def test_process_death_recovers_same_sell_without_double_consumption(tmp_path,point):
    from stock_swing.tracking.ledger_transaction import recover_ledger
    from stock_swing.tracking.settle_sell import settle_sell
    buy(PnLTracker(tmp_path))
    process=run_worker(tmp_path,'crash',point)
    out,err=process.communicate(timeout=12)
    assert process.returncode==73,(out,err)
    if point=='before_prepare':
        assert not (tmp_path/'data/tracking/.ledger_transaction.json').exists()
        assert PnLTracker(tmp_path).state.trades[0]['status']=='open'
        assert FillLedger(tmp_path).get('sell1') is None
        assert settle_sell(tmp_path,sell_snapshot(),exit_reason='test') is not None
    else:
        recover_ledger(tmp_path)
        assert settle_sell(tmp_path,sell_snapshot(),exit_reason='test') is None
    verify_settled(tmp_path)


@pytest.mark.parametrize('mode',['buy','settle'])
def test_real_processes_serialize_stale_writers_and_duplicate_sell(tmp_path,mode):
    import time
    buy(PnLTracker(tmp_path))
    children=[run_worker(tmp_path,mode,str(i)) for i in range(4)]
    try:
        deadline=time.monotonic()+8
        while len(list(tmp_path.glob('ready-*')))!=4:
            if time.monotonic()>deadline: raise AssertionError('workers did not reach barrier')
            time.sleep(.01)
        (tmp_path/'go').write_text('go')
        for process in children:
            out,err=process.communicate(timeout=12)
            assert process.returncode==0,(out,err)
    finally:
        for process in children:
            if process.poll() is None: process.kill();process.wait(timeout=5)
    if mode=='settle': verify_settled(tmp_path)
    else:
        tracker=PnLTracker(tmp_path)
        assert len(tracker.state.trades)==5
        assert sum(t['qty'] for t in tracker.state.trades)==14
        assert len(TradeEventStore(tmp_path).read_all())==5


def test_real_threads_share_lock_without_losing_submissions(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    trackers=[PnLTracker(tmp_path) for _ in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda pair:buy(pair[1],f'buy-{pair[0]}',1),enumerate(trackers)))
    assert len(PnLTracker(tmp_path).state.trades)==4


@pytest.mark.parametrize('corruption',['syntax','hash','path','duplicate','version','foreign_state'])
def test_bad_or_conflicting_journal_is_preserved_without_advancing_any_file(tmp_path,corruption):
    from stock_swing.tracking.ledger_transaction import recover_ledger, LedgerConflict
    buy(PnLTracker(tmp_path))
    process=run_worker(tmp_path,'crash','.ledger_transaction.json')
    out,err=process.communicate(timeout=12);assert process.returncode==73,(out,err)
    folder=tmp_path/'data/tracking';journal=folder/'.ledger_transaction.json'
    rec=json.loads(journal.read_text())
    if corruption=='syntax': journal.write_text('{broken')
    elif corruption=='foreign_state':
        data=json.loads((folder/'pnl_state.json').read_text());data['last_updated']='unexpected-external-edit'
        (folder/'pnl_state.json').write_text(json.dumps(data))
    else:
        if corruption=='hash': rec['files'][0]['after_sha256']='0'*64
        elif corruption=='path': rec['files'][0]['name']='../../outside.json'
        elif corruption=='duplicate': rec['files'].append(rec['files'][0])
        else: rec['version']=99
        journal.write_text(json.dumps(rec))
    before={p.name:p.read_bytes() for p in folder.iterdir() if p.is_file()}
    with pytest.raises(LedgerConflict): recover_ledger(tmp_path)
    assert before=={p.name:p.read_bytes() for p in folder.iterdir() if p.is_file()}


def test_real_io_error_after_prepare_is_roll_forward_recoverable(tmp_path,monkeypatch):
    import os
    from stock_swing.tracking.ledger_transaction import recover_ledger
    from stock_swing.tracking.settle_sell import settle_sell
    buy(PnLTracker(tmp_path))
    real_replace=os.replace
    def error(src,dst):
        if Path(dst).name=='pnl_state.json': raise OSError('injected disk error')
        return real_replace(src,dst)
    with monkeypatch.context() as m:
        m.setattr(os,'replace',error)
        with pytest.raises(OSError): settle_sell(tmp_path,sell_snapshot())
    assert (tmp_path/'data/tracking/.ledger_transaction.json').exists()
    recover_ledger(tmp_path);verify_settled(tmp_path)
    assert settle_sell(tmp_path,sell_snapshot()) is None


def test_historical_consumption_gap_is_not_auto_repaired(tmp_path):
    from stock_swing.tracking.settle_sell import settle_sell
    from stock_swing.tracking.ledger_transaction import LedgerConflict
    tracker=PnLTracker(tmp_path);buy(tracker)
    tracker.record_exit('AAPL',110,5,'sell1')
    state=tracker.state_path.read_bytes()
    with pytest.raises(LedgerConflict,match='historical'):
        settle_sell(tmp_path,sell_snapshot())
    assert tracker.state_path.read_bytes()==state
    assert FillLedger(tmp_path).get('sell1') is None


def test_two_incremental_observations_preserve_notional_and_replay(tmp_path):
    from stock_swing.tracking.settle_sell import settle_sell
    buy(PnLTracker(tmp_path))
    settle_sell(tmp_path,sell_snapshot(4))
    second=dict(sell_snapshot(10),filled_avg_price=112)
    settle_sell(tmp_path,second)
    assert settle_sell(tmp_path,second) is None
    closed=[t for t in PnLTracker(tmp_path).state.trades if t['status']=='closed']
    assert sorted(t['qty'] for t in closed)==[4,6]
    assert sum(t['qty']*t['exit_price'] for t in closed)==pytest.approx(1120)
    assert FillLedger(tmp_path).get('sell1')['consumed_qty']==10
    assert len([e for e in TradeEventStore(tmp_path).read_all() if e.event_type=='trade_closed'])==2


@pytest.mark.parametrize('content',['{broken\n','{}\n','[]\n'])
def test_corrupt_fill_evidence_is_not_skipped(tmp_path,content):
    folder=tmp_path/'data/tracking';folder.mkdir(parents=True)
    ledger=folder/'fill_ledger.jsonl';ledger.write_text(content)
    with pytest.raises(ValueError): FillLedger(tmp_path).ingest(sell_snapshot())
    assert ledger.read_text()==content


def test_uncoordinated_writer_change_aborts_before_journal_prepare(tmp_path):
    from stock_swing.tracking.ledger_transaction import ledger_transaction, LedgerConflict
    buy(PnLTracker(tmp_path))
    state_path=tmp_path/'data/tracking/pnl_state.json'
    with pytest.raises(LedgerConflict,match='uncoordinated'):
        with ledger_transaction(tmp_path):
            buy(PnLTracker(tmp_path),'buy2')
            data=json.loads(state_path.read_text());data['last_updated']='external-writer'
            state_path.write_text(json.dumps(data))
    assert json.loads(state_path.read_text())['last_updated']=='external-writer'
    assert len(json.loads(state_path.read_text())['trades'])==1
    assert not (tmp_path/'data/tracking/.ledger_transaction.json').exists()


def test_unsupported_target_cannot_escape_tracking_write_set(tmp_path):
    from stock_swing.tracking.ledger_transaction import stage_bytes, LedgerConflict
    outside=tmp_path/'outside.json'
    with pytest.raises(LedgerConflict): stage_bytes(tmp_path,outside,b'{}')
    assert not outside.exists()


def test_symlink_target_is_not_followed(tmp_path):
    from stock_swing.tracking.ledger_transaction import stage_bytes, LedgerConflict
    folder=tmp_path/'data/tracking';folder.mkdir(parents=True)
    outside=tmp_path/'outside.json';outside.write_text('original')
    (folder/'pnl_state.json').symlink_to(outside)
    with pytest.raises(LedgerConflict): stage_bytes(tmp_path,folder/'pnl_state.json',b'{}')
    assert outside.read_text()=='original'
