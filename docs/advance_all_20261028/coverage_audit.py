from pathlib import Path
import ast,hashlib,json,sys
from stock_swing.risk.allocation_config import read_symbol_registry
from stock_swing.risk.correlation_cluster import get_cluster_for_symbol
j=Path(__file__).parent;r=j/'candidate'
cli=r/'src/stock_swing/cli/paper_demo.py';tree=ast.parse(cli.read_text())
universe=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='DEFAULT_SYMBOLS' for t in n.targets))
regpath=r/'config/reference/symbol_registry.yaml';registry=read_symbol_registry(regpath)
pnlpath=r/'data/tracking/pnl_state.json';pnl=json.loads(pnlpath.read_text())
trades=pnl.get('trades',[]);held=sorted({t['symbol'] for t in trades if t.get('status')=='open'})
# Existing local open-order envelopes, if any, are not a fresh broker snapshot.
original=Path('/Users/hirotomookawasaki/stock_swing')
files=sorted((original/'data/raw/broker').glob('*orders*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
pending=[];pending_source=None
if files:
 p=files[0];d=json.loads(p.read_text());rows=d.get('payload',[]) if isinstance(d,dict) else d
 if isinstance(rows,list):pending=sorted({row['symbol'] for row in rows if isinstance(row,dict) and row.get('symbol') and row.get('status') not in {'filled','canceled','expired','rejected','replaced'}})
 pending_source=dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),qualification='local saved envelope; freshness/completeness unverified')
rows=[]
for symbol in sorted(set(universe)|set(held)|set(pending)):
 info=registry.get(symbol,{})
 clusters=get_cluster_for_symbol(symbol)
 semi=info.get('is_semiconductor_related')
 rows.append(dict(symbol=symbol,in_default=symbol in universe,held_in_saved_tracker=symbol in held,pending_in_saved_envelope=symbol in pending,asset_class=info.get('asset_class','unknown'),semiconductor_flag=semi,clusters=clusters,semiconductor_gap=semi is True and 'semis_combined' not in clusters))
output=dict(universe_count=len(universe),registry_count=len(registry),held_symbols=held,pending_symbols=pending,pending_source=pending_source,
 source_pins={str(p.relative_to(r)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [cli,regpath,pnlpath,r/'src/stock_swing/risk/correlation_cluster.py']},rows=rows,
 unknown=[r['symbol'] for r in rows if r['asset_class']=='unknown'],gaps=[r['symbol'] for r in rows if r['semiconductor_gap']],
 limits=['saved tracker != current broker holdings','no fresh or atomic pending snapshot certified','static membership does not certify detailed ETF look-through','no full PIT universe certification'])
(j/'coverage.json').write_text(json.dumps(output,indent=2));print(json.dumps({k:output[k] for k in ['universe_count','registry_count','held_symbols','pending_symbols','unknown','gaps']}))
