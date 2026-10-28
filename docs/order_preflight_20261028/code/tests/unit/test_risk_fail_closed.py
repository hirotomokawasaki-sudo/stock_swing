"""Acceptance K03; 2026-10-28 risk-unknown BUY leak at base 8909e79.

Exercise production logic, substituting broker I/O only. No monetary outcome
is measured; valid threshold behavior and risk-reducing SELL stay unchanged.
"""
from datetime import datetime, timezone
import json
from types import SimpleNamespace
import pytest

from stock_swing.cli.paper_demo import _filter_buys_by_risk_budget
from stock_swing.core.runtime import RuntimeMode
from stock_swing.decision_engine.decision_engine import DecisionRecord, ProposedOrder
from stock_swing.execution.paper_executor import PaperExecutor
from stock_swing.risk.risk_budget import compute_open_risk
from stock_swing.reporting.console_summary import ConsoleSummary
from stock_swing.reporting.console_renderer import ConsoleRenderer


def state(root, value):
    path = root / 'data/tracking/pnl_state.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def trade(**changes):
    return dict(status='open', symbol='AAPL', qty=10, entry_price=100, **changes)


def decisions():
    return [SimpleNamespace(action='buy', symbol='NVDA'),
            SimpleNamespace(action='sell', symbol='AAPL')]


@pytest.mark.parametrize('value', [None, [], {}, {'trades': None}, {'trades': {}},
    {'trades': [dict(status=[])]}, {'trades': [None]}, {'trades': [{}]}, {'trades': [dict(status='unknown')]}])
def test_ac_malformed_state_is_unknown_and_blocks_only_buys(tmp_path, value, monkeypatch):
    monkeypatch.delenv('PAPER_DEMO_SKIP_RISK_BUDGET', raising=False)
    state(tmp_path, value)
    original = decisions()
    allowed, blocked, risk = _filter_buys_by_risk_budget(original, tmp_path, 100000)
    assert allowed == [original[1]], 'unknown risk must preserve SELL, not BUY'
    assert blocked == ['NVDA'], 'all new BUYs must be held'
    assert risk['pct_of_equity'] is None, 'unknown is not measured zero'
    assert risk['is_blocked'] is True and risk['error'], 'reason must be explicit'


@pytest.mark.parametrize('scenario', ['missing', 'broken', 'unreadable'])
def test_ac_file_failures_block_buys(tmp_path, scenario, monkeypatch):
    monkeypatch.delenv('PAPER_DEMO_SKIP_RISK_BUDGET', raising=False)
    path = tmp_path / 'data/tracking/pnl_state.json'
    path.parent.mkdir(parents=True)
    if scenario == 'broken': path.write_text('{')
    if scenario == 'unreadable': path.mkdir()
    allowed, blocked, risk = _filter_buys_by_risk_budget(decisions(), tmp_path, 100000)
    assert [d.action for d in allowed] == ['sell'], 'SELL must survive file failures'
    assert blocked == ['NVDA'] and risk['pct_of_equity'] is None, 'BUY must not bypass unknown'


@pytest.mark.parametrize('field,value', [
    ('qty', None), ('qty', 'oops'), ('qty', -1), ('qty', 0), ('qty', float('nan')),
    ('qty', float('inf')), ('qty', True), ('entry_price', 0), ('entry_price', 'bad'),
    ('entry_price', float('inf')), ('entry_price', float('nan')),
    ('entry_signal_strength', 'bad'), ('entry_signal_strength', float('nan')),
    ('entry_signal_strength', 1.1), ('symbol', ''),
])
def test_ac_invalid_open_lot_cannot_reduce_risk_to_zero(tmp_path, field, value):
    row = trade(); row[field] = value
    state(tmp_path, {'trades': [row]})
    risk = compute_open_risk(tmp_path, 100000)
    assert risk.get('error') and risk['is_blocked'], 'invalid open lot must fail closed'
    assert risk['total_open_risk'] is None, 'partial sum cannot be reported as complete risk'


@pytest.mark.parametrize('equity', [0, -1, None, 'bad', True, float('nan'), float('inf')])
def test_ac_invalid_equity_is_unknown(tmp_path, equity):
    state(tmp_path, {'trades': []})
    result = compute_open_risk(tmp_path, equity)
    assert result['is_blocked'] and result['pct_of_equity'] is None, 'bad equity is not zero risk'


def test_ac_confirmed_empty_recovery_and_threshold_override(tmp_path, monkeypatch):
    monkeypatch.setenv('PAPER_DEMO_SKIP_RISK_BUDGET', 'true')
    assert _filter_buys_by_risk_budget(decisions(), tmp_path, 100000)[1] == ['NVDA'], 'override must not bypass unknown'
    state(tmp_path, {'trades': []})
    assert not compute_open_risk(tmp_path, 100000)['is_blocked'], 'confirmed flat recovers normally'
    row=trade(); row['qty']=1300; state(tmp_path, {'trades':[row]})
    assert not _filter_buys_by_risk_budget(decisions(),tmp_path,100000)[1], 'existing explicit override for measured risk stays supported'
    monkeypatch.delenv('PAPER_DEMO_SKIP_RISK_BUDGET')
    assert _filter_buys_by_risk_budget(decisions(),tmp_path,100000)[1] == ['NVDA'], 'normal threshold remains 6%'


class Broker:
    def __init__(self, positions, equity=100000):
        self.positions, self.equity, self.sent = positions, equity, []
    def fetch_account(self): return SimpleNamespace(payload={'equity':self.equity})
    def fetch_positions(self): return SimpleNamespace(payload=self.positions)
    def fetch_bars(self, *args, **kwargs): return SimpleNamespace(payload={'bars':[{'c':100}]})
    def fetch_quote(self, *args, **kwargs): return SimpleNamespace(payload={'quote':{'bp':99,'ap':101}})
    def submit_order(self, **kwargs):
        self.sent.append(kwargs); return {'id':'fixture-order','status':'accepted'}


def decision(side='buy'):
    return DecisionRecord(decision_id='fixture-'+side,schema_version='v1',generated_at=datetime.now(timezone.utc),
        mode='paper',strategy_id='breakout_momentum_v1',strategy_version_id='fixture',symbol='AAPL',
        action=side,confidence=.8,signal_strength=.8,risk_state='pass',deny_reasons=[],
        requires_operator_approval=False,time_horizon='5d',evidence={},
        proposed_order=ProposedOrder(symbol='AAPL',side=side,order_type='market',qty=2,time_in_force='day'))


@pytest.mark.parametrize('positions', [None, {}, {'symbol':'AAPL'}, [None],
    [{'symbol':'MSFT','qty':'bad','current_price':100}],
    [{'symbol':'MSFT','qty':10}], [{'symbol':'MSFT','qty':10,'current_price':0}],
    [{'symbol':'MSFT','qty':10,'current_price':float('nan')}],
    [{'symbol':'MSFT','qty':float('inf'),'current_price':100}],
    [{'symbol':'','qty':10,'current_price':100}]])
def test_ac_actual_executor_rejects_unknown_exposure_without_submit(positions):
    broker=Broker(positions); executor=PaperExecutor(RuntimeMode.PAPER,broker)
    qty, details=executor._calculate_position_size(decision())
    assert qty == 0 and details['skip_reason']=='risk_inputs_unavailable', 'malformed holdings must not size as flat'
    assert details['current_total_exposure'] is None, 'unknown exposure stays unknown'
    with pytest.raises(ValueError): executor.submit(decision())
    assert broker.sent == [], 'no order may cross the broker boundary'


def test_ac_executor_verified_sell_does_not_require_risk_sizing():
    broker=Broker(None); executor=PaperExecutor(RuntimeMode.PAPER,broker)
    submission=executor.submit(decision('sell'),current_qty=10)
    assert submission.qty == 10 and submission.side == 'sell', 'existing SELL quantity checks must be retained'
    assert len(broker.sent)==1, 'fixture SELL remains permitted'


def test_ac_unknown_survives_summary_and_renderer(tmp_path):
    risk=compute_open_risk(tmp_path,100000)
    summary=ConsoleSummary.build(run_id='fixture',equity=100000,open_position_count=0,
        risk_budget_pct=risk['pct_of_equity'],risk_budget_status=risk['status'])
    payload=summary.to_dict()
    assert payload['risk']['risk_budget_pct'] is None, 'unknown must remain null in JSON'
    assert payload['risk']['risk_budget_status']=='unavailable', 'status must be consumable'
    assert summary.run_status == 'DEGRADED', 'unknown risk must not be healthy OK'
    rendered=ConsoleRenderer().render(summary)
    assert 'UNAVAILABLE' in rendered, 'operator must not see a measured zero'
