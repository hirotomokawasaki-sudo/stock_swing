"""Acceptance FIX-CONSOLE-CONSISTENCY-20261029, base8909e79 + deployed10/28.

Actual acquisition/service/JSON/JS; substitute external broker only.
"""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from console.services.dashboard_service import DashboardService
from console.adapters.data_adapter import DataAdapter
from tests.unit.test_console_evidence_20261028 import js

STAMP = datetime.now(timezone.utc).isoformat()


def svc(root, positions=None, failure=False):
    class Broker:
        calls = 0
        def fetch_positions(self):
            self.calls += 1
            if failure:
                raise RuntimeError('PRIVATE_BROKER_ERROR')
            return SimpleNamespace(payload=positions)
        def fetch_account(self):
            return SimpleNamespace(payload={'cash':'0','equity':'1000','portfolio_value':'1000'})
    s=object.__new__(DashboardService)
    s.project_root=root; s._broker=Broker();s._tracker=None;s._price_overrides={}
    for key in ['positions','orders','account']:
        setattr(s,'_broker_'+key+'_cache',None);setattr(s,'_broker_'+key+'_cache_ts',0)
    s._BROKER_CACHE_TTL=120;s._tracking_state_meta_cache=None;s._current_account_cutoff_cache=None
    return s


def write(root,name,data):
    f=root/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(json.dumps(data));return f


def test_regression_verified_empty_is_not_missing(tmp_path):
    result=svc(tmp_path,[]).get_positions()
    assert result['available'] is True and result['source']=='broker', 'Broker-confirmed flat is not unavailable/tracker fallback'


def test_regression_positions_missing_not_zero():
    html=js('renderPositions',{'data':{'positions':{'available':False,'positions':[],'summary':{}}}})
    assert 'value success">0' not in html and 'ポジションの有無は未確認' in html, 'Missing positions must not be zero low risk'


def test_regression_missing_reconciliation_not_green_zero():
    html=js('renderReconciliationSummary',{'args':[{}]})
    assert 'value success">0' not in html and '現在の未解決不一致' in html, 'Missing reconciliation is not a current clean census'


def test_regression_unknown_freshness_not_green():
    html=js('renderPipelineFunnel',{'data':{'pipeline':{},'data_status':{}}})
    assert 'funnel-reason-count success">— (unknown)' not in html, 'Unknown freshness must not use success color'


def test_regression_missing_metrics_not_low_risk_zero():
    html=js('renderAnalysis',{'data':{}})
    assert '🛡️' not in html and 'N/A' in html, 'Absent metric availability must not imply a zero low-risk beta'


@pytest.mark.parametrize('raw',[None,{},[None],[{}],[{'symbol':'A','qty':False}],[{'symbol':'A','qty':'NaN'}]])
def test_ac_positions_invalid_shape_is_unknown(tmp_path,raw):
    s=svc(tmp_path,raw);result=s.get_positions()
    assert result['available'] is False and result['evidence']['status']!='ok', 'Malformed acquisition cannot certify flat'
    assert 'PRIVATE' not in json.dumps(result), 'Do not leak broker errors'


def test_ac_positions_failure_and_empty_different_cache_provenance(tmp_path):
    good=svc(tmp_path,[]);empty=good.get_positions();stamp=empty['evidence']['as_of'];good.get_positions()
    failed=svc(tmp_path,[],failure=True).get_positions()
    assert empty['evidence']['status']=='ok' and empty['summary']['gross_exposure']==0, 'Confirmed flat has actual zero'
    assert good._broker.calls==1 and good._broker_positions_evidence['as_of']==stamp, 'Cache read cannot refresh acquisition time'
    assert failed['evidence']['status']!='ok' and failed['summary']=={}, 'Failure is not flat'
    html=js('renderPositions',{'data':{'positions':json.loads(json.dumps(empty))}})
    assert '取得範囲内に保有なし' in html, 'Real acquired flat reaches actual renderer'


@pytest.mark.parametrize('bad',[None,'',True,'NaN','Infinity'])
def test_ac_incomplete_price_or_pnl_not_aggregated_as_zero(tmp_path,bad):
    result=svc(tmp_path,[{'symbol':'A','qty':'3.7','avg_entry_price':'10','current_price':bad}]).get_positions()
    assert result['positions'][0]['qty']==3.7, 'Display must preserve fractional broker quantity'
    assert result['summary']['gross_exposure'] is None and result['summary']['unrealized_pnl'] is None, 'Missing price is not zero exposure/PnL'
    json.dumps(result,allow_nan=False)


def test_ac_actual_position_service_json_renderer(tmp_path):
    result=svc(tmp_path,[{'symbol':'A','qty':'3.7','avg_entry_price':'10','current_price':'12'}]).get_positions()
    assert result['summary']['gross_exposure']==pytest.approx(44.4) and result['summary']['unrealized_pnl']==pytest.approx(7.4), 'Independent broker arithmetic'
    html=js('renderPositions',{'data':{'positions':json.loads(json.dumps(result))}})
    assert '3.7' in html and '$44.40' in html and '口座API取得' in html, 'Provenance and numbers cross JSON to actual JS'


@pytest.mark.parametrize('state',[None,'corrupt',{'trades':[]},{'trades':[],'last_updated':'bad'}])
def test_ac_tracker_missing_corrupt_clock_not_broker_flat(tmp_path,state):
    f=tmp_path/'data/tracking/pnl_state.json'
    if state is not None:
        f.parent.mkdir(parents=True,exist_ok=True);f.write_text('{' if state=='corrupt' else json.dumps(state))
    before=f.read_bytes() if f.exists() else None
    result=svc(tmp_path,[],failure=True).get_positions()
    assert result['evidence']['status']!='ok', 'Tracker fallback cannot certify broker flat'
    assert (f.read_bytes() if f.exists() else None)==before, 'Read-only fallback never creates/repairs ledger'
    html=js('renderPositions',{'data':{'positions':result}})
    assert '取得範囲内に保有なし' not in html, 'Tracker empty is not current acquired empty'


def test_ac_tracker_substitute_preserves_record_time_and_missing_quote(tmp_path):
    write(tmp_path,'data/tracking/pnl_state.json',{'last_updated':STAMP,'trades':[{'status':'open','symbol':'A','qty':2,'entry_price':10}]})
    result=svc(tmp_path,[],failure=True).get_positions(trading={'current_prices':{}})
    assert result['source']=='tracker' and result['evidence']['status']=='substitute', 'Saved tracker is explicit substitute'
    assert result['evidence']['as_of']==STAMP and result['summary']['unrealized_pnl'] is None, 'Saved time and unknown quote survive'
    html=js('renderPositions',{'data':{'positions':result}})
    assert '台帳の代用値' in html and '口座の保有なしを証明しません' in html, 'Fallback meaning remains visible'


@pytest.mark.parametrize('freshness',[{}, {'decisions':{'status':'unknown'}},{'decisions':{'status':'fresh','age_hours':None}},{'decisions':{'status':'fresh','age_hours':-1}}])
def test_ac_unknown_freshness_not_integrity_ok(tmp_path,freshness):
    r=svc(tmp_path,[])._build_integrity({'raw':1,'normalized':1,'features':1,'signals':1,'decisions':1},freshness)
    check=next(c for c in r['checks'] if c['name']=='decision_freshness')
    assert check['status']!='ok', 'Absent/future/invalid freshness cannot count as normal'


def test_ac_data_adapter_original_mtime_not_page_time(tmp_path):
    import os
    f=write(tmp_path,'data/normalized/a.json',{});stamp=1700000000;os.utime(f,(stamp,stamp))
    r=DataAdapter(tmp_path).get_freshness()['normalized']
    assert datetime.fromisoformat(r['as_of']).timestamp()==stamp and r['time_basis']=='file_mtime', 'Source mtime is not acquisition or market event time'
    html=js('renderPipelineFunnel',{'data':{'pipeline':{},'data_status':{'freshness':{'normalized':r}}}})
    assert 'ファイル更新' in html, 'File age is not market data timeliness'


@pytest.mark.parametrize('state',['missing','unknown','empty','error','fresh'])
def test_ac_freshness_renderer_requires_finite_nonnegative_age(state):
    html=js('renderPipelineFunnel',{'data':{'pipeline':{},'data_status':{'freshness':{'normalized':{'status':state,'age_hours':None}}}}})
    assert 'funnel-reason-count success">—' not in html, 'Unknown clocks never get success green'


def test_ac_reconciliation_missing_and_broker_failure_not_zero(tmp_path):
    s=svc(tmp_path,[]);s._broker=None;r=s.get_reconciliation_status()
    assert r['current_mismatches'] is None and r['current_orders']['open'] is None, 'No current qualified census from missing logs/broker'
    html=js('renderReconciliationSummary',{'args':[json.loads(json.dumps(r))]})
    assert '現在の未解決不一致' in html and '要確認' in html, 'Unknown current mismatch remains actionable'


def test_ac_reconciliation_states_do_not_equal_mismatch(tmp_path):
    # 10/30: present-order acquisition is separate from all/500 history.
    # Substitute the external broker, not the new acquisition/validation code.
    class Broker:
        def fetch_orders(self, *, status, limit):
            assert status in ('all','open') and limit == 500
            return [{'id':identity,'status':state,'symbol':'TEST','side':'buy',
                     'qty':'3.7','filled_qty':'1.2','type':'limit','limit_price':'10'}
                    for identity,state in [('a','accepted'),('b','pending_cancel'),('c','partially_filled')]]
    s=svc(tmp_path,[]);s._broker=Broker()
    r=s.get_reconciliation_status()
    assert r['current_orders']['open']==1 and r['current_orders']['pending_cancel']==1 and r['current_orders']['partial']==1, 'Disjoint operational states, not mismatch count'
    assert r['current_mismatches'] is None, 'Order status does not certify position/ledger reconciliation'
    html=js('renderReconciliationSummary',{'args':[r]})
    assert '取消待ち' in html and '過去ログ' in html and '範囲限定' in html, 'Scope/history/current preserved'


@pytest.mark.parametrize('metric,key',[('alpha','alpha'),('beta','beta'),('sharpe','sharpe_ratio')])
@pytest.mark.parametrize('value',[None,True,'', 'NaN'])
def test_ac_bad_analysis_metric_not_available(metric,key,value):
    html=js('renderAnalysis',{'data':{'performance':{metric:{'available':True,key:value}}}})
    assert 'value huge success">0' not in html and '🛡️' not in html, 'Malformed metrics cannot certify low risk'


def test_ac_true_zero_analysis_retained_and_qualified():
    d={'performance':{'snapshot_count':30,'alpha':{'available':True,'alpha':0,'period':{'start':'2026-01-01','end':'2026-02-01','days':30}},'beta':{'available':True,'beta':0,'data_points':29},'sharpe':{'available':True,'sharpe_ratio':0,'data_points':29}}}
    html=js('renderAnalysis',{'data':d})
    assert '0.00' in html and '参考集計' in html and '標本' in html, 'Measured zero not deleted; qualification/samples visible'


def test_ac_no_snapshot_producer_json_renderer(tmp_path):
    r=svc(tmp_path,[])._get_performance_attribution({'daily_snapshots':[]})
    html=js('renderAnalysis',{'data':{'performance':json.loads(json.dumps(r))}})
    assert r['available'] is False and '🛡️' not in html and 'N/A' in html, 'Real no-data producer reaches renderer'


def test_ac_gross_net_short_arithmetic_and_incomplete_component(tmp_path):
    s=svc(tmp_path,[])
    r=s._summarize_positions([{'market_value':100,'qty':1,'unrealized_pnl':5},{'market_value':-40,'qty':-1,'unrealized_pnl':-2}])
    assert r['gross_exposure']==140 and r['net_exposure']==60 and r['unrealized_pnl']==3, 'Gross absolute/net signed, no short offset mistaken for zero gross'
    r=s._summarize_positions([{'market_value':100,'qty':1,'unrealized_pnl':5},{'market_value':None,'qty':1,'unrealized_pnl':None}])
    assert r['gross_exposure'] is None and r['largest_position_weight'] is None, 'Partial coverage cannot certify aggregate or concentration'


def test_ac_broker_numeric_fields_are_json_finite(tmp_path):
    s=svc(tmp_path,[{'symbol':'A','qty':'3.7','avg_entry_price':'10','current_price':'12','lastday_price':'NaN'}])
    s._price_overrides={'A':{'fresh_price':'NaN'}}
    r=s.get_positions();json.dumps(r,allow_nan=False)
    assert r['positions'][0]['current_price'] is None and r['positions'][0]['lastday_price'] is None, 'Bad overrides/optional prices remain unknown'


def test_ac_stale_positions_and_order_cache_do_not_certify_current():
    position={'available':True,'evidence':{'status':'ok','as_of':'2020-01-01T00:00:00Z'},'positions':[],'summary':{'gross_exposure':0,'top5_concentration':0}}
    html=js('renderPositions',{'data':{'positions':position}})
    assert '取得範囲内に保有なし' not in html and 'value success">0' not in html, 'Stale acquired flat is not current absence'
    html=js('renderReconciliationSummary',{'args':[{'pending_orders_evidence':{'status':'ok','as_of':'2020-01-01T00:00:00Z'},'current_orders':{'open':0,'pending_cancel':0,'partial':0}}]})
    assert '未確認 / 未確認 / 未確認' in html, 'Old group counts cannot certify currently empty'


def test_ac_positions_injection_and_analysis_numeric_strings():
    html=js('renderPositions',{'data':{'positions':{'source':'<img onerror=evil()>','evidence':{'reason':'<script>evil()</script>'}}}})
    assert '<script>evil' not in html and '<img onerror' not in html, 'Allowlisted provenance strings escaped'
    html=js('renderStrategyAttributionTable',{'args':[[{'strategy_version_id':'a','beta':{'available':True,'beta':'0.1'},'sharpe':{'available':True,'sharpe_ratio':'0'}}]]})
    assert '0.10' in html and '0.00' in html, 'Finite numeric metric strings render, not crash'


def test_ac_analysis_unknown_auxiliary_values_not_green():
    html=js('renderAnalysis',{'data':{'performance':{'alpha':{'available':True,'alpha':0},'sharpe':{'available':True,'sharpe_ratio':0}}}})
    assert 'class="value success">未取得' not in html and 'class="value success">—' not in html, 'Missing auxiliary returns are not green normal values'
    assert 'snapshots=0' not in html, 'Absent sample count is not a measured zero'
