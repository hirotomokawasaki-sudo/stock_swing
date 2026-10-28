"""Frozen-input-only continuation of the existing five-session diagnostic."""
from pathlib import Path
from datetime import date,datetime,timedelta
from zoneinfo import ZoneInfo
from collections import Counter,defaultdict
import argparse,bisect,hashlib,json,math,random,statistics
from market_calendar import MarketCalendar
ET=ZoneInfo('America/New_York')
def number(x):return type(x) in (int,float) and math.isfinite(x)
def load(p):
 def pairs(items):
  out={}
  for k,v in items:
   if k in out:raise ValueError('duplicate JSON key')
   out[k]=v
  return out
 return json.loads(p.read_text(),object_pairs_hook=pairs)
def timestamp(x):
 try:
  d=datetime.fromisoformat(x.replace('Z','+00:00'))
  return d if d.tzinfo is not None and d.utcoffset() is not None else None
 except (ValueError,AttributeError,TypeError):return None
def sessions(start,end):
 result=[];d=start
 while d<=end:
  if d.weekday()<5 and not MarketCalendar.is_us_holiday(d)[0]:result.append(d.isoformat())
  d+=timedelta(days=1)
 return result
def valid_bar(b):
 return isinstance(b,dict) and all(number(b.get(k)) and b[k]>0 for k in ['open','high','low','close','volume']) and b['high']>=max(b['open'],b['low'],b['close']) and b['low']<=min(b['open'],b['high'],b['close'])
def outcome(prices,calendar,day,h=5):
 start=bisect.bisect_right(calendar,day);window=calendar[start:start+h]
 if len(window)!=h:return None,'outside_calendar'
 if any(not valid_bar(prices.get(d)) for d in window):return None,'missing_or_invalid_five_session_path'
 return dict(entry_date=window[0],exit_date=window[-1],entry_open=prices[window[0]]['open'],exit_close=prices[window[-1]]['close']),None
def net(entry,exit_,bps):
 c=bps/10000
 return exit_*(1-c)/(entry*(1+c))-1
def band(score):
 if not number(score) or not 0<=score<=1:return None
 return '0-.4' if score<.4 else '.4-.6' if score<.6 else '.6-.8' if score<.8 else '.8-1'
def interval(day_values,calendar):
 if len(day_values)<2:return None
 first=min(day_values);last=max(day_values);grid=[d for d in calendar if first<=d<=last]
 if len(grid)<40:return dict(status='insufficient_20_session_blocks',low=None,high=None,resamples=0,expected_session_span=len(grid),block_sessions=20,sparse_or_fewer_than_five_blocks=True)
 width=20;rng=random.Random(7);draws=[];attempts=0
 while len(draws)<4000:
  attempts+=1
  if attempts>40000:raise ValueError('insufficient nonempty block draws')
  sample=[]
  while len(sample)<len(grid):
   begin=rng.randrange(len(grid)-width+1);sample+=grid[begin:begin+width]
  values=[day_values[d] for d in sample[:len(grid)] if d in day_values]
  if values:draws.append(statistics.mean(values))
 draws.sort()
 return dict(status='exploratory_block_sensitivity',low=draws[int(.025*(len(draws)-1))],high=draws[int(.975*(len(draws)-1))],resamples=len(draws),empty_draws_excluded=attempts-len(draws),expected_session_span=len(grid),block_sessions=width,sparse_or_fewer_than_five_blocks=len(grid)<100)
def analyze(packet):
 pins=load(packet/'input_manifest.json')
 for name,pin in pins.items():
  if hashlib.sha256((packet/name).read_bytes()).hexdigest()!=pin:raise ValueError('input drift:'+name)
 spec=load(packet/'SPEC.json');rows=load(packet/'decisions.json');classes=load(packet/'classification.json')
 prices={p.stem:load(p) for p in (packet/'prices').glob('*.json')};calendar=sessions(date(2026,1,1),date(2026,12,31))
 ids=defaultdict(list)
 for r in rows:ids[r['id']].append(r)
 counters=Counter();events=[];dups=Counter();seen=set()
 for r in rows:
  rid=r['id']
  if rid is None:counters['missing_decision_id']+=1;continue
  variants={json.dumps({k:v for k,v in x.items() if k!='source_sha256'},sort_keys=True) for x in ids[rid]}
  if len(variants)>1:counters['conflicting_duplicate_identity']+=1;continue
  if rid in seen:counters['identical_duplicate_identity']+=1;continue
  seen.add(rid)
  if r['action']!='buy':counters['not_stored_buy']+=1;continue
  b=band(r['signal_strength'])
  if b is None:counters['missing_or_invalid_score']+=1;continue
  t=timestamp(r['decision_time'])
  if not t or t.year!=2026:counters['missing_naive_or_outside_2026_timestamp']+=1;continue
  day=t.astimezone(ET).date().isoformat();symbol=r['symbol']
  if symbol not in prices:counters['symbol_without_frozen_price']+=1;continue
  o,reason=outcome(prices[symbol],calendar,day);bench,br=outcome(prices['SPY'],calendar,day)
  if reason or br:counters['missing_or_invalid_five_session_path']+=1;continue
  assert (o['entry_date'],o['exit_date'])==(bench['entry_date'],bench['exit_date'])
  event=dict(id=rid,day=day,symbol=symbol,strategy=r['strategy_id'],asset_class=classes.get(symbol,'unknown'),score=r['signal_strength'],band=b,**o,benchmark_entry=bench['entry_open'],benchmark_exit=bench['exit_close'])
  for cost in spec['costs_bps_per_side']:
   event['net_'+str(cost)]=net(o['entry_open'],o['exit_close'],cost)
   event['excess_'+str(cost)]=event['net_'+str(cost)]-net(bench['entry_open'],bench['exit_close'],cost)
  events.append(event);counters['proxy_computable']+=1;dups[(day,symbol)]+=1
 assert sum(counters.values())==len(rows)
 groups=defaultdict(list)
 for e in events:groups[(e['strategy'],e['asset_class'],e['band'])].append(e)
 result_groups=[]
 for (strategy,asset,b),rs in sorted(groups.items()):
  daily=defaultdict(list)
  for e in rs:daily[e['day']].append(e)
  costs={}
  for cost in spec['costs_bps_per_side']:
   costs[str(cost)]=dict(net_price_return=statistics.mean(statistics.mean(e['net_'+str(cost)] for e in es) for es in daily.values()),SPY_excess=statistics.mean(statistics.mean(e['excess_'+str(cost)] for e in es) for es in daily.values()))
  day_values={d:statistics.mean(e['excess_5'] for e in es) for d,es in daily.items()}
  result_groups.append(dict(strategy=strategy,asset_class=asset,score_band=b,event_count=len(rs),signal_days=len(daily),symbols=len({e['symbol'] for e in rs}),costs=costs,excess_5bps_block_interval=interval(day_values,calendar)))
 result=dict(study_id=spec['study_id'],input_decisions=len(rows),coverage=dict(counters),proxy_event_count=len(events),proxy_signal_days=len({e['day'] for e in events}),first_signal_day=min((e['day'] for e in events),default=None),last_signal_day=max((e['day'] for e in events),default=None),last_outcome_day=max((e['exit_date'] for e in events),default=None),repeat_symbol_day_additional_rows=sum(n-1 for n in dups.values()),groups=result_groups,qualified_forward_additions=0,price_basis_qualified=False,full_candidate_denominator_known=False,portfolio_metrics_computed=False,S1_complete=False,S2_complete=False,S3_consumed=False,S4_started=False,F1_started=False,production_applied=False)
 return result,events
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();packet=Path(__file__).resolve().parent
 result,events=analyze(packet);out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=True)
 for name,data in [('results.json',result),('events.json',events)]:
  (out/name).write_text(json.dumps(data,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n')
 print(json.dumps({k:result[k] for k in ['input_decisions','coverage','proxy_signal_days','first_signal_day','last_signal_day','qualified_forward_additions']}))
if __name__=='__main__':main()
