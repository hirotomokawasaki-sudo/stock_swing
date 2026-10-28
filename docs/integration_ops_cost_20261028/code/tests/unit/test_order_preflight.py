"""K01/K02 regression: post-purchase cap/ambiguous intents, base 8909e79, 2026-10-28.

Acceptance contracts use independent arithmetic, real allocator and real CLI
separately. Broker doubles below replace external IO only. No trading evidence.
"""
from decimal import Decimal
from types import SimpleNamespace as NS
import json
import pytest
from stock_swing.risk.order_preflight import OrderPreflight, buy_conflicts, snapshot_from_broker
from stock_swing.risk.portfolio_allocator import PortfolioAllocator


def position(symbol="NOW", value=30000, qty=100):
    return {symbol: {"symbol": symbol, "market_value": value, "qty": qty}}


def order(**changes):
    return dict(dict(id="external-1", symbol="CRM", side="buy", qty="10", filled_qty="0", status="new", type="market", order_class="simple"), **changes)


def book(positions=None, orders=None, **kwargs):
    return OrderPreflight({} if positions is None else positions, 100000, [] if orders is None else orders,
                          complete=True, price_lookup=lambda symbol: 100, **kwargs)


def intent(ident, symbol="MSFT", side="buy"):
    return NS(decision_id=ident, proposed_order=NS(symbol=symbol, side=side), evidence={"strategy_id": ident})


@pytest.mark.parametrize("holding,amount,allowed", [(30000,5000,True),(30000,5001,False),(35000,1,False),(0,1000,True)])
def test_ac_projected_cluster_exact_and_above(holding, amount, allowed):
    result=book(position(value=holding,qty=0 if holding==0 else 100)).reserve("d", "MSFT", 1, amount, .08)
    assert result["allowed"] is allowed, result


@pytest.mark.parametrize("amount,allowed", [(8000,True),(8001,False)])
def test_ac_new_symbol_cap(amount,allowed):
    result=book().reserve("d","MSFT",1,amount,.08)
    assert result["allowed"] is allowed, result


def test_ac_overlap_hyperscale_is_not_only_cloud():
    result=book(position("AMZN",34000)).reserve("d","MSFT",20,100,.08)
    assert result["reason"] == "projected_cluster_cap_exceeded" and result["cluster"]=="hyperscale", result


def test_ac_batch_reservation_and_repeat_cannot_release():
    b=book(position(value=30000))
    assert b.reserve("a","MSFT",30,100,.08)["allowed"], "first 3k fits"
    b.observe_submission("a","submitted")
    assert b.reserve("a","MSFT",1,100,.08)["reason"]=="duplicate_or_invalid_decision_id", "same intent not duplicated"
    result=b.reserve("b","CRM",30,100,.08)
    assert not result["allowed"] and result["projected_cluster_notional"]=="36000", result
    assert b.projected_positions()["MSFT"]["market_value"]==pytest.approx(3000), "hold accepted amount"


@pytest.mark.parametrize("status", ["new","partially_filled","pending_cancel","pending_replace","done_for_day"])
def test_ac_pending_remaining_and_no_cancel_credit(status):
    b=book(position(value=33000),[order(status=status, qty="30", filled_qty="10")])
    result=b.reserve("d","MSFT",1,100,.08)
    assert b.values["CRM"]==Decimal("2000") and not result["allowed"], result


@pytest.mark.parametrize("status", ["filled","canceled","expired","rejected","replaced"])
def test_ac_confirmed_terminal_snapshot_releases_remaining(status):
    b=book(position(value=33000),[order(status=status)])
    assert b.reserve("d","MSFT",20,100,.08)["allowed"], "terminal does not reserve"


def test_ac_pending_sell_never_frees_capacity():
    b=book(position(value=35000),[order(symbol="NOW",side="sell",qty="100")])
    assert not b.reserve("d","MSFT",1,100,.08)["allowed"], "pending SELL cannot finance new BUY"


@pytest.mark.parametrize("side", ["buy","sell"])
def test_ac_same_symbol_open_order_holds_new_buy(side):
    result=book(orders=[order(symbol="MSFT",side=side)]).reserve("d","MSFT",1,100,.08)
    assert result["reason"]=="same_symbol_open_order", result


@pytest.mark.parametrize("changes", [dict(qty="nan"),dict(qty="1.5"),dict(filled_qty="inf"),dict(filled_qty="11"),dict(filled_qty="10"),dict(status="mystery"),dict(side="mystery"),dict(order_class="bracket"),dict(legs=[{}]),dict(notional="1000"),dict(type="stop"),dict(symbol=""),dict(id="")])
def test_ac_malformed_pending_is_unknown(changes):
    b=book(orders=[order(**changes)])
    assert not b.available and not b.reserve("d","MSFT",1,100,.08)["allowed"], changes


@pytest.mark.parametrize("value", [None,"nan","inf",-1,True,{},"bad"])
def test_ac_invalid_position_market_value_is_not_zero(value):
    b=book(position(value=value))
    assert not b.available and not b.reserve("d","MSFT",1,100,.08)["allowed"], value


@pytest.mark.parametrize("value", [None,"nan","inf",-1,0,True])
def test_ac_bad_equity_and_price_block(value):
    b=OrderPreflight({},value,[],complete=True,price_lookup=lambda s:100)
    assert not b.available, value
    assert not book().reserve("d","MSFT",1,value,.08)["allowed"], value


def test_ac_decimal_no_money_tolerance():
    b=book(position(value="34999.99"))
    assert b.reserve("a","MSFT",1,"0.01",.08)["allowed"], "exact cent fits"
    assert not b.reserve("b","CRM",1,"0.0001",.08)["allowed"], "no floating tolerance admits overage"


@pytest.mark.parametrize("status", ["rejected","unknown","pending"])
def test_ac_outcome_unknown_poison_retains_reservation(status):
    b=book()
    assert b.reserve("a","MSFT",10,100,.08)["allowed"], "reserve first"
    b.observe_submission("a",status)
    assert not b.reserve("b","CRM",1,100,.08)["allowed"] and "a" in b.reservations, "never release based on rejected label"
    assert book().reserve("b","CRM",1,100,.08)["allowed"], "new verified snapshot can recover; no durable intent claim"


def test_ac_duplicate_pending_id_and_invalid_caps():
    assert not book(orders=[order(),order()]).available, "cannot guess dedup identity"
    assert not book(cluster_caps={"cloud_software":"nan"}).available, "invalid config fail closed"
    assert not book(cluster_caps={"unknown":.2}).available, "unknown cap fail closed"
    assert book(cluster_caps={}).reserve("d","MSFT",1,100,.08)["allowed"], "explicit measured cluster override"


def test_ac_limit_reservation_uses_larger_qualified_quote():
    b=book(orders=[order(type="limit",limit_price="150")])
    assert b.values["CRM"]==Decimal("1500"), "pending limit not undercounted"


@pytest.mark.parametrize("payload", [None,{},"bad",[order(id=str(i)) for i in range(500)]])
def test_ac_incomplete_single_page_fails_closed(payload):
    b=snapshot_from_broker(NS(fetch_orders=lambda **k:NS(payload=payload)),{},100000,lambda s:100)
    assert not b.available, "unknown/at-limit page not complete"


def test_ac_broker_fetch_exception_is_unknown_then_recovers():
    def fail(**kw): raise OSError("fixture transport failure")
    assert not snapshot_from_broker(NS(fetch_orders=fail),{},100000,lambda s:100).available, "I/O fail closed"
    calls=[]
    def ok(**kw): calls.append(kw); return NS(payload=[])
    assert snapshot_from_broker(NS(fetch_orders=ok),{},100000,lambda s:100).available, "confirmed empty orders are valid"
    assert calls==[{"status":"open","limit":500}], calls


def test_ac_attribution_and_sell_are_preserved_without_netting():
    decisions=[intent("A"),intent("B"),intent("exit",side="sell"),intent("other","CRM")]
    original=json.dumps([d.evidence for d in decisions])
    held=buy_conflicts(decisions)
    assert set(held)=={"A","B"}, held
    assert held["A"]["related_decision_ids"]==["A","B","exit"], held
    assert original==json.dumps([d.evidence for d in decisions]), "do not rewrite originals"
    assert buy_conflicts([intent("A"),intent("B")])["A"]["reason"]=="same_symbol_duplicate_buy", "no winner"
    assert buy_conflicts([])=={}, "empty is valid"
    assert buy_conflicts([intent("exit",side="sell")])=={}, "SELL remains with existing checks"


def test_ac_real_allocator_includes_pending_and_same_run():
    allocator=PortfolioAllocator()
    # Existing stock band maximum, not a new target. Current plus pending crosses it.
    b=book(position("AAPL",91000),[order(symbol="CRM",qty="15")],cluster_caps={})
    result=b.reserve("d","MSFT",1,100,.08,allocator=allocator)
    assert not result["allowed"] and result["reason"].startswith("projected_allocation_band:"), result
