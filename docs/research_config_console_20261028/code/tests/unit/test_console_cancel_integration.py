"""Regression 2026-10-28: combined cancel+Console audit-only qty became 0."""
import importlib.util
from pathlib import Path
import pytest
root=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('console_fixture_helpers',root/'tests/unit/test_console_evidence_20261028.py')
helpers=importlib.util.module_from_spec(spec);spec.loader.exec_module(helpers)

@pytest.mark.parametrize('details,expected',[('sell 3.7 AMD','3.7'),('sell 3 AMD',3),('',None),('sell PRIVATE-CANARY AMD',None),('sell NaN AMD',None),('sell -3 AMD',None)])
def test_ac_failed_broker_audit_quantity_preserved_or_unknown(tmp_path,details,expected):
 svc=helpers.service(tmp_path,error=True)
 rows=svc._fetch_broker_pending_orders([dict(subject='fixture-order',details=details)],[])
 assert rows[0]['qty']==expected,'audit-only missing/fractional qty must not become zero'
 assert rows[0]['status']=='unconfirmed' and rows[0]['source']=='audit_only','quantity parsing cannot confirm order state'
 html=helpers.js('renderPendingOrdersTable',{'args':[rows,svc._broker_orders_evidence]})
 assert '取得未確認' in html and '取消確認済' not in html,'failure warning survives populated rows'
 assert (str(expected) if expected is not None else '未取得') in html,'quantity propagates service -> real renderer'
 assert 'PRIVATE-CANARY' not in html,'raw detail/error not exposed'
