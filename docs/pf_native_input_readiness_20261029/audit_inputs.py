"""Count-only PF input qualification. No return/PF optimization or outcome study."""
from pathlib import Path,PurePosixPath
from datetime import datetime,timezone
from collections import Counter
import argparse,hashlib,json,math,zipfile,tempfile,shutil,sys,gzip
from decimal import Decimal

def clock(value):
    try:
        x=datetime.fromisoformat(value.replace('Z','+00:00'))
        return x.astimezone(timezone.utc) if x.tzinfo is not None else None
    except (ValueError,TypeError,AttributeError):return None

def num(x):return type(x) in {int,float} and math.isfinite(x)
def audit_seed(raw,rows,freeze):
    counts=Counter();keys=Counter();foreign={x.get('trade_id') for x in raw.get('quarantined_trades',[])}
    for t in rows:
        counts['all_consumed_rows']+=1;counts['status_'+str(t.get('status'))]+=1
        if t.get('status')!='closed':continue
        entry,exit=clock(t.get('entry_time')),clock(t.get('exit_time'))
        if entry is None or exit is None:counts['closed_missing_or_naive_clock']+=1
        elif entry>exit:counts['closed_reversed_time']+=1
        if exit is not None and exit>freeze:counts['closed_after_capture']+=1
        if clock(t.get('known_at')) is None:counts['closed_missing_leg_known_at']+=1
        if not all(num(t.get(k)) for k in ['qty','entry_price','exit_price','pnl']) or any(t.get(k,0)<=0 for k in ['qty','entry_price','exit_price']):counts['closed_bad_numeric']+=1
        else:
            residual=abs((Decimal(str(t['exit_price']))-Decimal(str(t['entry_price'])))*Decimal(str(t['qty']))-Decimal(str(t['pnl'])))
            if residual>Decimal('.02'):
                counts['closed_strict_2cent_formula_disagreement']+=1
                # Diagnostic bound only. No tolerance change, correction or
                # certification: original execution prices still required.
                bound=Decimal(str(t['qty']))*Decimal('.01')+Decimal('.005')
                counts['formula_disagreement_possible_2dp_rounding' if residual<=bound else 'formula_disagreement_exceeds_2dp_rounding_bound']+=1
        if t.get('trade_id') in foreign:counts['closed_id_in_separate_quarantine']+=1
        leg=t.get('execution_leg_id')
        if isinstance(leg,str) and leg:keys[leg]+=1
        else:counts['closed_missing_execution_leg_id']+=1
    counts['duplicate_nonempty_leg_ids']=sum(n-1 for n in keys.values() if n>1)
    counts['separate_quarantine_rows']=len(raw.get('quarantined_trades',[]))
    counts['inline_quarantine_matching_separate_id']=sum(t.get('status')=='quarantined' and t.get('trade_id') in foreign for t in rows)
    return dict(sorted(counts.items()))

def run(root,source):
    root=Path(root);pins=json.loads((root/'PINS.json').read_text())
    for name,p in pins.items():
        f=root/name
        if f.is_symlink() or len(f.read_bytes())!=p['bytes'] or hashlib.sha256(f.read_bytes()).hexdigest()!=p['sha256']:raise ValueError('input drift '+name)
    spec=json.loads((root/'SPEC.json').read_text());contract=json.loads((root/'execution_spec.json').read_text())
    manifest=json.loads((root/'archive_manifest.json').read_text());expected={x['path']:x for x in manifest['files']}
    decisions=[];snapcounts=Counter();counts=Counter();run_ids=set();clock_dates=[]
    with zipfile.ZipFile(root/'archive.zip') as z:
        names=z.namelist()
        if len(names)!=len(set(names)) or set(names)!=set(expected):raise ValueError('archive inventory')
        for name in names:
            path=PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts:raise ValueError('unsafe archive path')
            data=z.read(name)
            if hashlib.sha256(data).hexdigest()!=expected[name]['sha256'] or len(data)!=expected[name]['bytes']:raise ValueError('archive drift')
            if name.startswith('data/decisions/'):
                d=json.loads(data);decisions.append(d);counts['action_'+str(d.get('action'))]+=1
                ev=d.get('evidence') or {};run=d.get('run_id') or ev.get('run_id')
                if isinstance(run,str) and run:run_ids.add(run)
                else:counts['missing_run_id']+=1
                explicit=d.get('decision_time');t=clock(explicit if explicit else d.get('generated_at'))
                counts['clock_explicit' if explicit else 'clock_generated_proxy']+=1
                if t:clock_dates.append(t.date().isoformat())
                for field in ['candidate_status','no_signal','stage_trace','symbol_slot_id']:
                    if field in d or field in ev:counts['has_'+field]+=1
                if isinstance(ev.get('pf_history_receipt'),dict):counts['has_pf_history_receipt']+=1
            elif name.startswith('data/feature_snapshots/'):
                doc=json.loads(gzip.decompress(data) if name.endswith('.gz') else data)
                snapcounts['all']+=1
                for field in ['available_at','known_at','source_id','adjustment_basis','corporate_actions']:
                    if field in doc:snapcounts['has_'+field]+=1
    raw=json.loads((root/'seed.json').read_text())
    # Real loader, independent disposable copy. Never let migration touch source.
    sys.path.insert(0,str(Path(source).resolve()/'src'))
    from stock_swing.tracking.pnl_tracker import PnLTracker
    assert Path(sys.modules[PnLTracker.__module__].__file__).resolve().is_relative_to(Path(source).resolve())
    tmp=Path(tempfile.mkdtemp(prefix='pf-seed-audit-')).resolve();f=tmp/'data/tracking/pnl_state.json';f.parent.mkdir(parents=True);shutil.copy2(root/'seed.json',f)
    before=f.read_bytes();rows=PnLTracker(tmp).state.trades
    native_loader=dict(rows=len(rows),raw_ordered_trades_equal=rows==raw['trades'],copy_input_bytes_unchanged=f.read_bytes()==before)
    if not native_loader['copy_input_bytes_unchanged']:raise ValueError('loader unexpectedly wrote seed fixture')
    seed=audit_seed(raw,rows,clock(spec['frozen_at']))
    pricecounts=Counter();dates=[];universe=set(contract['population']['universe']);window=contract['population']['window']['sessions'];future=[]
    for name in sorted(pins):
        if not name.startswith('prices/'):continue
        symbol=Path(name).stem;bars=json.loads((root/name).read_text());pricecounts['symbols']+=1
        if symbol in universe:pricecounts['universe_symbols_with_any_cache']+=1
        for day,bar in bars.items():
            pricecounts['daily_rows']+=1;dates.append(day)
            valid=all(num(bar.get(k)) for k in ['open','high','low','close','volume']) and min(bar.get(k,0) for k in ['open','high','low','close'])>0 and bar.get('volume',-1)>=0 and bar['low']<=min(bar['open'],bar['close'])<=max(bar['open'],bar['close'])<=bar['high']
            if not valid:pricecounts['invalid_OHLCV_rows']+=1
            for field in ['available_at','known_at','adjustment_basis','corporate_actions']:
                if field not in bar:pricecounts['missing_'+field]+=1
            if symbol in universe and day in window:future.append([symbol,day])
    planned=contract['population']['planned_checks']
    result=dict(spec_id=spec['id'],profit_trials=0,archive_files=len(expected),decision_rows=len(decisions),decision_counts=dict(sorted(counts.items())),historical_distinct_recorded_run_ids=len(run_ids),historical_first_date=min(clock_dates),historical_last_date=max(clock_dates),snapshots=dict(sorted(snapcounts.items())),
        denominator=dict(planned_future_checks=planned,observed_future_decision_rows=sum(d.get('generated_at','')[:10] in window for d in decisions),qualified_future_checks=0,missing_or_not_yet_observed_checks=planned,no_signal_records_identifiable=counts['has_no_signal'],full_historical_denominator_qualified=False,reason='decision-only archive is not all configured symbol-slots; historical run universe and explicit no-signal absent'),
        seed=dict(counts=seed,loader=native_loader,prewindow_snapshot_known_before_first_session=clock(spec['frozen_at'])<clock(window[0]+'T14:35:00+00:00'),economic_qualified=False,role='policy-memory seed only, never opening NAV; per-leg historical availability and canonical execution/CA qualification not established'),
        prices=dict(counts=dict(sorted(pricecounts.items())),first_date=min(dates),last_date=max(dates),prospective_symbol_session_rows=len(future),qualified_bidask_quotes=0,qualified_immediate_prior_minute_volumes=0,qualified_corporate_action_paths=0,qualified_for_execution=False),storage=json.loads((root/'STORAGE_COUNTS.json').read_text()),
        readiness=dict(complete_candidate_stream=False,qualified_asof_prices=False,seed_economically_qualified=False,AB_profit_batches=0,F1_started=False),rule='Future Nov2-5 absence on Oct29 is not a capture failure. Legacy data remains exploratory; no PnL/PF outcomes calculated.')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',default=str(Path(__file__).resolve().parent/'audit_inputs'));p.add_argument('--source',default=str(Path(__file__).resolve().parent/'candidate'));p.add_argument('--output',required=True);a=p.parse_args();r=run(a.root,a.source);Path(a.output).write_text(json.dumps(r,sort_keys=True,indent=2)+'\n');print(json.dumps(dict(decisions=r['decision_rows'],seed=r['seed']['counts'],prices=r['prices']['counts'],denominator=r['denominator'])))
