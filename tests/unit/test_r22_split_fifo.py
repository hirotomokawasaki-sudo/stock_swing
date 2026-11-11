"""Financial invariants, not a mirror of the FIFO implementation."""
from copy import deepcopy
from decimal import Decimal

import pytest
from scripts.rebuild_pnl_state_from_broker import match_buy_sell_orders
from stock_swing.tracking.pnl_tracker import TradeEntry


def order(identity, side, qty, price, time, **extra):
    return dict(id=identity, symbol='CRWD', side=side, filled_qty=str(qty),
                filled_avg_price=str(price), filled_at=time, status='filled', **extra)


def pair(removed=43, added=172, date='2026-07-06'):
    common = dict(symbol='CRWD', activity_type='SPLIT', activity_sub_type='FSPLIT',
                  corporate_action_id='ca-1', group_id='group-1', status='executed',
                  date=date, created_at='2026-07-07T16:49:23Z', net_amount='0')
    return [dict(common, id='remove', qty=str(-removed)), dict(common, id='add', qty=str(added))]


def split_orders():
    return [order('buy', 'buy', 43, '721.7525581395348837209302326', '2026-06-29T14:00:00Z'),
            order('sell-1', 'sell', 43, '194.79', '2026-07-06T14:00:00Z'),
            order('sell-2', 'sell', 129, '181.213333', '2026-07-13T14:00:00Z')]


def test_split_quantity_and_cost_conserved_and_schema_loadable():
    orders = split_orders()
    closed, opened = match_buy_sell_orders(orders, split_activities=pair())
    assert not opened
    assert [t['qty'] for t in closed] == [43, 129]
    assert sum(Decimal(str(t['entry_price'])) * t['qty'] for t in closed) == pytest.approx(Decimal('31035.36'))
    assert sum(t['pnl'] for t in closed) == pytest.approx(717.13)
    for row in closed:
        entry = TradeEntry(**row)
        assert entry.corporate_action_adjustments[0]['available_at'] == '2026-07-07T16:49:23+00:00'
        assert entry.corporate_action_adjustments[0]['effective_time_precision'] == 'date'
    assert match_buy_sell_orders(list(reversed(orders)), split_activities=list(reversed(pair()))) == (closed, opened)


def test_split_retains_open_cost_without_a_sell():
    closed, opened = match_buy_sell_orders(split_orders()[:1], split_activities=pair())
    assert not closed
    assert opened[0]['qty'] == 172
    assert opened[0]['entry_price'] * 172 == pytest.approx(31035.36)
    TradeEntry(**opened[0])


def test_future_buy_never_funds_prior_sell():
    with pytest.raises(ValueError, match='earlier inventory'):
        match_buy_sell_orders([order('sell', 'sell', 1, 110, '2026-06-01T14:00:00Z'),
                               order('buy', 'buy', 1, 100, '2026-06-02T14:00:00Z')])


def test_oversell_does_not_silently_disappear():
    with pytest.raises(ValueError, match='earlier inventory'):
        match_buy_sell_orders([order('b', 'buy', 1, 100, '2026-06-01T14:00:00Z'),
                               order('s', 'sell', 2, 110, '2026-06-02T14:00:00Z')])


def test_registry_alone_cannot_adjust_only_price():
    registry = [dict(symbol='CRWD', type='split', direction='forward', ex_date='2026-07-02', ratio=4)]
    with pytest.raises(ValueError, match='confirmed split evidence'):
        match_buy_sell_orders(split_orders(), registry)


def test_date_discrepancy_requires_explicit_mapping():
    registry = [dict(symbol='CRWD', type='split', direction='forward', ex_date='2026-07-02', ratio=4)]
    with pytest.raises(ValueError, match='confirmed split evidence'):
        match_buy_sell_orders(split_orders(), registry, split_activities=pair())
    closed, _ = match_buy_sell_orders(split_orders(), registry, split_activities=pair(),
                                     split_date_overrides={'group-1': '2026-07-02'})
    assert closed[0]['corporate_action_adjustments'][0]['registry_ex_date'] == '2026-07-02'


@pytest.mark.parametrize('change', ['one_leg', 'duplicate', 'cash', 'identity', 'status', 'inventory', 'available', 'fractional', 'subtype'])
def test_unproven_splits_fail_closed(change):
    acts = pair()
    if change == 'one_leg': acts.pop()
    elif change == 'duplicate': acts.append(deepcopy(acts[0]))
    elif change == 'cash': acts[0]['net_amount'] = '1'
    elif change == 'identity': acts[0]['corporate_action_id'] = 'other'
    elif change == 'status': acts[0]['status'] = 'pending'
    elif change == 'inventory': acts[0]['qty'] = '-42'
    elif change == 'available': acts[0]['created_at'] = None
    elif change == 'fractional': acts[1]['qty'] = '172.5'
    elif change == 'subtype': acts[0]['activity_sub_type'] = 'OTHER'
    with pytest.raises(ValueError):
        match_buy_sell_orders(split_orders(), split_activities=acts)


def test_reverse_split_fractional_lot_is_not_rounded_away():
    buys = [order('b1', 'buy', 1, 100, '2026-06-01T14:00:00Z'),
            order('b2', 'buy', 3, 100, '2026-06-02T14:00:00Z')]
    acts = pair(4, 1)
    for a in acts: a['activity_sub_type'] = 'RSPLIT'
    with pytest.raises(ValueError, match='fractional'):
        match_buy_sell_orders(buys, split_activities=acts)


@pytest.mark.parametrize('field,value', [('filled_qty','1.5'), ('filled_avg_price','nan'),
    ('filled_at','2026-06-01T14:00:00'), ('id',None), ('side','short'), ('filled_qty','-1')])
def test_invalid_orders_cannot_be_invented_or_truncated(field, value):
    row = order('b', 'buy', 1, 100, '2026-06-01T14:00:00Z'); row[field] = value
    with pytest.raises(ValueError): match_buy_sell_orders([row])


def test_duplicate_order_is_not_double_inventory():
    row = order('b', 'buy', 1, 100, '2026-06-01T14:00:00Z')
    with pytest.raises(ValueError, match='duplicate'):
        match_buy_sell_orders([row, deepcopy(row)])


def test_timezone_comparison_and_partial_cancel_preserve_raw_cost(monkeypatch):
    def forbidden(*a, **kw): raise AssertionError('current market prices are not execution evidence')
    monkeypatch.setattr('scripts.rebuild_pnl_state_from_broker.maybe_correct_scaled_price', forbidden)
    buy = order('b', 'buy', 3, '100.123456', '2026-06-02T00:00:00+09:00'); buy['status'] = 'canceled'
    closed, opened = match_buy_sell_orders([order('s', 'sell', 3, '110.987654', '2026-06-01T16:00:00Z'), buy])
    assert not opened
    assert closed[0]['entry_price'] == 100.123456
    assert closed[0]['pnl'] == 32.59


def test_equal_instant_opposite_orders_are_ambiguous():
    with pytest.raises(ValueError, match='ambiguous'):
        match_buy_sell_orders([order('b','buy',1,100,'2026-06-01T14:00:00Z'),
                               order('s','sell',1,110,'2026-06-01T14:00:00Z')])


@pytest.mark.parametrize('broker_positions', [{}, {'CRWD': {'qty':171,'avg_entry_price':180}}, {'OTHER': {'qty':172,'avg_entry_price':180}}])
def test_rebuild_boundary_does_not_replace_or_drop_split_lots(broker_positions):
    from scripts.rebuild_pnl_state_from_broker import reconcile_open_positions
    _, opened = match_buy_sell_orders(split_orders()[:1], split_activities=pair())
    with pytest.raises(ValueError, match='inventory'):
        reconcile_open_positions(opened, broker_positions, 0)


def test_rebuild_boundary_preserves_confirmed_lot_cost():
    from scripts.rebuild_pnl_state_from_broker import reconcile_open_positions
    _, opened = match_buy_sell_orders(split_orders()[:1], split_activities=pair())
    # Broker position averaging can use a different basis, not an individual lot.
    assert reconcile_open_positions(opened, {'CRWD': {'qty':172, 'avg_entry_price':999}}, 0) == opened


def test_failed_position_fetch_is_not_empty_inventory():
    from scripts.rebuild_pnl_state_from_broker import fetch_broker_open_positions
    class FailedBroker:
        def fetch_positions(self): raise RuntimeError('unavailable')
    with pytest.raises(ValueError, match='position evidence'):
        fetch_broker_open_positions(FailedBroker())


def test_truncated_history_is_not_a_complete_rebuild_input():
    from scripts.rebuild_pnl_state_from_broker import fetch_all_filled_orders
    class TruncatedBroker:
        def fetch_all_orders(self, **kw): return {'orders': [], 'truncated': True}
    with pytest.raises(ValueError, match='truncated'):
        fetch_all_filled_orders(TruncatedBroker())


def test_rebuild_integrates_split_evidence_and_preserves_risk_history(monkeypatch, tmp_path):
    import json
    from scripts import rebuild_pnl_state_from_broker as rebuild
    (tmp_path/'data').mkdir()
    (tmp_path/'data/corporate_actions.json').write_text(json.dumps({'actions':[
        dict(symbol='CRWD',type='split',ex_date='2026-07-02',ratio=4)]}))
    monkeypatch.setattr(rebuild, 'PROJECT_ROOT', tmp_path)
    class Broker:
        def fetch_all_orders(self, **kw): return {'orders':split_orders(),'truncated':False}
        def fetch_positions(self): return []
        def fetch_account(self): return {'id':'test-account'}
    meta=dict(baseline_date="2026-06-01",baseline_equity=100,peak_equity=120,max_drawdown_pct=.25,
        daily_snapshots=[{'date':'2026-06-05','equity':120},{'date':'2026-06-06','equity':90}])
    result=rebuild.rebuild_pnl_state(Broker(),meta,split_activities=pair(),split_date_overrides={'group-1':'2026-07-02'})
    assert result['cumulative_realized_pnl']==717.13
    assert result['total_trades']==2
    for key in ('peak_equity','max_drawdown_pct','daily_snapshots'): assert result[key]==meta[key]
    assert not (tmp_path/'data/tracking/pnl_state.json').exists()


def test_cli_rejects_bad_local_evidence_before_broker_access(monkeypatch, tmp_path):
    from scripts import rebuild_pnl_state_from_broker as rebuild
    path=tmp_path/'split.json'; path.write_text('{"activities": [] , "registry_date_overrides": {"unknown":"2026-07-02"}}')
    monkeypatch.setattr('sys.argv',['rebuild','--split-evidence-file',str(path)])
    def forbidden(*a,**kw): raise AssertionError('must not construct broker or fetch data')
    monkeypatch.setattr(rebuild,'BrokerClient',forbidden)
    assert rebuild.main()==1
