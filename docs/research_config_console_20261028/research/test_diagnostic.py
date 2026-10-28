"""Acceptance: fixed five-session proxy, missingness and exact tie boundaries."""
from datetime import date
import pytest
from analyze import band,interval,net,outcome,sessions,timestamp,valid_bar

@pytest.mark.parametrize('value',[None,True,float('nan'),float('inf'),-.1,1.1])
def test_invalid_score_never_enters_band(value):
 assert band(value) is None,'missing or invalid score cannot become zero'

@pytest.mark.parametrize('value,expected',[(0,'0-.4'),(.4,'.4-.6'),(.6,'.6-.8'),(.8,'.8-1'),(1,'.8-1')])
def test_equal_scores_have_fixed_unsplit_band(value,expected):
 assert band(value)==band(value)==expected,'ties cannot be count-ranked into distinct bands'

@pytest.mark.parametrize('value',[None,'bad','2026-05-12T12:00:00'])
def test_missing_naive_timestamp_refused(value):
 assert timestamp(value) is None,'aware clock required'

def bars(days):return {d:dict(open=100,close=105,high=110,low=90,volume=1000) for d in days}

def test_calendar_holiday_and_weekend_not_counted_as_outcome():
 days=sessions(date(2026,7,2),date(2026,7,13))
 assert days==['2026-07-02','2026-07-06','2026-07-07','2026-07-08','2026-07-09','2026-07-10','2026-07-13'],'observed July4 and weekend excluded'
 o,error=outcome(bars(days),days,'2026-07-02')
 assert error is None and o['entry_date']=='2026-07-06' and o['exit_date']=='2026-07-10','five expected sessions, no same-day fill'

def test_gap_is_rejected_not_compressed():
 days=sessions(date(2026,7,6),date(2026,7,20));p=bars(days);del p[days[2]]
 assert outcome(p,days,'2026-07-05')[0] is None,'missing middle bar cannot advance horizon to later available day'

@pytest.mark.parametrize('field,value',[('open',None),('volume',True),('close',float('inf')),('high',80),('low',120)])
def test_invalid_ohlcv_refused(field,value):
 b=bars(['d'])['d'];b[field]=value
 assert valid_bar(b) is False,'invalid path cannot enter return calculation'

def test_right_censored_window_rejected():
 days=['2026-07-06','2026-07-07']
 assert outcome(bars(days),days,'2026-07-05')[1]=='outside_calendar','never shorten the five-session horizon'

def test_cost_charged_both_legs_not_raw_return_subtraction():
 assert net(100,100,5)==pytest.approx(99.95/100.05-1),'entry/exit proportional cost formula'

def test_short_span_cannot_manufacture_degenerate_confidence_interval():
 days=sessions(date(2026,7,6),date(2026,7,20));r=interval({days[0]:.1,days[-1]:.2},days)
 assert r['status']=='insufficient_20_session_blocks' and r['low'] is None and r['high'] is None,'a block spanning the whole sample provides no uncertainty estimate'
