"""Acceptance RECORDING-CLOSURE-20261030; base 8909e79 + dirty live preimage.

Regression: sealed minimum changed the PF source definition and old summary
discarded constructed-setting observations. Only fixtures and real file I/O.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import pytest

NOW=datetime(2026,10,30,10,30,tzinfo=timezone.utc)


def test_ac_setting_observations_propagate_without_changing_run_status():
    from stock_swing.reporting.console_summary import ConsoleSummary
    s=ConsoleSummary.build(run_id='fixture',equity=100,open_position_count=0,unrealized_pnl=0)
    prior=s.to_dict();s.effective_config=[dict(kind='instance:EntryFilterConfig',status='not_reached',recorded=True)]
    wire=s.to_dict()
    assert wire['effective_config']==s.effective_config,'Opt-in receipt must reach serialized summary'
    wire.pop('effective_config')
    assert wire==prior,'Observations cannot change trading/control/performance fields'


def test_ac_explicit_v2_preserves_protocol_and_v1_namespace(monkeypatch):
    from stock_swing.risk import entry_restriction_review as review
    monkeypatch.delenv('ENTRY_RESTRICTION_REVIEW_VERSION',raising=False)
    protocol,store=review._study()
    assert protocol==review.PROTOCOL and store==review.STORE,'No implicit transition'
    monkeypatch.setenv('ENTRY_RESTRICTION_REVIEW_VERSION','v2')
    protocol,store=review._study()
    assert store!=review.STORE and protocol['automatic_release'] is False,'Fixed separate namespace; never release'
    assert protocol['horizon_sessions']==review.PROTOCOL['horizon_sessions'],'Economic specification is preserved'
    monkeypatch.setenv('ENTRY_RESTRICTION_REVIEW_VERSION','unknown')
    with pytest.raises(ValueError):review._study()


def evidence(age=0,status='ok'):
    return dict(status=status,as_of=(NOW-timedelta(seconds=age)).isoformat())


def portfolio_fixture(root):
    p=root/'config/reference/symbol_registry.yaml';p.parent.mkdir(parents=True)
    p.write_text('symbols:\n  AAPL: {asset_class: stock, sector: hardware}\n  MSFT: {asset_class: stock, sector: software}\n')
    return dict(root=root, positions=[dict(symbol='AAPL',qty='2.5',market_value='250',side='long')],
        positions_evidence=evidence(),pending=dict(status='observed_scope_only',as_of=NOW.isoformat(),complete_open_query=True,observed_active_orders=0),
        account={'equity':'1000','currency':'USD'},account_evidence=evidence(),now=NOW)


@pytest.mark.parametrize('age,status,expected',[(0,'ok',500),(120,'ok',500),(121,'ok',None),(0,'error',None),(-1,'ok',None)])
def test_ac_reported_buying_power_is_not_debited_again(age,status,expected):
    from console.services.operational_inputs_service import funds_projection
    d=funds_projection(dict(cash='1000',buying_power='500',non_marginable_buying_power='450'),evidence(age,status),now=NOW)
    assert d['buying_power']==expected,'Preserve original acquisition freshness and reported capacity'
    assert d['reserved_cash'] is None and d['free_settled_cash'] is None,'Capacity is not reserved/settled cash'


@pytest.mark.parametrize('value',[None,True,'',float('nan'),float('inf'),'-1'])
def test_ac_invalid_capacity_is_unknown_not_zero(value):
    from console.services.operational_inputs_service import funds_projection
    d=funds_projection({'non_marginable_buying_power':value},evidence(),now=NOW)
    assert d['non_marginable_buying_power'] is None,'Malformed/missing capacity cannot be invented'


def test_ac_current_and_projected_exposure_use_independent_arithmetic(tmp_path):
    from console.services.operational_inputs_service import portfolio_projection
    kw=portfolio_fixture(tmp_path)
    current=portfolio_projection(**kw)
    assert current['current_largest_position_pct']==pytest.approx(250/1000)
    assert current['projected_concentration'] is None and current['projected_status']=='no_proposal'
    projected=portfolio_projection(**kw,proposal=dict(symbol='MSFT',side='buy',type='limit',qty='3.5',limit_price='100'))
    assert projected['projected_concentration']==pytest.approx(350/1000)
    assert projected['projected_gross_exposure_pct']==pytest.approx((250+350)/1000)
    assert projected['policy_approved'] is False and projected['reserved_cash'] is None


@pytest.mark.parametrize('fault',['positions_missing','stale','future','duplicate','short','nan','unknown_symbol','currency','pending','pending_stale','pending_bool','partial_orders','bad_proposal','registry_missing','registry_corrupt'])
def test_ac_uncertain_portfolio_withholds_scenario(tmp_path,fault):
    from console.services.operational_inputs_service import portfolio_projection
    kw=portfolio_fixture(tmp_path);proposal=dict(symbol='MSFT',side='buy',type='limit',qty='3',limit_price='100')
    if fault=='positions_missing':kw['positions']=None
    elif fault=='stale':kw['positions_evidence']=evidence(121)
    elif fault=='future':kw['positions_evidence']=evidence(-1)
    elif fault=='duplicate':kw['positions']*=2
    elif fault=='short':kw['positions'][0]['side']='short'
    elif fault=='nan':kw['positions'][0]['market_value']='nan'
    elif fault=='unknown_symbol':kw['positions'][0]['symbol']='UNKNOWN'
    elif fault=='currency':kw['account']['currency']='EUR'
    elif fault=='pending':kw['pending']['observed_active_orders']=1
    elif fault=='pending_stale':kw['pending']['as_of']=evidence(121)['as_of']
    elif fault=='pending_bool':kw['pending']['observed_active_orders']=False
    elif fault=='partial_orders':kw['pending']['complete_open_query']=False
    elif fault=='bad_proposal':proposal['type']='market'
    elif fault=='registry_missing':(tmp_path/'config/reference/symbol_registry.yaml').unlink()
    elif fault=='registry_corrupt':(tmp_path/'config/reference/symbol_registry.yaml').write_text('[')
    d=portfolio_projection(**kw,proposal=proposal)
    assert d['projected_concentration'] is None and d['policy_approved'] is False,'Invalid inputs cannot produce an approved or numeric scenario'


def test_ac_verified_empty_positions_not_unknown_or_full_coverage(tmp_path):
    from console.services.operational_inputs_service import portfolio_projection
    kw=portfolio_fixture(tmp_path);kw['positions']=[]
    d=portfolio_projection(**kw)
    assert d['current_largest_position_pct']==0 and d['total_positions']==0
    assert d['classification_coverage'] is None and d['classification_state']=='empty_population'


def test_ac_v2_console_keeps_legacy_history_separate(tmp_path):
    from console.services.operational_evidence_service import _run_and_research, SUMMARY
    path=tmp_path/SUMMARY;path.parent.mkdir(parents=True)
    path.write_text(json.dumps(dict(run=dict(mode='paper',dry_run=False,invocation_source='paper_demo_scheduled',run_id='fixture',timestamp=NOW.isoformat()),
        decision_funnel=dict(entry_restriction_review=dict(status='observing',eligible_to_trade=False,automatic_release=False,
            protocol='pf-review-v2-20261029',observations=0,rows=[],
            legacy=dict(status='retained',role='historical_only',observations=2,completed=0,pending=2))))))
    _,r,_=_run_and_research(tmp_path,NOW)
    assert r['status']=='observing' and r['observations']==0,'New store begins separately'
    assert r['legacy']['observations']==2 and r['eligible_to_trade'] is False,'Old observations are historical, not added'


def test_ac_quality_context_never_rewrites_or_recertifies(tmp_path):
    from console.services.operational_inputs_service import quality_context
    path=tmp_path/'data/tracking/pnl_state.json';path.parent.mkdir(parents=True)
    path.write_text(json.dumps(dict(trades=[{'status':'quarantined'}],quarantined_trades=[{'status':'quarantined'}])))
    before=path.read_bytes();d=quality_context(tmp_path,now=NOW)
    assert path.read_bytes()==before and d['strict_health_waived'] is False
    assert d['inline_quarantined']==1 and d['separate_quarantined']==1,'Separate containers must not be summed'
    assert d['ledger_audit_status']=='not_recertified' and d['quality_stamp_updated'] is False


@pytest.mark.parametrize('body',[None,'{','{"trades":"bad"}','{"trades":[],"x":NaN}'])
def test_ac_missing_corrupt_ledger_never_certified(tmp_path,body):
    from console.services.operational_inputs_service import quality_context
    p=tmp_path/'data/tracking/pnl_state.json';p.parent.mkdir(parents=True)
    if body is not None:p.write_text(body)
    d=quality_context(tmp_path,now=NOW)
    assert d['ledger_audit_status']=='unknown' and d['inline_quarantined'] is None
    assert d['quality_stamp_updated'] is False
