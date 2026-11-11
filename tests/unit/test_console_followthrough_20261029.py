"""Acceptance: FOLLOWTHROUGH-20261029, base8909e79 plus Console10/29.
Real service/JSON/JS; external broker only substituted; never submits orders.
"""
import hashlib,json
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from pathlib import Path
import pytest
from console.services.followthrough_service import (get_followthrough,position_comparison,pending_risk,
    scheduler_evidence,research_inputs,acceptance_evidence,REVIEW,SUMMARY,READINESS,VALUES)
from console.services.dashboard_service import DashboardService
from tests.unit.test_console_evidence_20261028 import js
NOW=datetime(2026,10,29,3,tzinfo=timezone.utc)
EV={'status':'ok','as_of':NOW.isoformat(),'complete':True}

def write(root,rel,data):
 p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data));return p

def ledger(root,rows):return write(root,'data/tracking/pnl_state.json',{'trades':rows,'last_updated':'2026-01-01T00:00:00Z'})
def order(**kw):return dict(id='o1',symbol='A',side='buy',type='limit',status='pending_cancel',qty='3.7',filled_qty='1.2',limit_price='10',**kw)

@pytest.mark.parametrize('rows,pos,expected',[([],[],0),([{'status':'open','symbol':'A','qty':'1.2'},{'status':'open','symbol':'A','qty':'2.5'}],[{'symbol':'A','qty':'3.7'}],0),([{'status':'open','symbol':'A','qty':3}],[{'symbol':'A','qty':'3.7'}],1),([],[{'symbol':'A','qty':'-3.7'}],1)])
def test_ac_quantity_comparison(rows,pos,expected,tmp_path):
 p=ledger(tmp_path,rows);before=p.read_bytes();out=position_comparison(tmp_path,pos,EV,NOW)
 assert out['mismatch_count']==expected
 assert out['broker_as_of']==EV['as_of'] and out['tracker_last_updated']=='2026-01-01T00:00:00Z'
 assert p.read_bytes()==before and out['tracker_sha256']==hashlib.sha256(before).hexdigest()
 assert '全口座' in out['scope']

@pytest.mark.parametrize('change',[{'status':'error'},{'complete':False},{'as_of':None},{'as_of':(NOW-timedelta(seconds=121)).isoformat()},{'as_of':(NOW+timedelta(seconds=1)).isoformat()}])
def test_ac_unqualified_positions_not_zero(tmp_path,change):
 ledger(tmp_path,[]);out=position_comparison(tmp_path,[],{**EV,**change},NOW)
 assert out['mismatch_count'] is None

@pytest.mark.parametrize('rows',[None,[None],[{}],[{'status':'open','symbol':'A','qty':True}],[{'status':'open','symbol':'A','qty':float('nan')}],[{'status':'open','symbol':'A','qty':-1}],[{'status':'mystery','symbol':'A','qty':1}]])
def test_ac_invalid_ledger_no_parity(tmp_path,rows):
 ledger(tmp_path,rows);assert position_comparison(tmp_path,[],EV,NOW)['mismatch_count'] is None

def test_ac_quarantine_does_not_disappear(tmp_path):
 ledger(tmp_path,[{'status':'quarantined','symbol':'A','qty':1}]);o=position_comparison(tmp_path,[],EV,NOW)
 assert o['status']=='quarantine_present' and o['mismatch_count'] is None and o['quarantined_rows']==1

@pytest.mark.parametrize('corrupt',[False,True])
def test_ac_missing_corrupt_tracker_read_only(tmp_path,corrupt):
 if corrupt:p=ledger(tmp_path,[]);p.write_text('{PRIVATE')
 o=position_comparison(tmp_path,[],EV,NOW);assert o['mismatch_count'] is None and 'PRIVATE' not in json.dumps(o)
 if not corrupt:assert not (tmp_path/'data').exists()

def test_ac_cancel_partial_pending_value_not_released():
 o=pending_risk([order()],EV,NOW)
 assert o['observed_limit_buy_notional']==25 and o['pending_cancel']==1
 assert o['reserved_cash'] is None and o['projected_concentration'] is None
 assert pending_risk([{**order(),'status':'canceled'}],EV,NOW)['observed_limit_buy_notional']==0

@pytest.mark.parametrize('row',[{**order(),'filled_qty':'4'}, {**order(),'qty':True},{**order(),'status':'mystery'},{**order(),'side':'unknown'},None])
def test_ac_invalid_pending_not_zero(row):
 assert pending_risk([row],EV,NOW)['observed_active_orders'] is None

@pytest.mark.parametrize('evidence',[{}, {'status':'error'}, {**EV,'status':'partial'},{**EV,'as_of':(NOW-timedelta(seconds=121)).isoformat()}])
def test_ac_partial_stale_orders_no_total(evidence):
 assert pending_risk([],evidence,NOW)['observed_limit_buy_notional'] is None

def test_ac_query_cap_duplicate_market_and_empty():
 assert pending_risk([order(),order()],EV,NOW)['observed_active_orders'] is None
 assert pending_risk([order()]*500,EV,NOW)['observed_active_orders'] is None
 m=pending_risk([{**order(),'type':'market','limit_price':None}],EV,NOW)
 assert m['unpriced_buy_orders']==1 and m['reserved_cash'] is None
 e=pending_risk([],EV,NOW);assert e['observed_active_orders']==0 and e['reserved_cash'] is None

def receipt(root,**kw):
 p=write(root,SUMMARY,{'run':{'run_id':'app-run'}})
 review={'reviewed_at':NOW.isoformat(),'summary_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
   'scheduler':{'origin':'gateway.automations.get','job_name':'stock_swing_paper_demo_market_close','job_id':'job','last_status':'ok','last_run_at':NOW.isoformat()}}
 review.update(kw);return write(root,REVIEW,review)

def test_ac_independent_metadata_never_implies_history_config_sell(tmp_path):
 receipt(tmp_path);r=scheduler_evidence(tmp_path,NOW)
 assert r['registered_job_observed'] is True and r['status']=='metadata_observed'
 assert not any(r[k] for k in ['history_run_id_available','application_run_linked','scheduled_verified','effective_config_verified','sell_monitor_verified'])
 write(tmp_path,SUMMARY,{'run':{'run_id':'new-run'}})
 assert scheduler_evidence(tmp_path,NOW)['status']=='changed_summary'

@pytest.mark.parametrize('stamp',[None,'bad','2026-10-29T03:00:00',(NOW+timedelta(seconds=1)).isoformat(),(NOW-timedelta(days=2)).isoformat()])
def test_ac_review_bad_or_stale_clock(tmp_path,stamp):
 receipt(tmp_path,reviewed_at=stamp);assert not scheduler_evidence(tmp_path,NOW)['registered_job_observed']

def test_ac_missing_corrupt_symlink_review_unknown(tmp_path):
 assert scheduler_evidence(tmp_path,NOW)['status']=='unknown'
 p=receipt(tmp_path);p.write_text('{PRIVATE');assert scheduler_evidence(tmp_path,NOW)['status']=='unknown'
 outside=tmp_path.parent/(tmp_path.name+'-external.json');outside.write_text('{}');p.unlink();p.symlink_to(outside)
 assert scheduler_evidence(tmp_path,NOW)['status']=='unknown'

def research(root):
 return write(root,READINESS,{'scope':'historical audit','groups':{
 'deny':{'rows':2,'field_counts':{'snapshot_join':{'no_exact_snapshot':2}}},
 'sell':{'rows':3,'field_counts':{'snapshot_join':{'exact_unique_same_action':1,'no_exact_snapshot':2}}}},
 'frozen_ledger':{'direct_SELL_to_closed_exit_join_available':False}})

def test_ac_historical_input_counts_not_forward_or_profit(tmp_path):
 research(tmp_path);r=research_inputs(tmp_path)
 assert (r['deny_exact_snapshots'],r['deny_decisions'],r['sell_exact_snapshots'],r['sell_decisions'])==(0,2,1,3)
 assert r['status']=='historical_input_audit' and r['exit_direct_link'] is False

@pytest.mark.parametrize('bad',[{}, {'no_exact_snapshot':1},{'exact_unique_same_action':True},{'exact_unique_same_action':-1}])
def test_ac_missing_or_partial_histogram_not_measured_zero(tmp_path,bad):
 p=research(tmp_path);j=json.loads(p.read_text());j['groups']['deny']['field_counts']['snapshot_join']=bad;write(tmp_path,READINESS,j)
 assert research_inputs(tmp_path)['deny_exact_snapshots'] is None

@pytest.mark.parametrize('value',[None,{}, {'capital_B':0}, {'F1_started':True,'T0':'invented'}])
def test_ac_missing_values_no_promotion(tmp_path,value):
 if value is not None:write(tmp_path,VALUES,value)
 r=acceptance_evidence(tmp_path)
 assert r['formal_start_ready'] is False and r['promotion_authorized'] is False


def test_ac_service_json_renderer_and_external_broker_only(tmp_path):
 ledger(tmp_path,[])
 class Broker:
  def fetch_account(self):return {'cash':'100','buying_power':'200'}
  def fetch_positions(self):return []
  def fetch_orders(self,**kw):assert kw=={'status':'all','limit':500};return [order()]
 s=object.__new__(DashboardService);s.project_root=tmp_path;s._broker=Broker()
 for k in ['orders','positions','account']:
  setattr(s,'_broker_'+k+'_cache',None);setattr(s,'_broker_'+k+'_cache_ts',0)
 s._get_broker_positions();s._get_broker_orders()
 e=s.get_operational_evidence();wire=json.loads(json.dumps(e,allow_nan=False))
 assert wire.get('followthrough',{}).get('position_comparison',{}).get('mismatch_count')==0,'Broker→saved quantity comparison must be connected, not only a static label'
 assert wire['followthrough']['pending_risk']['observed_limit_buy_notional']==25
 h=js('renderFollowthroughEvidence',{'data':{'operational_evidence':wire}})
 assert '$25.00' in h and '全口座' in h and '正式比較: 未開始' in h and '未確認' in h


def test_ac_real_renderer_missing_and_injection(tmp_path):
 h=js('renderFollowthroughEvidence',{'data':{}})
 assert '数量差の銘柄数: 未確認' in h and '$0.00' not in h
 data=get_followthrough(tmp_path,now=NOW);data['next_actions']=['<img src=x onerror=alert(1)>']
 h=js('renderFollowthroughEvidence',{'data':{'operational_evidence':{'followthrough':data}}})
 assert '<img' not in h and '&lt;img' in h


def test_ac_cold_cache_does_not_fetch_extra_broker_inputs(tmp_path):
 s=object.__new__(DashboardService);s.project_root=tmp_path
 s._get_broker_account=lambda:{}
 def forbidden():raise AssertionError('No broker calls just to populate a display')
 s._get_broker_positions=forbidden;s._get_broker_orders=forbidden
 e=s.get_operational_evidence()
 assert e['followthrough']['position_comparison']['mismatch_count'] is None
 assert e['followthrough']['pending_risk']['observed_active_orders'] is None

@pytest.mark.parametrize('failure',[None,'log_changed','wrong_id','outside_window','dry_run','bad_duration','outside_path','future_app','duplicate_id'])
def test_ac_exact_retained_log_summary_join_is_scoped(tmp_path,failure):
 p=receipt(tmp_path);r=json.loads(p.read_text());rel='logs/gateway_workflows/stock_swing_paper_demo_market_close_20261029T030000_00000000.log'
 log=tmp_path/rel;log.parent.mkdir(parents=True);log.write_text('  Run ID    : app-run\n')
 run={'run_id':'app-run','mode':'paper','dry_run':False,'invocation_source':'paper_demo_scheduled','timestamp':NOW.isoformat()}
 if failure=='wrong_id':run['run_id']='other'
 if failure=='outside_window':run['timestamp']=(NOW-timedelta(seconds=1)).isoformat()
 if failure=='future_app':run['timestamp']=(NOW+timedelta(seconds=1)).isoformat()
 if failure=='dry_run':run['dry_run']=True
 if failure=='duplicate_id':log.write_text('Run ID : app-run\nRun ID : app-run\n')
 summary=write(tmp_path,SUMMARY,{'run':run});r['summary_sha256']=hashlib.sha256(summary.read_bytes()).hexdigest()
 r['scheduler'].update(wrapper_log_path=rel,wrapper_log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),last_duration_ms=1000)
 if failure=='bad_duration':r['scheduler']['last_duration_ms']=True
 if failure=='outside_path':r['scheduler']['wrapper_log_path']='../outside.log'
 if failure=='log_changed':log.write_text('different')
 write(tmp_path,REVIEW,r);result=scheduler_evidence(tmp_path,NOW)
 assert result['registered_job_observed'] is True
 assert result['application_run_linked'] is (failure is None)
 assert result['scheduled_verified'] is False and result['effective_config_verified'] is False and result['sell_monitor_verified'] is False
