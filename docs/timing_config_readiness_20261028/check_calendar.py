from pathlib import Path
from datetime import date,timedelta,time
import json
from stock_swing.execution.cancellation_timing import session_bounds
ref=json.loads((Path(__file__).resolve().parent/'calendar_reference.json').read_text())
day=date(2026,1,1);count=0
while day<date(2029,1,1):
 bounds=session_bounds(day);expected=day.weekday()<5 and day.isoformat() not in ref['closed_dates']
 assert bool(bounds)==expected,(day,bounds,expected)
 if bounds:
  assert bounds[0].time()==time(9,30),(day,bounds)
  assert bounds[1].time()==time(13 if day.isoformat() in ref['early_close_13_ET'] else 16),(day,bounds)
 day+=timedelta(days=1);count+=1
print(json.dumps(dict(calendar_days=count,official_closed_dates=len(ref['closed_dates']),early_close_dates=len(ref['early_close_13_ET']),all_match=True),sort_keys=True))
