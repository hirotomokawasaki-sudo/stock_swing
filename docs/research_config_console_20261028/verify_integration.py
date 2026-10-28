from pathlib import Path
from types import SimpleNamespace
import importlib.util,json,tempfile,hashlib
import httpx
from stock_swing.sources.broker_client import BrokerClient
from stock_swing.execution.cancellation_guard import cancel_order_safely
from console.services.dashboard_service import DashboardService
from console.services.evidence_service import get_console_evidence
from stock_swing.risk.config_instance_receipts import ConfigInstanceRecorder
from stock_swing.risk.entry_filter import EntryFilterConfig
from stock_swing.risk.losing_position_add_guard import LosingPositionAddGuardConfig
from stock_swing.reporting.console_summary import ConsoleSummary
from stock_swing.reporting.console_renderer import ConsoleRenderer
j=Path(__file__).resolve().parent;root=j/'candidate'
sp=importlib.util.spec_from_file_location('renderer_helpers',root/'tests/unit/test_console_evidence_20261028.py');helper=importlib.util.module_from_spec(sp);sp.loader.exec_module(helper)
results=[];original=httpx.Client
with tempfile.TemporaryDirectory(prefix='console-integrated-',dir=j) as temp:
 work=Path(temp)
 for state in ['pending_cancel','canceled','partially_filled','404']:
  fixture=work/state;(fixture/'config/runtime').mkdir(parents=True);(fixture/'config/runtime/current_mode.yaml').write_text('mode: paper\n');calls=[]
  def order(status='new'):
   return dict(id='fixture-order',symbol='AMD',side='sell',type='market',time_in_force='day',qty='3.7',filled_qty='1.2' if status=='partially_filled' else '0',status=status)
  def boundary(req):
   calls.append(req.method+' '+req.url.path)
   if req.url.path.endswith('/account'):return httpx.Response(200,json=dict(id='fixture-account',status='ACTIVE'))
   if req.method=='DELETE':return httpx.Response(204)
   after=any(c.startswith('DELETE') for c in calls)
   if state=='404' and after:return httpx.Response(404,json={})
   value=order(state if after else 'new')
   return httpx.Response(200,json=[value] if req.url.path.endswith('/orders') else value)
  httpx.Client=lambda **kw:original(transport=httpx.MockTransport(boundary),**kw)
  broker=BrokerClient(api_key='fixture',api_secret='fixture',paper_mode=True)
  first=cancel_order_safely(broker,fixture,order());second=cancel_order_safely(broker,fixture,order())
  assert sum(c.startswith('DELETE') for c in calls)==1,'retry must never duplicate cancel'
  svc=object.__new__(DashboardService);svc.project_root=fixture;svc._broker=broker;svc._broker_orders_cache=None;svc._broker_orders_cache_ts=0;svc._BROKER_CACHE_TTL=60
  rows=svc._fetch_broker_pending_orders([dict(subject='fixture-order',details='sell 3.7 AMD')],[])
  evidence=svc._broker_orders_evidence;serialized=json.loads(json.dumps(dict(pending_orders=rows,pending_orders_evidence=evidence)))
  html=helper.js('renderPendingOrdersTable',{'args':[serialized['pending_orders'],serialized['pending_orders_evidence']]})
  if state=='404':assert first['state']=='unknown' and '取得未確認' in html and '3.7' in html,'unknown remains unknown with audit-only fractional quantity'
  elif state=='canceled':assert first['cancelled'] and '取消確認済' in html,'only terminal readback is confirmed'
  else:assert not first['cancelled'] and '取消確認済' not in html and '3.7' in html,'pending/partial is not cancellation complete'
  results.append(dict(broker_state=state,guard_state=first['state'],service_acquisition=evidence['status'],serialized_to_actual_JS=True,delete_attempts=1))
 httpx.Client=original
 recorder=ConfigInstanceRecorder(work,'fixture-config');recorder.construct(EntryFilterConfig);recorder.construct(LosingPositionAddGuardConfig);recorder.finalize()
 summary=ConsoleSummary(run_id='fixture-config',timestamp='2026-10-28T15:00:00Z',equity=100,open_position_count=0,realized_pnl=0,unrealized_pnl=None,signals_total=0,signals_buy=0,signals_sell=0,signals_deny=0,orders_submitted=0,orders_rejected=0,effective_config=recorder.receipts)
 data=json.loads(json.dumps(summary.to_dict()));text=ConsoleRenderer()._config_instances(data)
 assert len(data['effective_config'])==11 and 'EntryFilterConfig: observed' in text and 'LosingPositionAddGuardConfig: observed' in text and 'not_reached=9' in text,'CLI consumer -> summary JSON -> real text renderer'
 evidence=get_console_evidence(root)
 audit=DashboardService._summarize_paper_runs(object.__new__(DashboardService),[dict(category='system',action='paper_demo_complete',ts='2026-10-28T02:05:00Z',details='decisions=1 submitted=0'),dict(category='system',action='paper_demo_start',ts='2026-10-28T02:00:00Z')])
 payload=dict(time='2026-10-28T15:00:00Z',system=dict(status='unknown'),alerts=[],overview=dict(account={},trading_summary={}),positions=dict(positions=[],summary={}),charts=dict(overview={}),pipeline=dict(runs=audit,funnel={}),reconciliation=serialized,data_status=dict(counts={}),cron_jobs=dict(jobs=[]),trading=dict(available=True,summary={},daily_snapshots=[],closed_trades=[]),news=dict(items=[],diagnostics={}),archives={},console_evidence=evidence)
 (j/'browser_payload.json').write_text(json.dumps(payload))
 receipt=dict(cancel_to_serialized_service_to_JS=results,config_summary_text_renderer=True,web_config_receipts_panel_present=False,web_config_receipts_note='Web Console does not yet consume effective_config; CLI JSON/text receipt view only. No new web panel claimed.',evidence_snapshot_status=evidence['status'],latest_Console_preserved_except_audit_quantity_display_fix=True)
 (j/'integration_results.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt))
