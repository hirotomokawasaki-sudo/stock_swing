"""Actual selectors/script/main with synthetic HTTP and durable restart state."""
from pathlib import Path
import contextlib,io,json,os,runpy,sys
import httpx
root=Path.cwd();scenario=json.loads((root/'scenario.json').read_text())
from stock_swing.cli import reconcile_orders
assert Path(reconcile_orders.__file__).resolve().is_relative_to(root.resolve())
order=dict(id='fixture-order',symbol='AMD',side='sell' if scenario['entry']!='buy' else 'buy',type='market',time_in_force='day',qty='5',filled_qty='0',status='new',submitted_at='2026-06-07T01:34:06+00:00',extended_hours=False)
calls=[]
def transport(request):
    calls.append([request.method,request.url.path])
    with (root/'http_calls.jsonl').open('a') as f:f.write(json.dumps(calls[-1])+'\n');f.flush();os.fsync(f.fileno())
    if request.url.path.endswith('/account'):return httpx.Response(200,json=dict(id='account-fixture',status='ACTIVE',equity='100000',cash='100000',buying_power='100000'))
    if request.url.path.endswith('/positions'):return httpx.Response(200,json=[])
    if request.url.path.endswith('/orders'):
        return httpx.Response(200,json=[] if request.url.params.get('status')=='all' else [order])
    if request.method=='DELETE':
        (root/'accepted').write_text('fixture accepted')
        if scenario.get('die') and not (root/'died').exists():
            (root/'died').write_text('fixture death after acceptance')
            os._exit(77)
        if scenario.get('lost'):raise httpx.ReadTimeout('fixture ACK loss',request=request)
        return httpx.Response(204)
    if request.url.path.endswith('/fixture-order'):
        if (root/'accepted').exists():
            if scenario['after']=='404':return httpx.Response(404,json={})
            body=dict(order,status=scenario['after'],filled_qty=scenario.get('filled','0'))
            if scenario.get('mismatch'):body['symbol']='MSFT'
        else:body=order
        return httpx.Response(200,json=body)
    raise AssertionError(request.url.path)
original=httpx.Client
httpx.Client=lambda **kw:original(transport=httpx.MockTransport(transport),**kw)
from stock_swing.sources.broker_client import BrokerClient
broker=BrokerClient(api_key='fixture',api_secret='fixture',paper_mode=True)
buf=io.StringIO()
with contextlib.redirect_stdout(buf),contextlib.redirect_stderr(buf):
    if scenario['entry']=='buy':result=reconcile_orders.cancel_stale_buy_orders(broker)
    elif scenario['entry']=='sell':result=reconcile_orders.cancel_stale_sell_orders(broker,root)
    elif scenario['entry']=='main':result=reconcile_orders.main()
    else:
        sys.argv=['cancel_broker_orders','--order-id','fixture-order']+([] if scenario.get('preview') else ['--execute'])
        try:runpy.run_path(str(root/'scripts/cancel_broker_orders.py'),run_name='__main__')
        except SystemExit as exc:result=exc.code
store=root/'data/tracking/pending_exit_reasons.json'
print(json.dumps(dict(result=result,calls=calls,output=buf.getvalue(),exit_reason_present='fixture-order' in json.loads(store.read_text()) if store.exists() else False),sort_keys=True))
