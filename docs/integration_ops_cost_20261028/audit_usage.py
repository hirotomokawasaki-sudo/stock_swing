"""Local, provenance-bounded audit. No network/pricing/provider usage inference."""
from pathlib import Path
import argparse,collections,csv,hashlib,json,math,statistics
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
TOKEN_FIELDS=['timestamp','workflow_name','model','input_tokens','output_tokens','total_tokens','estimated_cost','success','retry_count','error','skip_reason']
BACK_FIELDS=['timestamp','workflow_name','model','input_tokens','output_tokens','total_tokens','estimated_cost','decision_id','symbol','context_pack','telemetry_source']
LAT_FIELDS=['endpoint','started_at','duration_ms','status','error_type','retry_count','symbol']
def sha(b):return hashlib.sha256(b).hexdigest()
def parse_csv(text,name):
 rows=list(csv.reader(text.splitlines()));records=[];notes=collections.Counter();header=None
 for row in rows:
  if not row:notes['blank']+=1;continue
  if len(row)==1 and row[0].startswith('#'):notes['comments']+=1;continue
  if row in (TOKEN_FIELDS,BACK_FIELDS,LAT_FIELDS):
   notes['headers']+=1;header=row;continue
  if header is None or len(row)!=len(header):notes['invalid_width_or_header']+=1;continue
  # Archive rows are mixed under the old runtime header; recognize exact backfill source.
  fields=header
  if name.startswith('token_usage_legacy'):
   if row[-1]=='estimated_rule_based':fields=BACK_FIELDS
   elif row[7] in ('True','False'):fields=TOKEN_FIELDS
   else:notes['unrecognized_archive_schema']+=1;continue
  r=dict(zip(fields,row));r.pop('error',None);r.pop('skip_reason',None);r.pop('symbol',None);r.pop('context_pack',None)
  if r.get('decision_id'):r['decision_key']=sha(r.pop('decision_id').encode())
  r['schema']='latency' if fields==LAT_FIELDS else 'decision_estimate' if fields==BACK_FIELDS else 'runtime_summary'
  records.append(r)
 return records,dict(notes)
def freeze(folder):
 result={}
 for path in sorted(folder.iterdir()):
  data=path.read_bytes();notes={}
  if path.suffix=='.csv':records,notes=parse_csv(data.decode(),path.name)
  else:
   records=[]
   for line in data.decode().splitlines():
    try:r=json.loads(line)
    except (ValueError,TypeError):notes['invalid_json']=notes.get('invalid_json',0)+1;continue
    keep={k:r.get(k) for k in ('timestamp','model','input_tokens','output_tokens','total_tokens','telemetry_source')}
    if r.get('decision_id'):keep['decision_key']=sha(str(r['decision_id']).encode())
    keep['schema']='decision_estimate';records.append(keep)
  result[path.name]=dict(source_sha256=sha(data),source_bytes=len(data),notes=notes,records=records)
 return result

def valid_tokens(r):
 values=[]
 for k in ('input_tokens','output_tokens','total_tokens'):
  x=r.get(k)
  if isinstance(x,bool) or x is None or not str(x).isdigit():raise ValueError('invalid_nonnegative_integer')
  values.append(int(x))
 if values[0]+values[1]!=values[2]:raise ValueError('token_sum_mismatch')
 return values

def stamp(value):
 d=datetime.fromisoformat(str(value).replace('Z','+00:00'))
 if d.tzinfo is None:raise ValueError('timezone_missing')
 return d.astimezone(timezone.utc).isoformat()

def aggregate(inputs):
 datasets={};ids={};joins={}
 for name,item in inputs.items():
  rows=item['records'];issues=collections.Counter();schemas=collections.Counter();models=collections.Counter();workflows=collections.Counter();sources=collections.Counter();totals=[0,0,0];valid=0;cost=Decimal(0);cost_rows=0;dates=[];identities={};cost_bad=0
  latency=[];endpoints=collections.Counter();statuses=collections.Counter();retry_total=0;retry_unknown=0
  for r in rows:
   schemas[r['schema']]+=1
   try:dates.append(stamp(r.get('timestamp',r.get('started_at'))))
   except (ValueError,TypeError):issues['timestamp']+=1
   if r['schema']=='latency':
    endpoints[r['endpoint']]+=1;statuses[r['status']]+=1
    try:
     duration=float(r['duration_ms']);assert math.isfinite(duration) and duration>=0
     latency.append(duration)
    except (ValueError,AssertionError):issues['duration']+=1
   else:
    models[str(r.get('model'))]+=1;workflows[str(r.get('workflow_name','not_recorded'))]+=1;sources[str(r.get('telemetry_source','not_recorded'))]+=1
    try:
     values=valid_tokens(r);totals=[a+b for a,b in zip(totals,values)];valid+=1
     if r.get('decision_key'):
      fingerprint=tuple(values)+(r.get('model'),r.get('telemetry_source'))
      key=r['decision_key']
      if key in identities:
       issues['duplicate_decision_id']+=1
       if identities[key]!=fingerprint:issues['conflicting_decision_id']+=1
      identities[key]=fingerprint
    except ValueError as exc:issues[str(exc)]+=1
    if 'estimated_cost' in r:
     try:
      amount=Decimal(str(r['estimated_cost']));assert amount.is_finite() and amount>=0
      cost+=amount;cost_rows+=1
     except (InvalidOperation,AssertionError):cost_bad+=1
   if 'retry_count' in r and str(r['retry_count']).isdigit():retry_total+=int(r['retry_count'])
   else:retry_unknown+=1
  ids[name]=identities
  base=dict(parsed_rows=len(rows),schemas=dict(schemas),parse_notes=item['notes'],issues=dict(issues),earliest_utc=min(dates) if dates else None,latest_utc=max(dates) if dates else None,exact_duplicate_rows=len(rows)-len({json.dumps(r,sort_keys=True) for r in rows}))
  if latency:
   ordered=sorted(latency);base['latency']=dict(valid_rows=len(latency),p50_ms=statistics.median(latency),p95_nearest_rank_ms=ordered[math.ceil(.95*len(ordered))-1],endpoints=dict(endpoints),statuses=dict(statuses),reported_retry_sum=retry_total,retry_unknown_rows=retry_unknown,not_billable_http_count=True)
  else:
   base.update(valid_token_rows=valid,input_tokens=totals[0],output_tokens=totals[1],total_tokens=totals[2],models=dict(models),workflows=dict(workflows),telemetry_sources=dict(sources),unique_decision_ids=len(identities),logged_estimated_cost_sum=str(cost) if cost_rows else None,cost_rows=cost_rows,invalid_cost_rows=cost_bad,currency=None,billable_provider_tokens=None,invoiced_cost=None,reported_retry_sum=retry_total,retry_unknown_rows=retry_unknown)
  datasets[name]=base
 names=list(ids)
 for n,a in enumerate(names):
  for b in names[n+1:]:
   shared=set(ids[a])&set(ids[b])
   if shared:joins[a+' :: '+b]=dict(shared_decision_ids=len(shared),token_model_source_conflicts=sum(ids[a][k]!=ids[b][k] for k in shared))
 return dict(datasets=datasets,overlaps=joins,combined_token_total=None,combined_invoiced_cost=None,reason='Overlapping backfills, aggregate runtime summaries, and archived mixed schemas are not additive. Historical estimates and zero placeholders are not invoices.',actual_provider_usage_evidence='not established by these five inputs',pricing_applied=False)

def main():
 p=argparse.ArgumentParser();p.add_argument('--raw');p.add_argument('--review');p.add_argument('--out',required=True);p.add_argument('--freeze-out');a=p.parse_args()
 inputs=freeze(Path(a.raw)) if a.raw else json.loads(Path(a.review).read_text())
 if a.freeze_out:Path(a.freeze_out).write_text(json.dumps(inputs,indent=2,sort_keys=True))
 Path(a.out).write_text(json.dumps(aggregate(inputs),indent=2,sort_keys=True))
if __name__=='__main__':main()
