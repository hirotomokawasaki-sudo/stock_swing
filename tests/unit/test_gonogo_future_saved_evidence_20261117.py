"""Regression 2026-11-17 FIX-06: clamped adapter age hides future ledger dates.
Acceptance uses native YAML/summary readers and report save; no internal mocks.
"""
from datetime import datetime, timedelta, timezone
import pytest
from test_gonogo_cached_ledger_freshness_20261117 import setup


def config(day):
    return 'mode: paper\nledger_quality_gate:\n  current_status: VALID\n  last_checked: "'+day+'"\n'


@pytest.mark.parametrize('offset',[1,2,365])
def test_ac_future_saved_date_fails_even_if_shared_age_is_clamped(tmp_path,offset):
    day=(datetime.now(timezone.utc).date()+timedelta(days=offset)).isoformat()
    m=setup(tmp_path,config(day));before=m.CURRENT_MODE_PATH.read_bytes()
    result=m.check()['ledger_quality']
    assert result['evidence']['age_seconds']==0, 'native adapter rounds future age to zero'
    assert result['pass'] is False, 'future saved evidence must never qualify as current'
    m.format_report({'ledger_quality':result},save=True)
    assert m.CURRENT_MODE_PATH.read_bytes()==before, 'report cannot repair or renew evidence'


def test_ac_maximum_date_is_future_not_current(tmp_path):
    m=setup(tmp_path,config('9999-12-31'))
    assert m.check()['ledger_quality']['pass'] is False, 'far future must fail closed'


@pytest.mark.parametrize('day',['garbage','2026-02-30','2026-11-18T00:00:00+00:00'])
def test_ac_malformed_saved_date_is_not_evidence(tmp_path,day):
    m=setup(tmp_path,config(day));before=m.CURRENT_MODE_PATH.read_bytes()
    assert m.check()['ledger_quality']['pass'] is False, 'date-only evidence required'
    assert m.CURRENT_MODE_PATH.read_bytes()==before, 'invalid inputs remain unmodified'


def test_ac_valid_future_valid_transition_and_report_does_not_stamp(tmp_path):
    today=datetime.now(timezone.utc).date()
    m=setup(tmp_path,config(today.isoformat()))
    for day,expected in [(today,True),(today+timedelta(days=1),False),(today,True)]:
        m.CURRENT_MODE_PATH.write_text(config(day.isoformat()))
        before=m.CURRENT_MODE_PATH.read_bytes();results=m.check()
        assert results['ledger_quality']['pass'] is expected, 'native reread must not cache qualification'
        m.format_report(results,save=True)
        assert m.CURRENT_MODE_PATH.read_bytes()==before, 'save cannot mutate config in either direction'
