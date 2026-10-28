"""K04/CMP-C05 isolated acceptance; no new policy values or economic trials."""
from pathlib import Path
from types import SimpleNamespace as NS
import json
import pytest
import yaml
from stock_swing.risk.effective_config import read_effective_config,EXIT_DEFAULTS
from stock_swing.risk.allocation_config import read_allocation_config,read_symbol_registry
from stock_swing.risk.portfolio_allocator import PortfolioAllocator
from stock_swing.risk.order_preflight import OrderPreflight
from stock_swing.reporting.console_summary import ConsoleSummary

@pytest.mark.parametrize('body',['null','[]','[','stop_loss_pct: .nan','min_hold_days_enabled: "false"','max_hold_days: -1','staged_trailing_levels: [null]','volatility_multiplier_min: 3\nvolatility_multiplier_max: 1'])
def test_ac_invalid_exit_is_receipted_legacy_fallback(tmp_path,body):
    p=tmp_path/'exit.yaml';p.write_text(body)
    values,receipt=read_effective_config(p,'exit')
    assert receipt['status']=='unavailable' and receipt['issues'] and values==EXIT_DEFAULTS,receipt
    assert 'draft' in receipt['fallback'],receipt


def test_ac_missing_and_normal_do_not_activate_ignored_flags(tmp_path):
    p=tmp_path/'exit.yaml';values,receipt=read_effective_config(p,'exit')
    assert receipt['status']=='unavailable' and values['stop_loss_pct']==-.07,receipt
    p.write_text('enabled: false\nmax_hold_days: 20\nstop_loss_pct: -0.07\n')
    values,receipt=read_effective_config(p,'exit')
    assert receipt['status']=='configured' and receipt['unused_keys']==['enabled'] and 'enabled' not in values,receipt

@pytest.mark.parametrize('body',['null','[]','[','lookback_bars: 0','smoothing_window: true','signal_criteria: null','signal_criteria: {momentum_threshold: .inf}'])
def test_ac_intraday_shape_and_finite(tmp_path,body):
    p=tmp_path/'intraday.yaml';p.write_text(body)
    values,receipt=read_effective_config(p,'intraday')
    assert receipt['status']=='unavailable' and values['lookback_bars']==25,receipt

@pytest.mark.parametrize('body',['null','[]','[','portfolio: []','portfolio: {allocation: null}','portfolio: {use_projected_allocation: "false"}','stock_new_buy_multiplier: .nan','sector_cap_pct: 2','portfolio: {allocation_band: {stocks_min: 0.9, stocks_max: 0.8}}'])
def test_ac_allocation_invalid_holds_direct_guard(tmp_path,body):
    p=tmp_path/'allocation.yaml';p.write_text(body);cfg=read_allocation_config(p)
    assert cfg.configuration_issue,cfg
    allocator=PortfolioAllocator(config=cfg,registry={'MSFT':{'asset_class':'stock'}})
    assert not allocator.check_projected_band('MSFT',100,{},100000).allowed,'direct band guard cannot silently use defaults'

@pytest.mark.parametrize('body',['null','[]','[','symbols: []','symbols: {NVDA: null}','symbols: {NVDA: {asset_class: [stock]}}','symbols: {NVDA: {asset_class: stock, is_semiconductor_related: "false"}}'])
def test_ac_registry_corrupt_is_unknown_not_crash(tmp_path,body):
    p=tmp_path/'registry.yaml';p.write_text(body)
    assert read_symbol_registry(p)=={},'invalid row cannot supply default classification'

@pytest.mark.parametrize('source',['candidate','holding','pending'])
def test_ac_semiconductor_gap_not_zero_and_unrelated_unchanged(source):
    registry={'AVGO':{'asset_class':'stock','is_semiconductor_related':True},'NVDA':{'asset_class':'stock','is_semiconductor_related':True},'MSFT':{'asset_class':'stock','is_semiconductor_related':False}}
    positions={'AVGO':{'qty':1,'market_value':100}} if source=='holding' else {}
    orders=[dict(id='pending',symbol='AVGO',qty='1',filled_qty='0',side='buy',type='market',status='new')] if source=='pending' else []
    book=OrderPreflight(positions,100000,orders,complete=True,price_lookup=lambda s:100,registry=registry)
    result=book.reserve('d','AVGO' if source=='candidate' else 'NVDA',1,100,.08)
    assert result['reason']=='semiconductor_cluster_coverage_gap' and result['coverage_gaps']==['AVGO'],result
    assert book.reserve('other','MSFT',1,100,.08)['allowed'],'verified unrelated group unaffected'


def test_ac_unknown_and_held_propagate_to_json_and_alert_renderer():
    from stock_swing.reporting.console_renderer import ConsoleRenderer
    summary=ConsoleSummary.build(run_id='fixture',equity=100000,open_position_count=0,realized_pnl=0,unrealized_pnl=0,
        submissions=[NS(status='unknown'),NS(status='held')],risk_budget_status='ok',risk_budget_pct=0)
    payload=summary.to_dict()
    assert {k:payload['decision_funnel'][k] for k in ('submitted','rejected','unknown','held')}==dict(submitted=0,rejected=0,unknown=1,held=1),payload['decision_funnel']
    assert summary.run_status=='DEGRADED' and any(a.code=='submission_unresolved_or_held' for a in summary.alerts),summary
    rendered=ConsoleRenderer().render(summary)
    assert 'unknown=1' in rendered and 'not rejected' in rendered,rendered


def test_ac_effective_receipt_retains_per_lot_flag_after_constructor_selection(tmp_path):
    p=tmp_path/'exit.yaml';p.write_text('per_lot_time_based_exit_enabled: false\n')
    values,receipt=read_effective_config(p,'exit')
    values.pop('per_lot_time_based_exit_enabled')
    assert receipt['effective']['per_lot_time_based_exit_enabled'] is False,'effective receipt must survive caller argument extraction'
