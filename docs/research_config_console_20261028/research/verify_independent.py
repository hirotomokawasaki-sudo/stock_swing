"""Independent Decimal event and grouped-mean check, no analyzer import."""
from pathlib import Path
from datetime import date,datetime,timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo
from collections import defaultdict,Counter
import json,sys,statistics
from market_calendar import MarketCalendar
p=Path(__file__).resolve().parent
out=Path(sys.argv[1]);rows=json.loads((p/'decisions.json').read_text());events=json.loads((out/'events.json').read_text());r=json.loads((out/'results.json').read_text())
prices={f.stem:json.loads(f.read_text(),parse_float=D) for f in (p/'prices').glob('*.json')}
ids=Counter(x['id'] for x in rows);assert all(n==1 for n in ids.values()),'independent check requires reviewed unique identities'
matched={e['id']:e for e in events};eligible=set();by=defaultdict(list);cells=0
for x in rows:
 if x['action']!='buy':continue
 t=datetime.fromisoformat(x['decision_time'].replace('Z','+00:00'));day=t.astimezone(ZoneInfo('America/New_York')).date()
 ds=[];d=day+timedelta(days=1)
 while len(ds)<5:
  if d.weekday()<5 and not MarketCalendar.is_us_holiday(d)[0]:ds.append(d.isoformat())
  d+=timedelta(days=1)
 ps=prices.get(x['symbol']);bs=prices['SPY']
 if ps is None or not all(k in ps and k in bs for k in ds):continue
 eligible.add(x['id']);e=matched[x['id']]
 assert (e['entry_date'],e['exit_date'])==(ds[0],ds[-1]),'independently derived dates'
 for bps in [0,2,5,10,15]:
  c=D(bps)/10000;ret=D(str(ps[ds[-1]]['close']))*(1-c)/(D(str(ps[ds[0]]['open']))*(1+c))-1
  benchmark=D(str(bs[ds[-1]]['close']))*(1-c)/(D(str(bs[ds[0]]['open']))*(1+c))-1
  assert abs(float(ret)-e['net_'+str(bps)])<1e-12 and abs(float(ret-benchmark)-e['excess_'+str(bps)])<1e-12,'independent Decimal arithmetic'
  cells+=2
 by[(e['strategy'],e['asset_class'],e['band'])].append(e)
assert eligible==set(matched),'no omitted or invented eligible event'
assert len(eligible)==r['proxy_event_count'] and sum(r['coverage'].values())==len(rows),'coverage partition'
for g in r['groups']:
 es=by[(g['strategy'],g['asset_class'],g['score_band'])];days=defaultdict(list)
 for e in es:days[e['day']].append(e)
 assert len(es)==g['event_count'] and len(days)==g['signal_days'],'group counts'
 for cost in [0,2,5,10,15]:
  for field,key in [('net_','net_price_return'),('excess_','SPY_excess')]:
   val=sum(sum(D(str(e[field+str(cost)])) for e in rs)/len(rs) for rs in days.values())/len(days)
   assert abs(float(val)-g['costs'][str(cost)][key])<1e-12,'independent day-first mean'
assert r['qualified_forward_additions']==0 and not r['S3_consumed'] and not r['F1_started'],'proxy cannot advance qualification'
print(json.dumps(dict(independent_events=len(eligible),decimal_return_cells=cells,group_count=len(r['groups']),coverage_partition=True,qualification_preserved=True)))
