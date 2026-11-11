"""R22 AMAT 2026-10-14 regression; base 1e0c682. No broker/network writes."""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pytest

from stock_swing.cli import reconcile_orders
from stock_swing.tracking.pnl_tracker import PnLTracker


def order(qty=144, price='453.345694'):
    return dict(id='sell', symbol='AMAT', side='sell', status='filled', filled_qty=qty,
                filled_avg_price=price, filled_at='2026-10-14T13:34:00+00:00',
                submitted_at='2026-10-14T13:30:00+00:00')


def leg(qty=98, price='453.18'):
    return dict(trade_id='lot', execution_leg_id='lot-leg-1', symbol='AMAT',
                status='closed', qty=qty, exit_price=price, exit_broker_order_id='sell')


def delta(o, rows, consumed=0):
    from stock_swing.tracking.execution_cost import incremental_sell_fill
    return incremental_sell_fill(o, rows, consumed_qty=consumed)


def test_ac_amat_incremental_vwap_conserves_cumulative_proceeds():
    result = delta(order(), [leg()], 98)
    assert result.qty == 46, 'consume only remaining 46 shares'
    assert float(result.price) == pytest.approx(453.6986942608696), 'remaining VWAP is not whole-order VWAP'
    assert Decimal('98')*Decimal('453.18') + result.notional == Decimal('144')*Decimal('453.345694'), 'cumulative notional must be conserved'


@pytest.mark.parametrize('case', ['missing_price','nan','negative_price','fractional_qty','quantity_decrease','same_qty_revision','missing_prior_price','duplicate_leg','wrong_symbol','ledger_ahead','nonpositive_increment'])
def test_ac_ambiguous_economics_rejected(case):
    o, rows, consumed = order(), [leg()], 98
    if case == 'missing_price': o.pop('filled_avg_price')
    if case == 'nan': o['filled_avg_price'] = 'NaN'
    if case == 'negative_price': o['filled_avg_price'] = -1
    if case == 'fractional_qty': o['filled_qty'] = '144.5'
    if case == 'quantity_decrease': o['filled_qty'] = 97
    if case == 'same_qty_revision': o.update(filled_qty=98, filled_avg_price='454')
    if case == 'missing_prior_price': rows[0].pop('exit_price')
    if case == 'duplicate_leg': rows.append(deepcopy(rows[0]))
    if case == 'wrong_symbol': rows[0]['symbol'] = 'OTHER'
    if case == 'ledger_ahead': consumed = 100
    if case == 'nonpositive_increment': o['filled_avg_price'] = 1
    from stock_swing.tracking.execution_cost import ExecutionCostError
    with pytest.raises(ExecutionCostError):
        delta(o, rows, consumed)


def test_ac_complete_fill_is_noop_and_first_fill_uses_full_notional():
    assert delta(order(98,'453.18'), [leg()],98).qty == 0, 'identical cumulative observation is not a new execution'
    first = delta(order(98,'453.18'), [])
    assert first.price == Decimal('453.18'), 'first observation has no prior notional to subtract'


def tracker_entry(root, symbol='AMAT', qty=144, price=519.99, oid='buy'):
    tracker=PnLTracker(root)
    tracker.record_submission(symbol,'test','buy',qty,price,oid,'decision-'+oid)
    tracker.state.trades[-1]['entry_time']='2026-10-07T19:55:00+00:00'
    tracker._save_state()
    return tracker


class Broker:
    def __init__(self, orders, positions=None):
        self.orders=orders
        self.positions=positions or []
    def get_order(self, oid):
        return SimpleNamespace(payload=self.orders[oid])
    def fetch_positions(self):
        return SimpleNamespace(payload=self.positions)


def buy(oid='buy', qty=144, price='521.283125'):
    return dict(id=oid,symbol='AMAT',side='buy',status='filled',filled_qty=qty,filled_avg_price=price,
                filled_at='2026-10-07T19:56:00+00:00')


def test_ac_confirmed_buy_cost_below_five_percent_is_corrected(tmp_path):
    tracker=tracker_entry(tmp_path)
    assert reconcile_orders.reconcile_stale_entry_prices(Broker({'buy':buy()}),tracker)==1, 'small actual fill differences must not be ignored'
    saved=PnLTracker(tmp_path).get_open_positions()[0]
    assert saved['entry_price']==pytest.approx(521.283125), 'use confirmed order VWAP'
    assert saved['entry_reference_price']==pytest.approx(519.99), 'retain original reference price'


def test_ac_buy_prices_remain_per_order_not_symbol_scaled(tmp_path):
    tracker=tracker_entry(tmp_path,qty=10,price=100,oid='a')
    tracker.record_submission('AMAT','test','buy',20,200,'b','another-decision')
    broker=Broker({'a':buy('a',10,101),'b':buy('b',20,201)})
    reconcile_orders.reconcile_stale_entry_prices(broker,tracker)
    prices={t['broker_order_id']:t['entry_price'] for t in tracker.get_open_positions()}
    assert prices=={'a':pytest.approx(101),'b':pytest.approx(201)}, 'do not proportionally scale both lots by symbol average'


@pytest.mark.parametrize('case',['missing_order','split_qty','already_closed','wrong_identity','missing_qty'])
def test_ac_unproven_buy_cost_never_overwrites_history(tmp_path,case):
    tracker=tracker_entry(tmp_path)
    o=buy()
    if case=='missing_order': o={}
    if case=='split_qty': o['filled_qty']=36
    if case=='wrong_identity': o['symbol']='OTHER'
    if case=='missing_qty': o.pop('filled_qty')
    if case=='already_closed': tracker.record_exit('AMAT',453.18,98,'sell')
    before=deepcopy(tracker.state.trades)
    reconcile_orders.reconcile_stale_entry_prices(Broker({'buy':o}),tracker)
    assert tracker.state.trades==before, 'ambiguous or partially closed cost needs explicit repair, not automatic rewriting'


def test_ac_real_reconcile_entry_then_partial_completion(tmp_path,monkeypatch):
    """Only external BrokerClient and root/environment are substituted; real main/helpers execute."""
    tracker=tracker_entry(tmp_path)
    broker=Broker({'buy':buy()})
    reconcile_orders.reconcile_stale_entry_prices(broker,tracker)
    tracker.record_exit('AMAT',453.18,98,'sell',exit_reason='stop_loss')
    from stock_swing.tracking.fill_ledger import FillLedger
    fills=FillLedger(tmp_path)
    key=fills.ingest(dict(order(98,'453.18'),qty=98))
    fills.consume(key,'first-leg',98)
    (tmp_path/'data/audits').mkdir(exist_ok=True)
    (tmp_path/'data/audits/paper_demo_case.log').write_text('2026-10-14T13:30:00+00:00 | INFO | submission | paper | test | sub-1 | Order submitted: sell 144 AMAT\n')
    class Api(Broker):
        def __init__(self,*args,**kwargs): super().__init__({'buy':buy()})
        def fetch_orders(self,status='all',limit=500): return SimpleNamespace(payload=[] if status=='open' else [order()])
        def fetch_latest_quote(self,symbol): return SimpleNamespace(payload={'quote':{'bp':453,'ap':455}})
    monkeypatch.setattr(reconcile_orders,'BrokerClient',Api)
    monkeypatch.setattr(reconcile_orders,'project_root',tmp_path)
    monkeypatch.setenv('BROKER_API_KEY','test-only');monkeypatch.setenv('BROKER_API_SECRET','test-only')
    assert reconcile_orders.main()==0, 'actual cron path must reconcile known remaining execution'
    saved=PnLTracker(tmp_path)
    closed=[t for t in saved.state.trades if t['status']=='closed']
    assert sum(t['qty'] for t in closed)==144, 'no duplicate quantity'
    assert sum(t['pnl'] for t in closed)==pytest.approx(-9782.99), 'BUY confirmed cost and incremental SELL economics must propagate to PnL'
    assert reconcile_orders.main()==0, 'second observation must not create another execution'
    assert len(PnLTracker(tmp_path).state.trades)==len(saved.state.trades), 'replay must not add legs'
