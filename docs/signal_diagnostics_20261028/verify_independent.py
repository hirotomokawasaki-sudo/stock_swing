"""Independent Decimal/count oracle; consumes only the frozen packet."""
from pathlib import Path
import collections,decimal,gzip,hashlib,json,math,zipfile
D=decimal.Decimal

def verify(packet):
    saved=json.loads((packet/'results.json').read_text());manifest=json.loads((packet/'input_manifest.json').read_text())
    assert hashlib.sha256((packet/'SPEC.json').read_bytes()).hexdigest()==manifest['spec_sha256']
    snapshots=[];decisions=[];ledger=None
    with zipfile.ZipFile(packet/'inputs.zip') as archive:
        assert sorted(archive.namelist())==sorted(row['path'] for row in manifest['files'])
        for row in manifest['files']:
            blob=archive.read(row['path']);assert hashlib.sha256(blob).hexdigest()==row['sha256'] and len(blob)==row['bytes']
            name=row['path']
            if name.startswith('data/feature_snapshots/'):
                snapshots.append(json.loads(gzip.decompress(blob) if name.endswith('.gz') else blob))
            elif name.startswith('data/decisions/'):decisions.append(json.loads(blob))
            elif name=='data/tracking/pnl_state.json':ledger=json.loads(blob)
    assert len(snapshots)==saved['inputs']['feature_snapshots'] and len(decisions)==saved['inputs']['decision_files']
    score_checks=0
    for sid,group in saved['snapshot_inventory']['by_strategy'].items():
        items=[s['features'] for s in snapshots if s['features'].get('strategy_id')==sid]
        assert len(items)==group['count']
        assert sum(abs(x['signal_strength']-1)<1e-12 for x in items)==group['final_score']['at_one'];score_checks+=1
    oracle_score_cases=0
    for snap in snapshots:
        f=snap['features'];m=f.get('metadata') or {}
        if 'breakout' not in f.get('strategy_id','') or f.get('action')!='buy':continue
        if not all(k in m for k in ['momentum','macro_regime','raw_signal_score','normalized_signal_score']):continue
        raw=D(str(m['momentum']))/D('.20');base=min(raw,D(1))
        factor={'expansion':D('1.1'),'high_volatility':D('.9'),'recession':D('.7')}.get(m['macro_regime'],D(1));base=min(base*factor,D(1));final=min(base*D('1.2'),D(1)) if 'intraday_enhanced' in f['strategy_id'] else base
        for actual,expected in [(m['raw_signal_score'],raw),(m['normalized_signal_score'],base),(f['signal_strength'],final)]:assert abs(D(str(actual))-expected)<D('0.0000000001')
        oracle_score_cases+=1
    assert oracle_score_cases==saved['current_breakout_score_metadata_contract']['counts']['eligible']
    qids={x.get('trade_id') for x in ledger.get('quarantined_trades',[])}
    closed=[t for t in ledger['trades'] if t.get('status')=='closed' and t.get('trade_id') not in qids and isinstance(t.get('pnl'),(float,int)) and math.isfinite(t['pnl'])]
    assert len(closed)==saved['closed_entry_score_readiness']['closed_valid_rows']
    tagged=[t for t in closed if isinstance(t.get('entry_signal_strength'),(int,float)) and math.isfinite(t['entry_signal_strength']) and 0<=t['entry_signal_strength']<=1]
    assert len(tagged)==saved['closed_entry_score_readiness']['explicit_entry_strength_valid']
    cells=0
    for band in saved['closed_entry_score_readiness']['fixed_score_bands']:
        lo,hi=map(lambda x:D(str(x)),band['band']);rows=[t for t in tagged if D(str(t['entry_signal_strength']))>=lo and (D(str(t['entry_signal_strength']))<hi or hi==1 and D(str(t['entry_signal_strength']))<=hi)]
        assert len(rows)==band['count']
        for cost,res in band['cost_sensitivity'].items():
            outcomes=[D(str(t['pnl']))-D(str(t['qty']))*(D(str(t['entry_price']))+D(str(t['exit_price'])))*D(cost)/D(10000) for t in rows];total=sum(outcomes,D(0));gain=sum((v for v in outcomes if v>0),D(0));loss=-sum((v for v in outcomes if v<0),D(0))
            assert abs(total-D(str(res['pnl'])))<D('.000001')
            if loss:assert abs(gain/loss-D(str(res['PF'])))<D('.000000000001')
            else:assert res['PF'] is None
            cells+=1
    return {'independent_count_oracle':True,'source_score_decimal_oracle_rows':oracle_score_cases,'strategy_score_count_groups':score_checks,'outcome_decimal_cells':cells,'closed_rows':len(closed),'score_tagged_rows':len(tagged)}

if __name__=='__main__':print(json.dumps(verify(Path(__file__).resolve().parent),sort_keys=True))
