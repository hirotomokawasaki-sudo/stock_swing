#!/usr/bin/env python3
"""Packet-only signal diagnostic; no project imports, network, or canonical writes."""
from __future__ import annotations
import argparse,ast,collections,datetime,decimal,gzip,hashlib,json,math,random,statistics,types,zipfile
from pathlib import Path
from zoneinfo import ZoneInfo
ET=ZoneInfo('America/New_York')
def number(v):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
def timestamp(v):
    if not isinstance(v,str):return None
    try:
        d=datetime.datetime.fromisoformat(v.replace('Z','+00:00'))
        return d if d.tzinfo is not None and d.utcoffset() is not None else None
    except ValueError:return None
def stats(values):
    a=[float(x) for x in values if number(x)];c=collections.Counter(a)
    return {'n':len(a),'missing_or_nonfinite':len(values)-len(a),'unique':len(c),'min':min(a) if a else None,'max':max(a) if a else None,'at_one':sum(abs(x-1)<1e-12 for x in a),'outside_0_1':sum(not 0<=x<=1 for x in a),'largest_exact_tie':max(c.values()) if c else 0}
def time_stats(values):
    ds=[timestamp(x) for x in values];valid=[x.astimezone(datetime.timezone.utc) for x in ds if x]
    return {'aware':len(valid),'missing_naive_or_invalid':len(ds)-len(valid),'first_utc':min(valid).isoformat() if valid else None,'last_utc':max(valid).isoformat() if valid else None,'ET_dates':len({x.astimezone(ET).date() for x in valid})}
def source_function(blob,name):
    tree=ast.parse(blob.decode());nodes=[n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==name]
    assert len(nodes)==1,(name,len(nodes))
    node=nodes[0];node.decorator_list=[]
    module=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),node],type_ignores=[])
    ast.fix_missing_locations(module);namespace={};exec(compile(module,'<pinned-source:'+name+'>','exec'),namespace)
    return namespace[name]
def run(packet):
    manifest=json.loads((packet/'input_manifest.json').read_text());spec=json.loads((packet/'SPEC.json').read_text())
    assert hashlib.sha256((packet/'SPEC.json').read_bytes()).hexdigest()==manifest['spec_sha256'],'changed spec'
    with zipfile.ZipFile(packet/'inputs.zip') as z:
        names=[r['path'] for r in manifest['files']]
        assert len(names)==len(set(names))==len(z.namelist()) and set(names)==set(z.namelist()),'archive inventory mismatch'
        blobs={}
        for r in manifest['files']:
            b=z.read(r['path']);assert len(b)==r['bytes'] and hashlib.sha256(b).hexdigest()==r['sha256'],r['path'];blobs[r['path']]=b
    breakout='src/stock_swing/strategy_engine/breakout_momentum_strategy.py';event='src/stock_swing/strategy_engine/event_swing_strategy.py'
    br=source_function(blobs[breakout],'_calculate_raw_signal_score');bs=source_function(blobs[breakout],'_calculate_signal_strength')
    er=source_function(blobs[event],'_calculate_raw_signal_score');es=source_function(blobs[event],'_calculate_signal_strength')
    rank=source_function(blobs['src/stock_swing/utils/signal_prioritization.py'],'annotate_cross_sectional_percentile')
    deciles=source_function(blobs['scripts/analyze_signal_strength_decile.py'],'compute_decile_stats')
    curve=source_function(blobs['scripts/analyze_signal_strength_decile.py'],'compute_calibration_curve')
    checks=[];cases=0
    def check(name,test):
        assert test,name;checks.append(name)
    check('breakout known 10pct input has neutral strength .5',math.isclose(bs(None,.10,None),.5))
    check('raw score retains magnitude beyond normalized saturation',br(None,.4)>br(None,.3)>1 and bs(None,.4,None)==bs(None,.3,None)==1)
    check('regime adjustment distinguishes expansion and recession at unsaturated input',bs(None,.10,'expansion')>bs(None,.10,None)>bs(None,.10,'recession'))
    check('event timing prefers 2-to-5 days without selecting a profitable threshold',es(None,.10,2,None)==es(None,.10,5,None)>es(None,.10,1,None))
    momenta=[0,.04,.08,.10,.18,.20,.40];regimes=[None,'expansion','high_volatility','recession','unknown']
    for regime in regimes:
        values=[bs(None,m,regime) for m in momenta];assert values==sorted(values) and all(0<=v<=1 for v in values);cases+=len(values)
        for day in [0,1,2,5,6]:
            values=[es(None,m,day,regime) for m in momenta];assert values==sorted(values) and all(0<=v<=1 for v in values);cases+=len(values)
    check('210 source-scorer fixtures monotonic and bounded for nonnegative momentum inputs',cases==210)
    make=lambda scores:[types.SimpleNamespace(symbol=str(i),action='buy',signal_strength=s,metadata={}) for i,s in enumerate(scores)]
    signals=make([.4,.8,.8]);rank(signals);p=[x.metadata['cross_sectional_percentile'] for x in signals]
    check('equal strengths receive the same same-run percentile',p==[0,.5,.5])
    one=make([.8]);rank(one);check('single candidate percentile is convention 1 not calibrated probability',one[0].metadata['cross_sectional_percentile']==1)
    reverse=list(reversed(signals));rank(reverse);check('same-run percentile stable under permutation',{x.symbol:x.metadata['cross_sectional_percentile'] for x in reverse}=={'0':0,'1':.5,'2':.5})
    synthetic=[{'status':'closed','entry_signal_strength':.8,'pnl':float(1 if i<10 else -1)} for i in range(20)]
    a=deciles(synthetic);b=deciles(list(reversed(synthetic)))
    check('legacy deciles split identical scores into arbitrary PnL buckets',[x['net_pnl'] for x in a]!=[x['net_pnl'] for x in b] and all(x['ss_min']==x['ss_max']==.8 for x in a))
    pseudo=curve([{'decile':1,'ss_range':'.8-.8','count':20,'ss_min':.8,'ss_max':.8,'win_rate':.5}])[0]
    check('legacy calibration predicted field is score midpoint, not validated probability',pseudo['predicted']==.8 and pseudo['actual']==.5)
    decisions=[];snapshots=[];parse_fail=[]
    for path,blob in blobs.items():
        if path.startswith('data/decisions/') or path.startswith('data/feature_snapshots/'):
            try:
                d=json.loads(gzip.decompress(blob) if path.endswith('.gz') else blob)
                assert isinstance(d,dict)
                (decisions if path.startswith('data/decisions/') else snapshots).append((path,d))
            except Exception as exc:parse_fail.append({'path':path,'error':type(exc).__name__})
    decision_index=collections.defaultdict(list)
    for path,d in decisions:
        evidence=d.get('evidence') if isinstance(d.get('evidence'),dict) else {}
        key=(d.get('decision_id'),d.get('run_id') or evidence.get('run_id'),d.get('symbol'))
        if all(isinstance(x,str) and x for x in key):decision_index[key].append((path,d))
    by_strategy=collections.defaultdict(list);contract=collections.Counter();examples=[];join=collections.Counter();actions=collections.Counter();buy_runs=collections.defaultdict(list)
    snapshot_records=[]
    for path,d in snapshots:
        f=d.get('features') if isinstance(d.get('features'),dict) else {};m=f.get('metadata') if isinstance(f.get('metadata'),dict) else {};sid=str(f.get('strategy_id'))
        by_strategy[sid].append((d,f,m));key=(d.get('decision_id'),d.get('run_id'),d.get('symbol'));matches=decision_index.get(key,[])
        if len(matches)==1:
            join['exact_unique']+=1;dd=matches[0][1];actions[str(f.get('action'))+'->'+str(dd.get('action'))]+=1
            if number(f.get('signal_strength')) and number(dd.get('signal_strength')):
                join['finite_score_comparable']+=1
                if not math.isclose(f['signal_strength'],dd['signal_strength'],abs_tol=1e-10):join['score_difference']+=1
        else:join['unmatched' if not matches else 'ambiguous']+=1
        if f.get('action')=='buy':buy_runs[d.get('run_id')].append((d,f,m))
        if 'breakout' in sid and f.get('action')=='buy':
            if all(k in m for k in ['momentum','macro_regime','raw_signal_score','normalized_signal_score']) and all(number(m.get(k)) for k in ['momentum','raw_signal_score','normalized_signal_score']) and number(f.get('signal_strength')):
                expected_raw=br(None,m['momentum']);base=bs(None,m['momentum'],m['macro_regime']);final=min(base*1.2,1) if 'intraday_enhanced' in sid else base
                raw_ok=math.isclose(expected_raw,m['raw_signal_score'],rel_tol=1e-10,abs_tol=1e-10);base_ok=math.isclose(base,m['normalized_signal_score'],rel_tol=1e-10,abs_tol=1e-10);final_ok=math.isclose(final,f['signal_strength'],rel_tol=1e-10,abs_tol=1e-10)
                contract['eligible']+=1;contract['raw_match']+=raw_ok;contract['base_match']+=base_ok;contract['final_match']+=final_ok
                if not (raw_ok and base_ok and final_ok) and len(examples)<5:examples.append({'path':path,'strategy_id':sid,'raw_ok':raw_ok,'base_ok':base_ok,'final_ok':final_ok})
            else:contract['missing_required_metadata']+=1
        snapshot_records.append({'path':path,'strategy_id':sid,'action':f.get('action'),'created_at':d.get('created_at'),'run_id':d.get('run_id'),'experiment_id':d.get('experiment_id'),'has_raw_score':number(m.get('raw_signal_score')),'has_normalized_score':number(m.get('normalized_signal_score')),'has_percentile':number(m.get('cross_sectional_percentile')),'has_feature_available_at':any(m.get(k) is not None for k in ['available_at','feature_available_at','latest_bar_available_at']),'has_latest_bar_end':any(m.get(k) is not None for k in ['latest_bar_end','latest_bar_end_at','bar_window_end'])})
    rank_counts=collections.Counter();rank_examples=[]
    for run_id,rows in buy_runs.items():
        declared={m.get('cross_sectional_n') for _,_,m in rows if isinstance(m.get('cross_sectional_n'),int)};valid=[m.get('cross_sectional_percentile') for _,_,m in rows]
        if len(declared)!=1 or any(not number(x) for x in valid):rank_counts['missing_or_conflicting_contract']+=1;continue
        n=next(iter(declared));rank_counts['with_contract']+=1
        if len(rows)!=n:
            rank_counts['incomplete_or_different_candidate_population']+=1
            if len(rank_examples)<5:rank_examples.append({'run_id':run_id,'stored_buy_rows':len(rows),'declared_pre_prioritization_n':n})
            continue
        rank_counts['complete_size']+=1;signals=make([f.get('signal_strength') for _,f,_ in rows]);rank(signals)
        if all(math.isclose(s.metadata['cross_sectional_percentile'],p,abs_tol=1e-10) for s,p in zip(signals,valid)):rank_counts['percentile_reproduced_on_complete_size']+=1
        else:rank_counts['percentile_mismatch_at_complete_size']+=1
    groups={}
    for sid,rows in sorted(by_strategy.items()):
        groups[sid]={'count':len(rows),'action_counts':dict(collections.Counter(str(f.get('action')) for _,f,_ in rows)),'final_score':stats([f.get('signal_strength') for _,f,_ in rows]),'raw_score':stats([m.get('raw_signal_score') for _,_,m in rows]),'normalized_score':stats([m.get('normalized_signal_score') for _,_,m in rows]),'confidence':stats([f.get('confidence') for _,f,_ in rows]),'run_count':len({d.get('run_id') for d,_,_ in rows}),'experiment_ids':len({d.get('experiment_id') for d,_,_ in rows})}
    ledger=json.loads(blobs['data/tracking/pnl_state.json']);qids={t.get('trade_id') for t in ledger.get('quarantined_trades',[]) if t.get('trade_id')};excluded=collections.Counter();closed=[];seen=set()
    for t in ledger.get('trades',[]):
        if t.get('status')!='closed':excluded['not_closed']+=1;continue
        if t.get('trade_id') in qids:excluded['quarantine_id']+=1;continue
        if not all(number(t.get(k)) for k in ['pnl','qty','entry_price','exit_price']) or min(t.get('qty',0),t.get('entry_price',0),t.get('exit_price',0))<=0:excluded['invalid_numeric']+=1;continue
        en=timestamp(t.get('entry_time'));ex=timestamp(t.get('exit_time'))
        if en is None or ex is None or en>ex:excluded['invalid_chronology']+=1;continue
        key=(t.get('exit_broker_order_id') or t.get('broker_order_id'),t.get('trade_id'),t.get('exit_time'),t.get('qty'),t.get('exit_price'))
        if key in seen:excluded['repeated_execution_projection']+=1;continue
        seen.add(key);closed.append(t)
    tagged=[t for t in closed if number(t.get('entry_signal_strength')) and 0<=t['entry_signal_strength']<=1]
    bands=spec['fixed_score_bands'];band_rows=[];decimal_checks=0
    for lo,hi in zip(bands,bands[1:]):
        rows=[t for t in tagged if lo<=t['entry_signal_strength'] and (t['entry_signal_strength']<hi or hi==1 and t['entry_signal_strength']<=hi)]
        outcomes={}
        for bps in spec['cost_assumptions_bps_per_side']:
            vals=[t['pnl']-t['qty']*(t['entry_price']+t['exit_price'])*bps/10000 for t in rows];g=sum(x for x in vals if x>0);l=-sum(x for x in vals if x<0)
            D=decimal.Decimal;other=sum((D(str(t['pnl']))-D(str(t['qty']))*(D(str(t['entry_price']))+D(str(t['exit_price'])))*D(bps)/D(10000) for t in rows),D(0));assert abs(float(other)-sum(vals))<1e-6;decimal_checks+=1
            outcomes[str(bps)]={'n':len(rows),'pnl':sum(vals),'PF':g/l if l else None,'mean_pnl':sum(vals)/len(vals) if vals else None}
        weeks=collections.defaultdict(list)
        for t in rows:
            iso=timestamp(t['exit_time']).astimezone(ET).isocalendar();weeks[(iso.year,iso.week)].append(t['pnl']-t['qty']*(t['entry_price']+t['exit_price'])*5/10000)
        ci=None
        if len(weeks)>=2:
            rng=random.Random(7);blocks=list(weeks.values());res=[]
            for _ in range(4000):
                vals=[v for block in rng.choices(blocks,k=len(blocks)) for v in block];res.append(sum(vals)/len(vals))
            res.sort();ci=[res[99],res[3899]]
        band_rows.append({'band':[lo,hi],'count':len(rows),'cost_sensitivity':outcomes,'exit_week_clusters':len(weeks),'5bps_expectancy_cluster_interval_95':ci})
    check('fixed score bands preserve all and only tagged rows',sum(r['count'] for r in band_rows)==len(tagged))
    return {'study_id':spec['study_id'],'scope':spec['status'],'inputs':{'files':len(manifest['files']),'spec_sha256':manifest['spec_sha256'],'capture_until':manifest['captured_until_utc'],'decision_files':len(decisions),'feature_snapshots':len(snapshots),'parse_failures':parse_fail},'source_contract_checks':{'assertions_passed':len(checks),'checks':checks,'synthetic_score_cases':cases,'decimal_band_sum_checks':decimal_checks,'legacy_equal_score_decile_net_pnl_order_A':[x['net_pnl'] for x in a],'legacy_equal_score_decile_net_pnl_order_B':[x['net_pnl'] for x in b],'pseudo_probability_fixture':pseudo},'decision_inventory':{'timestamps':time_stats([d.get('decision_time') or d.get('generated_at') for _,d in decisions]),'strategies':dict(collections.Counter(str(d.get('strategy_id')) for _,d in decisions)),'actions':dict(collections.Counter(str(d.get('action')) for _,d in decisions)),'config_hashes':len({d.get('config_hash') for _,d in decisions if d.get('config_hash')}),'config_hash_present':sum(bool(d.get('config_hash')) for _,d in decisions),'run_ids_present':sum(bool(d.get('run_id') or (d.get('evidence') or {}).get('run_id')) for _,d in decisions)},'snapshot_inventory':{'timestamps':time_stats([d.get('created_at') for _,d in snapshots]),'by_strategy':groups,'feature_available_at_fields_present':sum(x['has_feature_available_at'] for x in snapshot_records),'latest_bar_end_fields_present':sum(x['has_latest_bar_end'] for x in snapshot_records)},'exact_snapshot_decision_join':{'counts':dict(join),'signal_to_decision_actions':dict(actions),'limitation':'Exact tuple correspondence is not fill/economic lineage proof; decision archive does not cover every snapshot.'},'current_breakout_score_metadata_contract':{'counts':dict(contract),'mismatch_examples':examples,'limitation':'Consistency with pinned current scorer is not historical full-strategy replay or point-in-time data qualification.'},'same_run_percentile':{'counts':dict(rank_counts),'incomplete_examples':rank_examples,'limitation':'Snapshots are after prioritization and sector exclusion; declared pre-prioritization population can be missing.'},'closed_entry_score_readiness':{'ledger_last_updated':ledger.get('last_updated'),'closed_valid_rows':len(closed),'excluded':dict(excluded),'explicit_entry_strength_valid':len(tagged),'missing_or_invalid_entry_strength':len(closed)-len(tagged),'explicit_decision_id_field':sum(bool(t.get('decision_id') or t.get('entry_decision_id')) for t in closed),'trade_id_repeats_retained_as_possible_partial_exits':len(closed)-len({t.get('trade_id') for t in closed}),'fixed_score_bands':band_rows,'limitation':'Recorded-only variable-size/variable-holding-period subset, no invented score join and no fixed-5-session signal return estimate.'},'forward_5_session_performance':{'computed':False,'reason':'No frozen joined, qualified decision-time price and mature outcome set established in this batch; existing CSV absent at capture. No online builder run.'},'qualification':{'S1_complete':False,'S2_complete':False,'S3_candidate_selected':False,'S4_challenger_test_started':False,'qualified_forward_additions':0,'F1_started':False,'production_changed':False}}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--packet',type=Path,default=Path(__file__).resolve().parent);ap.add_argument('--output',type=Path);ap.add_argument('--verify',action='store_true');args=ap.parse_args();result=run(args.packet);encoded=json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n'
    if args.verify:
        assert (args.packet/'results.json').read_text()==encoded,'saved results do not reproduce';print(json.dumps({'reproduced':True,'input_files':result['inputs']['files'],'contract_assertions':result['source_contract_checks']['assertions_passed'],'synthetic_score_cases':result['source_contract_checks']['synthetic_score_cases']}))
    elif args.output:args.output.write_text(encoded)
    else:print(encoded,end='')
if __name__=='__main__':main()
