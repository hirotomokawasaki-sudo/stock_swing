"""Bounded K01/K02 contract diagnostics; not an order/fill replay."""
from datetime import datetime,timezone
from types import SimpleNamespace
import json
from stock_swing.cli.paper_demo import _filter_buys_by_cluster_cap
from stock_swing.risk.correlation_cluster import compute_cluster_exposures
from stock_swing.strategy_engine.base_strategy import CandidateSignal
from stock_swing.utils.signal_prioritization import prioritize_buy_signals_v2
from stock_swing.decision_engine.decision_engine import DecisionEngine
from stock_swing.core.runtime import RuntimeMode
from stock_swing.risk.same_symbol_cooldown import filter_buys_by_same_symbol_cooldown,SameSymbolCooldownConfig
now=datetime(2026,10,28,15,tzinfo=timezone.utc)
results={}
for name,holding,buys in [('cross_cap',34000,[('MSFT',3000)]),('at_cap',35000,[('MSFT',1000)]),('batch',30000,[('MSFT',3000),('CRM',3000)])]:
 positions={'NOW':dict(symbol='NOW',market_value=holding,qty=100,current_price=holding/100)}
 ds=[SimpleNamespace(action='buy',symbol=sym,proposed_order=SimpleNamespace(qty=notional/100,limit_price=100)) for sym,notional in buys]
 allowed,blocked=_filter_buys_by_cluster_cap(ds,positions,100000)
 projected=holding+sum(v for _,v in buys)
 results[name]=dict(holding=holding,proposed_total=sum(v for _,v in buys),projected_cloud_notional=projected,cloud_cap=35000,
                    allowed_symbols=[d.symbol for d in allowed],blocked=blocked,guard_reads_proposed_notional=False)
assert results['cross_cap']['allowed_symbols']==['MSFT']
assert len(results['batch']['allowed_symbols'])==2
assert results['batch']['projected_cloud_notional']>35000
candidates=[CandidateSignal(strategy_id=st,symbol='AAPL',action='buy',signal_strength=.95,
    generated_at=now,time_horizon='5d',confidence=.95,reasoning='synthetic contract case') for st in ['breakout_momentum_v1','event_swing_v1']]
prioritized=prioritize_buy_signals_v2(candidates,{},equity=100000)
engine=DecisionEngine(RuntimeMode.PAPER)
ds=[engine.process(c,current_positions={}) for c in prioritized]
allowed,blocked=filter_buys_by_same_symbol_cooldown(ds,[],SameSymbolCooldownConfig(),now=now)
results['same_symbol_buy']=dict(actions=[d.action for d in allowed],strategies=[d.strategy_id for d in allowed],decision_ids=[d.decision_id for d in allowed],blocked=blocked)
assert [d.action for d in allowed]==['buy','buy'] and len({d.decision_id for d in allowed})==2
sell=CandidateSignal(strategy_id='simple_exit_v2',symbol='AAPL',action='sell',signal_strength=.95,generated_at=now,time_horizon='1d',confidence=.95,reasoning='synthetic protective exit')
conflict=[engine.process(candidates[0],current_positions={'AAPL':10}),engine.process(sell,current_positions={'AAPL':10})]
allowed,blocked=filter_buys_by_same_symbol_cooldown(conflict,[],SameSymbolCooldownConfig(),now=now)
results['buy_sell_conflict']=dict(actions=[d.action for d in allowed],blocked=blocked)
assert results['buy_sell_conflict']['actions']==['buy','sell']
results['limitations']=['helper chain only, not complete paper_demo submit/reconcile path','not actual cap violation or duplicate fills','no K01/K02 policy or code change']
print(json.dumps(results,indent=2,sort_keys=True))
