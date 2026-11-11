"""Regression 2026-10-21 R22: raw readers and hidden writer bypasses."""
import json
from types import SimpleNamespace

import pytest

from tests.unit.test_r22_history_migration import fixture_plan
from stock_swing.tracking.history_migration import apply_migration
from stock_swing.tracking.ledger_transaction import LedgerConflict


def migrated(root):
    _,_,plan=fixture_plan(root);apply_migration(root,plan)
    return root/'data/tracking/pnl_state.json'


def test_ac_market_audit_rejects_damaged_pair_before_any_external_fetch(tmp_path,monkeypatch):
    from scripts import audit_trades_with_market_data as m
    path=migrated(tmp_path);(path.parent/'trade_events.jsonl').write_text('corrupt\n')
    calls=[]
    monkeypatch.setattr(m,'PROJECT_ROOT',tmp_path)
    monkeypatch.setattr('sys.argv',['audit','--symbols','NOT_PRESENT'])
    monkeypatch.setattr(m,'fetch_yahoo_finance_bars',lambda *a:(calls.append('market') or {}))
    monkeypatch.setattr(m,'load_broker_positions',lambda *a:(calls.append('broker') or []))
    assert m.main()==2
    assert calls==[], 'no broker/market I/O before state/event coherence'


def test_ac_missing_corporate_tracker_is_unavailable_not_clean_empty(tmp_path,monkeypatch):
    from scripts import check_corporate_actions as m
    monkeypatch.setattr(m,'PNL_STATE_PATH',tmp_path/'data/tracking/pnl_state.json')
    with pytest.raises((FileNotFoundError,LedgerConflict)):
        m._get_tracker_open()


def test_ac_corporate_detection_refuses_prepared_writer_before_broker(tmp_path,monkeypatch):
    from scripts import check_corporate_actions as m
    path=migrated(tmp_path)
    journal=path.parent/'.ledger_transaction.json';journal.write_text('{"state":"prepared"}')
    monkeypatch.setattr(m,'PNL_STATE_PATH',path)
    def forbidden():raise AssertionError('broker must not precede coherent state')
    monkeypatch.setattr(m,'_get_broker_positions',forbidden)
    before={p.name:p.read_bytes() for p in path.parent.iterdir() if p.is_file()}
    with pytest.raises(LedgerConflict):m.detect_anomalies()
    assert before=={p.name:p.read_bytes() for p in path.parent.iterdir() if p.is_file()}


def test_ac_broker_only_fetch_does_not_create_or_load_a_tracker(tmp_path,monkeypatch):
    from scripts import check_corporate_actions as m
    from stock_swing.sources import broker_client
    calls=[]
    class Broker:
        def __init__(self,**kw):
            assert kw['paper_mode'] is True
        def fetch_positions(self):calls.append('fetch');return SimpleNamespace(payload=[])
    monkeypatch.setattr(broker_client,'BrokerClient',Broker)
    monkeypatch.setattr(m,'PROJECT_ROOT',tmp_path)
    monkeypatch.setenv('BROKER_API_KEY','fixture-key');monkeypatch.setenv('BROKER_API_SECRET','fixture-secret')
    assert m._get_broker_positions()==[]
    assert calls==['fetch']
    assert not list(tmp_path.rglob('*')), 'broker-only GET cannot create tracking state or locks'


def test_ac_invariants_refuse_unversioned_export_even_when_sum_matches(tmp_path,monkeypatch,capsys):
    from scripts import check_pnl_invariants as m
    path=migrated(tmp_path);state=json.loads(path.read_text())
    perf=tmp_path/'data/analysis/performance_summary.json';perf.parent.mkdir()
    perf.write_text(json.dumps({'realized_pnl':state['cumulative_realized_pnl']}))
    monkeypatch.setattr(m,'STATE_PATH',path);monkeypatch.setattr(m,'PERF_PATH',perf)
    assert m.main()!=0
    assert 'All invariants PASS' not in capsys.readouterr().out


@pytest.mark.parametrize('kind',['migrated','missing','corrupt'])
def test_ac_legacy_backtest_loader_never_launders_unsupported_data_as_trades_or_empty(tmp_path,kind):
    from stock_swing.backtest.data_loader import DataLoader
    if kind=='migrated':migrated(tmp_path)
    if kind=='corrupt':
        p=tmp_path/'data/tracking/pnl_state.json';p.parent.mkdir(parents=True);p.write_text('{')
    with pytest.raises((LedgerConflict,ValueError,FileNotFoundError)):
        DataLoader(tmp_path).load_trades()


@pytest.mark.parametrize('field', ['qty', 'entry_price'])
@pytest.mark.parametrize('bad', [float('nan'), float('inf'), True, None, 'broken', 0, -1, 1e309])
def test_ac_corporate_cannot_drop_invalid_open_lots(field, bad):
    from scripts import check_corporate_actions as m
    trade = {'symbol':'TEST', 'status':'open', 'qty':1, 'entry_price':10}
    trade[field] = bad
    with pytest.raises((ValueError, TypeError)):
        m._get_tracker_open({'trades':[trade]})


def test_ac_corporate_aggregate_overflow_is_unavailable():
    from scripts import check_corporate_actions as m
    with pytest.raises(ValueError):
        m._get_tracker_open({'trades':[{'symbol':'TEST','status':'open','qty':1e308,'entry_price':1e308}]})


@pytest.mark.parametrize('broker_row', [{}, {'symbol':'TEST','qty':'1','avg_entry_price':'NaN'},
    {'symbol':'TEST','qty':True,'avg_entry_price':10}])
def test_ac_broken_broker_rows_are_not_an_empty_clean_check(monkeypatch, broker_row):
    from scripts import check_corporate_actions as m
    monkeypatch.setattr(m, '_load_known_actions', lambda:set())
    monkeypatch.setattr(m, '_get_broker_positions', lambda:[broker_row])
    with pytest.raises((ValueError, TypeError)):
        m.detect_anomalies(tracker_open={})


@pytest.mark.parametrize('bars', [{}, {'2026-10-19':(9,11,10)},
    {'2026-10-19':(9,11,10), '2026-10-20':(9,float('nan'),10)}])
def test_ac_incomplete_market_audit_never_reports_success(tmp_path,monkeypatch,capsys,bars):
    from scripts import audit_trades_with_market_data as m
    path=tmp_path/'data/tracking/pnl_state.json';path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'trades':[{'symbol':'TEST','status':'closed','entry_time':'2026-10-19T15:00:00Z',
        'exit_time':'2026-10-20T15:00:00Z','entry_price':10,'exit_price':10,'pnl':0,
        'asset_class':'stock','holding_days':1}], 'cumulative_realized_pnl':0}))
    before=path.read_bytes()
    monkeypatch.setattr(m,'PROJECT_ROOT',tmp_path)
    monkeypatch.setattr('sys.argv',['audit'])
    monkeypatch.setattr(m,'fetch_yahoo_finance_bars',lambda *a:bars)
    monkeypatch.setattr(m,'load_broker_positions',lambda *a:[])
    assert m.main()==2
    assert 'No price anomalies, tracker issues' not in capsys.readouterr().out
    assert path.read_bytes()==before


def test_ac_legacy_loader_still_returns_valid_explicit_empty_history(tmp_path):
    from stock_swing.backtest.data_loader import DataLoader
    path=tmp_path/'data/tracking/pnl_state.json';path.parent.mkdir(parents=True)
    path.write_text('{"trades":[]}')
    assert DataLoader(tmp_path).load_trades()==[]


def test_ac_legacy_equity_adjustment_refuses_migrated_input_before_broker_or_save(tmp_path,monkeypatch):
    from scripts import reconcile_equity_bridge as m
    migrated(tmp_path)
    output=tmp_path/'data/audits/equity_bridge_reconciliation.json';output.parent.mkdir()
    output.write_text('previous audited result')
    monkeypatch.setattr(m,'PROJECT_ROOT',tmp_path);monkeypatch.setattr(m,'OUTPUT_PATH',output)
    monkeypatch.setattr('sys.argv',['bridge','--save'])
    def forbidden(*a,**k):raise AssertionError('unsupported history must not fetch broker')
    monkeypatch.setattr(m,'BrokerClient',forbidden)
    assert m.main()==2
    assert output.read_text()=='previous audited result'


@pytest.mark.parametrize('bad_fields', [
    {'pnl':True, 'cumulative_realized_pnl':True},
    {'pnl':float('nan'), 'cumulative_realized_pnl':float('nan')},
    {'pnl':float('inf'), 'cumulative_realized_pnl':float('inf')},
    {'entry_time':'2026-10-19BAD', 'exit_time':'2026-10-20BAD'},
    {'entry_time':None},
])
def test_ac_market_audit_refuses_invalid_closed_financial_fields(tmp_path,monkeypatch,capsys,bad_fields):
    from scripts import audit_trades_with_market_data as m
    trade={'symbol':'TEST','status':'closed','entry_time':'2026-10-19T15:00:00Z',
           'exit_time':'2026-10-20T15:00:00Z','entry_price':10,'exit_price':10,
           'pnl':0,'asset_class':'stock','holding_days':1}
    trade.update({k:v for k,v in bad_fields.items() if k!='cumulative_realized_pnl'})
    path=tmp_path/'data/tracking/pnl_state.json';path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'trades':[trade], 'cumulative_realized_pnl':bad_fields.get('cumulative_realized_pnl',0)}))
    monkeypatch.setattr(m,'PROJECT_ROOT',tmp_path);monkeypatch.setattr('sys.argv',['audit'])
    monkeypatch.setattr(m,'fetch_yahoo_finance_bars',lambda *a:{'2026-10-19':(9,11,10),'2026-10-20':(9,11,10)})
    monkeypatch.setattr(m,'load_broker_positions',lambda *a:[])
    assert m.main()==2
    assert 'No price anomalies, tracker issues' not in capsys.readouterr().out


@pytest.mark.parametrize('target',['corporate','bridge'])
def test_ac_public_legacy_writers_cannot_bypass_migration_guard(tmp_path,monkeypatch,target):
    path=migrated(tmp_path)
    before={n:(path.parent/n).read_bytes() for n in ('pnl_state.json','trade_events.jsonl','fill_ledger.jsonl','fill_consumed_ledger.json')}
    if target=='corporate':
        from scripts import check_corporate_actions as m
        output=tmp_path/'data/corporate_actions.json'
        monkeypatch.setattr(m,'CORPORATE_ACTIONS_PATH',output)
        invoke=lambda:m.register_action({'symbol':'TEST'})
    else:
        from scripts import reconcile_equity_bridge as m
        output=tmp_path/'data/audits/equity_bridge_reconciliation.json'
        invoke=lambda:m._atomic_write_json(output,{'unqualified':True})
    with pytest.raises(LedgerConflict):
        invoke()
    assert not output.exists()
    assert before=={n:(path.parent/n).read_bytes() for n in before}


def test_ac_equity_writer_refuses_noncanonical_root_without_creating_files(tmp_path):
    from scripts import reconcile_equity_bridge as m
    with pytest.raises(LedgerConflict,match='unsupported adjustment'):
        m._atomic_write_json(tmp_path/'unexpected.json',{})
    assert not list(tmp_path.iterdir())
