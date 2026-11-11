"""FIX-04 2026-11-04 / base8909e79: preflight unknown must not be clean.
Only external HTTP and clock are replaced; real CLI, JSON, reader and CB store.
"""
from pathlib import Path
import json,shutil,subprocess,sys
import pytest

@pytest.mark.parametrize("scenario,expected_exit", [
 ({},0),
 ({"recovery_pending":True},0),
 ({"orders":{"incomplete":True}},1),
 ({"orders":{"incomplete":True},"recovery_pending":True},1),
 ({"symbols":"MSFT,CRM","submit_timeout":True},1),
 ({"symbols":"MSFT","positions":[dict(symbol="NOW",qty="100",market_value="34000",current_price="340",avg_entry_price="340",unrealized_pl="0",unrealized_plpc="0",asset_class="us_equity")]},0),
])
def test_ac_actual_cli_preflight_outcome_not_false_clean(tmp_path,scenario,expected_exit):
 source=Path(__file__).resolve().parents[2]
 for name in ["src","config"]:shutil.copytree(source/name,tmp_path/name)
 (tmp_path/"config/runtime/current_mode.yaml").write_text("mode: paper\n")
 (tmp_path/"config/guardrails/autonomous_stop.yaml").write_text("paper_warning_only: true\nrules: {}\n")
 if scenario.get("recovery_pending"):
  cb=tmp_path/"data/guardrails/circuit_breaker.json";cb.parent.mkdir(parents=True)
  cb.write_text(json.dumps(dict(status="recovery_pending",action="allow",reason="fixture_requires_clean_run",triggered_rules=[],latest_triggered_rules=[])))
 state=tmp_path/"data/tracking/pnl_state.json";state.parent.mkdir(parents=True);state.write_text(json.dumps(dict(last_updated="2026-10-28T14:59:00+00:00",trades=[])))
 (tmp_path/"scenario.json").write_text(json.dumps(dict(scenario,capture=True,config_capture=True)))
 shutil.copy2(source/"tests/fixtures/k04_cli_driver.py",tmp_path/"driver.py")
 profile=tmp_path/"deny.sb";profile.write_text('(version 1)\n(allow default)\n(deny network*)\n(deny file-write*)\n(allow file-write* (subpath '+json.dumps(str(tmp_path))+'))\n(allow file-write* (literal "/dev/null"))\n(deny file-read* (subpath '+json.dumps(str(source))+'))\n')
 env=dict(PATH="/usr/bin:/bin",TZ="Asia/Tokyo",PYTHONPATH=str(tmp_path/"src"),PYTHONDONTWRITEBYTECODE="1",BROKER_API_KEY="fixture",BROKER_API_SECRET="fixture",BROKER_BASE_URL="https://paper-fixture.invalid",MASSIVE_API_KEY="fixture")
 p=subprocess.run(["/usr/bin/sandbox-exec","-f",str(profile),sys.executable,"-B",str(tmp_path/"driver.py")],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=35)
 assert p.returncode==0,p.stderr
 d=json.loads(p.stdout)
 assert d["origin_is_copy"] and d["capture_complete"],"real private CLI and saved reader"
 assert d["main_exit"]==expected_exit,d.get("diagnostic_tail")
 assert d["declared_exit_success"] is (expected_exit==0),"capture completion != business success"
 if expected_exit:
  assert d["run_status"]=="DEGRADED",d
  assert any("order_preflight_unavailable" in json.dumps(a) for a in d["alerts"]),d["alerts"]
  if not scenario.get("submit_timeout"):assert not d["posts"],"unknown snapshot cannot BUY"
  else:
   attempted={p["symbol"] for p in d["posts"]}
   assert len(attempted)==1 and attempted <= {"MSFT","CRM"},"later BUY contained; generation tie order is not a newly adopted winner policy"
 if scenario.get("recovery_pending"):
  assert d["breaker_state"]["status"] == ("recovery_pending" if expected_exit else "ok"),"unknown run not clean; normal recovery preserved"
 if scenario.get("positions"):
  assert all(p["side"]=="sell" for p in d["posts"]),"SELL unchanged"
  assert d["funnel"]["stages"]["allocation_blocked"]==1,"held BUY must reach saved funnel"
