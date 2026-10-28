"""Independent arithmetic/overlap check from the private raw snapshots (no cost inference)."""
from pathlib import Path
import csv,hashlib,json,sqlite3
j=Path(__file__).resolve().parent
summary=json.loads((j/'usage_summary.json').read_text());records={}
con=sqlite3.connect(':memory:');con.execute('create table tokens(dataset text,i integer,o integer,t integer,k text)')
for name in ['token_usage.csv','token_usage_backfill.csv','token_usage_legacy_mixed_schema_20260801.csv','ai_usage.jsonl']:
 path=j/'usage_inputs'/name;lines=path.read_text().splitlines()
 if name.endswith('.jsonl'):rows=[json.loads(line) for line in lines]
 else:
  data=[r for r in csv.reader(lines) if len(r)==11];rows=[]
  for r in data[1:]:
   row=dict(input_tokens=r[3],output_tokens=r[4],total_tokens=r[5]);row['decision_id']=r[7] if r[-1]=='estimated_rule_based' else None;rows.append(row)
 for row in rows:
  vals=[int(row[k]) for k in ('input_tokens','output_tokens','total_tokens')];assert vals[0]+vals[1]==vals[2]
  key=hashlib.sha256(str(row['decision_id']).encode()).hexdigest() if row.get('decision_id') else None
  con.execute('insert into tokens values (?,?,?,?,?)',(name,*vals,key))
 n,i,o,t=con.execute('select count(*),sum(i),sum(o),sum(t) from tokens where dataset=?',(name,)).fetchone();expected=summary['datasets'][name]
 assert [n,i,o,t]==[expected[k] for k in ('valid_token_rows','input_tokens','output_tokens','total_tokens')],name
 records[name]=dict(rows=n,input=i,output=o,total=t)
shared=con.execute("select count(*) from tokens a join tokens b on a.k=b.k where a.dataset='ai_usage.jsonl' and b.dataset='token_usage_backfill.csv'").fetchone()[0];assert shared==1939
lat=list(csv.DictReader((j/'usage_inputs/api_latency.csv').open()));assert len(lat)==summary['datasets']['api_latency.csv']['parsed_rows']
runtime_rows={tuple(r) for r in csv.reader((j/'usage_inputs/token_usage.csv').read_text().splitlines()) if len(r)==11 and r[0]!='timestamp'}
archive_runtime={tuple(r) for r in csv.reader((j/'usage_inputs/token_usage_legacy_mixed_schema_20260801.csv').read_text().splitlines()) if len(r)==11 and r[7] in ('True','False')}
assert len(runtime_rows & archive_runtime)==31
result=dict(archived_runtime_rows_repeated_in_current=31,independent_method='raw CSV/JSON + in-memory SQLite sums/join',datasets=records,shared_decision_ids=shared,latency_rows=len(lat),matches=True)
(j/'usage_independent.json').write_text(json.dumps(result,indent=2,sort_keys=True));print(json.dumps(result))
