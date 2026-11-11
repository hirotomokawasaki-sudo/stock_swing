"""Regression 2026-11-09: fixed wall ages/UTC days falsely stale on weekends.
Acceptance: scheduled-session freshness never excuses a missed slot, diagnostic,
bad clock or missing file, nor clears an actual control/overdue ledger audit.
"""
from datetime import datetime, timedelta, timezone
import json
import os
import pytest
from console.adapters.system_adapter import SystemAdapter

WEEKEND = datetime(2026, 11, 8, 19, tzinfo=timezone.utc)
FRIDAY = '2026-11-06T20:55:06+00:00'

def write(root, rel, value):
    f = root/rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(value))
    return f

def seed(root, *, stamp=FRIDAY, day='2026-11-06', status='ok'):
    write(root, 'reports/console/latest_console_summary.json', dict(run=dict(
        timestamp=stamp, dry_run=False, invocation_source='paper_demo_scheduled')))
    write(root, 'data/guardrails/circuit_breaker.json',dict(status=status,last_evaluated_at=stamp,reason='fixture'))
    write(root, 'data/guardrails/day_start_snapshot.json',dict(market_date=day,
        captured_at=day+'T14:25:02+00:00',source='broker_api',missing_fields=[]))

def test_ac_weekend_matches_completed_slot_without_modifying_files(tmp_path):
    seed(tmp_path)
    before = {str(f):f.read_bytes() for f in tmp_path.rglob('*') if f.is_file()}
    a = SystemAdapter(tmp_path)
    summary = a._check_console_summary_freshness(now=WEEKEND)
    guard = a._check_guardrail_freshness(now=WEEKEND)
    assert summary['ok'] and guard['ok'], (summary,guard)
    assert guard['expected_market_date']=='2026-11-06', guard
    assert summary['expected_run_at']=='2026-11-06T20:55:00+00:00', summary
    assert {str(f):f.read_bytes() for f in tmp_path.rglob('*') if f.is_file()}==before, 'health is read-only'

@pytest.mark.parametrize('now,due',[
    ('2026-11-09T14:34:59+00:00','2026-11-06T20:55:00+00:00'),
    ('2026-11-09T14:35:00+00:00','2026-11-09T14:25:00+00:00'),
    ('2026-10-30T20:06:00+00:00','2026-10-30T19:55:00+00:00'),
    ('2026-11-02T14:36:00+00:00','2026-11-02T14:25:00+00:00'),
    ('2026-12-25T18:00:00+00:00','2026-12-24T20:55:00+00:00'),
])
def test_ac_grace_holiday_dst_and_missed_slot(tmp_path,now,due):
    seed(tmp_path)
    now=datetime.fromisoformat(now)
    d=SystemAdapter(tmp_path)._check_console_summary_freshness(now=now)
    assert d['expected_run_at']==due, d
    assert d['ok'] == (datetime.fromisoformat(due)<=datetime.fromisoformat(FRIDAY)<=now), d

@pytest.mark.parametrize('kind',['missing','corrupt','list','manual','dry','naive','future','old'])
def test_ac_recent_mtime_cannot_launder_bad_summary(tmp_path,kind):
    seed(tmp_path)
    f=tmp_path/'reports/console/latest_console_summary.json'
    d=json.loads(f.read_text())
    if kind=='missing':f.unlink()
    elif kind=='corrupt':f.write_text('broken')
    elif kind=='list':f.write_text('[]')
    else:
        if kind=='manual':d['run']['invocation_source']='manual_diagnostic'
        if kind=='dry':d['run']['dry_run']=True
        if kind=='naive':d['run']['timestamp']='2026-11-06T20:55:06'
        if kind=='future':d['run']['timestamp']=(WEEKEND+timedelta(hours=1)).isoformat()
        if kind=='old':d['run']['timestamp']='2026-11-05T20:55:06+00:00'
        f.write_text(json.dumps(d))
    if f.exists():os.utime(f,(WEEKEND.timestamp(),WEEKEND.timestamp()))
    d=SystemAdapter(tmp_path)._check_console_summary_freshness(now=WEEKEND)
    assert not d['ok'], d

@pytest.mark.parametrize('status',['degraded','halted','recovery_pending','unknown'])
def test_ac_fresh_control_remains_visible_and_blocking(tmp_path,status):
    seed(tmp_path,status=status)
    d=SystemAdapter(tmp_path)._check_guardrail_freshness(now=WEEKEND)
    assert d['metrics_fresh'] and not d['ok'], d
    assert d['cb_status']==status and 'cb_'+status in d['problems'], d

@pytest.mark.parametrize('kind',['missing','corrupt','naive','future','wrong_day','missing_metrics','stale_cb'])
def test_ac_invalid_guardrail_inputs_fail_closed(tmp_path,kind):
    seed(tmp_path)
    rel='data/guardrails/day_start_snapshot.json'
    f=tmp_path/rel;d=json.loads(f.read_text())
    if kind=='missing':f.unlink()
    elif kind=='corrupt':f.write_text('broken')
    elif kind=='stale_cb':write(tmp_path,'data/guardrails/circuit_breaker.json',dict(status='ok',last_evaluated_at='2026-11-05T20:55:00Z'))
    else:
        if kind=='naive':d['captured_at']='2026-11-06T14:25:02'
        if kind=='future':d['captured_at']='2026-11-09T14:25:02Z'
        if kind=='wrong_day':d['market_date']='2026-11-05'
        if kind=='missing_metrics':d['missing_fields']=['day_start_equity']
        f.write_text(json.dumps(d))
    d=SystemAdapter(tmp_path)._check_guardrail_freshness(now=WEEKEND)
    assert not d['ok'],d

def test_ac_weekend_does_not_refresh_old_ledger_audit(tmp_path):
    p=tmp_path/'config/runtime/current_mode.yaml';p.parent.mkdir(parents=True)
    p.write_text('mode: paper\nledger_quality_gate:\n  current_status: VALID\n  last_checked: "2026-09-14"\n')
    before=p.read_bytes()
    d=SystemAdapter(tmp_path)._check_ledger_validity()
    assert not d['ok'] and d['stale'], d
    assert p.read_bytes()==before,'no stamp refresh'
