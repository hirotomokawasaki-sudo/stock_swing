"""Regression 2026-11-04 FIX-03/K03, base 8909e79: precomputed BUY bypass.
Acceptance: unreadable or malformed risk inputs never become measured zero.
Only external broker I/O is substituted; executor/sizing logic remains real.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
import pytest
from stock_swing.core.runtime import RuntimeMode
from stock_swing.decision_engine.decision_engine import DecisionRecord, ProposedOrder
from stock_swing.execution.paper_executor import PaperExecutor

class Broker:
    def __init__(self, positions=None, equity=100000, failure=None):
        self.positions = [] if positions == "flat" else positions
        self.equity, self.failure, self.sent = equity, failure, []
    def fetch_account(self):
        if self.failure == "account": raise OSError("fixture account unavailable")
        return SimpleNamespace(payload={"equity": self.equity})
    def fetch_positions(self):
        if self.failure == "positions": raise OSError("fixture positions unavailable")
        return SimpleNamespace(payload=self.positions)
    def fetch_bars(self, *args, **kwargs):
        return SimpleNamespace(payload={"bars": [{"c": 100}]})
    def fetch_quote(self, *args, **kwargs):
        return SimpleNamespace(payload={"quote": {"bp": 99, "ap": 101}})
    def submit_order(self, **kwargs):
        self.sent.append(kwargs)
        return {"id": "fixture-order", "status": "accepted"}

def decision(side="buy"):
    return DecisionRecord(decision_id="k03-"+side, schema_version="v1",
        generated_at=datetime.now(timezone.utc), mode="paper", strategy_id="breakout_momentum_v1",
        strategy_version_id="fixture", symbol="AAPL", action=side, confidence=.8,
        signal_strength=.8, risk_state="pass", deny_reasons=[], requires_operator_approval=False,
        time_horizon="5d", evidence={}, proposed_order=ProposedOrder(symbol="AAPL",
            side=side, order_type="market", qty=2, time_in_force="day"))

@pytest.mark.parametrize("positions", [None, {}, [None],
    [{"symbol":"MSFT","qty":"bad","current_price":100}],
    [{"symbol":"MSFT","qty":1}],
    [{"symbol":"MSFT","qty":1,"current_price":float("nan")}],
    [{"symbol":"MSFT","qty":float("inf"),"current_price":100}]])
def test_ac_precomputed_buy_does_not_bypass_unknown_holdings(positions):
    b=Broker(positions); e=PaperExecutor(RuntimeMode.PAPER,b)
    with pytest.raises(ValueError, match="risk_inputs_unavailable"):
        e.submit(decision(),precomputed_qty=2,precomputed_sizing={"final_shares":2})
    assert b.sent == [], "precomputed quantity must not bypass unavailable exposure"

@pytest.mark.parametrize("failure", ["account", "positions"])
@pytest.mark.parametrize("precomputed", [False, True])
def test_ac_broker_io_failure_denies_buy_but_preserves_verified_sell(failure, precomputed):
    b=Broker("flat",failure=failure); e=PaperExecutor(RuntimeMode.PAPER,b)
    kw=dict(precomputed_qty=2,precomputed_sizing={"final_shares":2}) if precomputed else {}
    with pytest.raises(ValueError, match="risk_inputs_unavailable"):
        e.submit(decision(),**kw)
    assert not b.sent, "unavailable broker inputs must not send BUY"
    sell=e.submit(decision("sell"),current_qty=10,**kw)
    assert sell.side == "sell" and sell.qty == (2 if precomputed else 10), "confirmed SELL must remain available"
    assert len(b.sent)==1 and b.sent[0]["side"]=="sell", "only verified SELL crosses fixture boundary"

@pytest.mark.parametrize("equity", [None, True, "bad", 0, float("nan"), float("inf")])
def test_ac_precomputed_buy_requires_measurable_equity(equity):
    b=Broker("flat",equity=equity); e=PaperExecutor(RuntimeMode.PAPER,b)
    with pytest.raises(ValueError, match="risk_inputs_unavailable"):
        e.submit(decision(),precomputed_qty=2,precomputed_sizing={"final_shares":2})
    assert not b.sent, "invalid account equity is not a sizing authorization"

@pytest.mark.parametrize("qty", [True, 1.5, float("nan"), float("inf"), "2", -1, 0])
def test_ac_invalid_precomputed_quantity_is_never_sent(qty):
    b=Broker("flat"); e=PaperExecutor(RuntimeMode.PAPER,b)
    with pytest.raises(ValueError):
        e.submit(decision(),precomputed_qty=qty,precomputed_sizing={"final_shares":qty})
    assert not b.sent, "invalid quantity must not reach broker"

def test_ac_failed_precomputed_measurement_cannot_be_relabeled_valid():
    b=Broker("flat"); e=PaperExecutor(RuntimeMode.PAPER,b)
    with pytest.raises(ValueError, match="risk_inputs_unavailable"):
        e.submit(decision(),precomputed_qty=2,precomputed_sizing={"skip_reason":"risk_inputs_unavailable"})
    assert not b.sent, "failed sizing must be recomputed, not used as permission"

def test_ac_valid_precomputed_quantity_is_preserved_after_input_check():
    b=Broker("flat"); e=PaperExecutor(RuntimeMode.PAPER,b)
    qty,details=e._calculate_position_size(decision())
    assert qty > 0, "normal sizing fixture must be usable"
    sub=e.submit(decision(),precomputed_qty=qty,precomputed_sizing=details)
    assert sub.qty==qty and b.sent[0]["qty"]==qty, "risk-input validation must not adopt a new quantity policy"
