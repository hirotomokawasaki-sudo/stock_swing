"""Regression 2026-11-04 FIX-03/K03 base 8909e79: unknown exposure reported OK.
Acceptance: actual CLI must preserve unknown/held through summary and capture reader.
Only external HTTP and clock inputs are substituted in the fixture driver.
"""
from pathlib import Path
import json, shutil, subprocess, sys
import pytest

@pytest.mark.parametrize("scenario,expected_exit,alert", [
    ({},0,None),
    ({"state":"missing"},1,"risk_budget_unavailable"),
    ({"state":"missing","recovery_pending":True},1,"risk_budget_unavailable"),
    ({"positions_bad_after":2},1,"risk_inputs_unavailable"),
    ({"positions_bad_after":3},1,"risk_inputs_unavailable"),
])
def test_ac_actual_cli_unknown_risk_is_not_clean(tmp_path, scenario, expected_exit, alert):
    source=Path(__file__).resolve().parents[2]
    for name in ["src","config"]:shutil.copytree(source/name,tmp_path/name)
    (tmp_path/"config/runtime/current_mode.yaml").write_text("mode: paper\n")
    (tmp_path/"config/guardrails/autonomous_stop.yaml").write_text("paper_warning_only: true\nrules: {}\n")
    if scenario.get("recovery_pending"):
        cb=tmp_path/"data/guardrails/circuit_breaker.json";cb.parent.mkdir(parents=True)
        cb.write_text(json.dumps(dict(status="recovery_pending",action="allow",reason="fixture_requires_clean_run",triggered_rules=[],latest_triggered_rules=[])))
    state=tmp_path/"data/tracking/pnl_state.json";state.parent.mkdir(parents=True)
    if scenario.get("state")!="missing":state.write_text(json.dumps({"last_updated":"2026-10-28T14:59:00+00:00","trades":[]}))
    (tmp_path/"scenario.json").write_text(json.dumps(dict(scenario,capture=True,config_capture=True)))
    shutil.copy2(source/"tests/fixtures/k03_cli_driver.py",tmp_path/"driver.py")
    profile=tmp_path/"deny.sb";profile.write_text('(version 1)\n(allow default)\n(deny network*)\n(deny file-write*)\n(allow file-write* (subpath '+json.dumps(str(tmp_path))+'))\n(allow file-write* (literal "/dev/null"))\n(deny file-read* (subpath '+json.dumps(str(source))+'))\n')
    env=dict(PATH="/usr/bin:/bin",TZ="Asia/Tokyo",PYTHONPATH=str(tmp_path/"src"),PYTHONDONTWRITEBYTECODE="1",BROKER_API_KEY="fixture",BROKER_API_SECRET="fixture",BROKER_BASE_URL="https://paper-fixture.invalid",MASSIVE_API_KEY="fixture")
    run=subprocess.run(["/usr/bin/sandbox-exec","-f",str(profile),sys.executable,"-B",str(tmp_path/"driver.py")],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=35)
    assert run.returncode==0, run.stderr
    data=json.loads(run.stdout)
    assert data["origin_is_copy"] and data["capture_complete"], "real module/reader must run on private copy"
    assert data["main_exit"]==expected_exit, data.get("diagnostic_tail")
    assert data["declared_exit_success"]==(expected_exit==0), "capture completion is not business success"
    if scenario.get("recovery_pending"):
        assert data["breaker_state"]["status"]=="recovery_pending", "unknown risk is not a clean verification run"
    if alert:
        assert not data["posts"], "unknown risk must not submit BUY"
        assert data["run_status"]=="DEGRADED", "unavailable exposure must not be reported healthy"
        assert any(a["code"]==alert for a in data["alerts"]), "reason must reach saved JSON alerts"
    else:
        assert len(data["posts"])==1 and data["posts"][0]["qty"]==61, "normal sizing must remain unchanged"
