"""Acceptance: per-arm native Entry/PF/guard -> one C11/U book -> Exit.

Synthetic prices and explicit operational assumptions are not market outcomes.
"""
from copy import deepcopy
from dataclasses import asdict, fields
from datetime import timedelta
import inspect
import json
import os
from pathlib import Path

import pytest
import native_paths as n
import path_driver as d

WORK=Path(os.environ['C11_ENTRY_WORK'])
DEP=json.loads((WORK/'DEPENDENCIES.json').read_text())
PINS=json.loads((WORK/'NATIVE_SOURCE_PINS.json').read_text())
T='2026-11-02T15:00:00+00:00'


def setup(symbols=('IBM',), cash=1_000_000.):
    module,_=d.native(DEP['native_root'],PINS)
    from stock_swing.risk.entry_filter import EntryFilterConfig
    from stock_swing.risk.allocation_config import AllocationConfig
    from stock_swing.risk.position_sizing import PositionSizingInputs
    c=d.core(); initial={}
    for arm in d.ARMS:
        initial[arm]=c.ComparisonBook(c.BookPolicy(arm,cash,quantity_scale=1. if arm=='C11' else int(arm[-3:])/100,
            atr_sizing=arm=='C11',semiconductor_cap=.3 if arm=='C11' else None,fee_bps=5.,slippage_bps=0.),
            [c.Instrument(s,'stock','breakout_momentum_v1',1. if s in {'NVDA','AMD'} else 0.) for s in symbols]).dumps()
    policy=dict(generation=dict(min_momentum=.05,min_signal_strength=.5),
        risk=dict(min_signal_strength=.5,min_confidence=.4,max_position_size=400),
        filter=asdict(EntryFilterConfig(min_trades_for_gate=1)),
        sizing=dict(market_regime='neutral',max_risk_per_trade_pct=.005,max_position_notional_pct=.08,
            default_stop_pct=.05,risk_per_share=None,max_sector_exposure_pct=.55,exposure_cap_override=None),
        allocation=asdict(AllocationConfig(stock_new_buy_multiplier=.5,etf_new_buy_multiplier=.7)),
        guard=dict(paper_warning_only=False,rules={'test-api':dict(metric='api_error_rate_pct',
            operator='>=',threshold=10.,action='halt',enabled=True)}),
        confidence_risk_budget_fix_enabled=False,quarantined_symbols=['ANET'])
    exit_policy={k:deepcopy(v.default) for k,v in inspect.signature(module.SimpleExitV2Strategy).parameters.items()}
    exit_policy['min_hold_days_enabled']=False
    return initial,policy,exit_policy


def frame(symbols=('IBM',), when=T, price=100., momentum=.14, day_start=True):
    at=d.aware(when)
    features=[dict(feature_name='price_momentum',symbol=s,computed_at=when,available_at=when,
        values=dict(momentum=momentum,trend='bullish',bars_used=15,latest_close=price,atr=10.),
        metadata={},quality_flags=[],source_ref='synthetic-feature') for s in symbols]
    bars={s:[dict(symbol=s,event_type='bar_daily',event_time=(at-timedelta(days=15-i)).isoformat(),
        ingested_at=when,payload=dict(volume=2_000_000,high=price*1.02,low=price*.98,close=price)) for i in range(15)] for s in symbols}
    op=dict(role='explicit_model_assumptions',source_ref='synthetic-not-measured',as_of=when,available_at=when,
        metrics=dict(stale_price_event_count=0,broker_tracker_mismatch_count=0,api_error_rate_pct=0.,
            order_rejection_rate_pct=0.,token_spend_spike_pct=0.),
        breaker=dict(status='ok',action='allow',last_evaluated_at=when),dynamic_exposure_cap=.75)
    return dict(at=when,quotes={s:dict(bid=price-.1,ask=price+.1,as_of=when,available_at=when) for s in symbols},
        features=features,bars=bars,close=dict(session_date=when[:10],close_at=when,calendar_source_ref='synthetic'),
        day_start=day_start,operational={a:deepcopy(op) for a in d.ARMS},exit_only=False,source_ref='synthetic-frame',filter_policy=None)


def run(initial,p,e,frames):
    return n.run(initial,frames,native_source_root=DEP['native_root'],native_pins=PINS,
        entry_policy=p,exit_policy=e,guard_source=WORK/'guard_port.py',guard_sha256=DEP['guard_port_sha256'],
        source_ref='engineering-fixture',execution_model=n.MODEL)


def test_ac_native_entry_to_exact_decimal_p0_grid_and_single_cost():
    initial,p,e=setup();v=run(initial,p,e,[frame()])
    bs={a:d.core().ComparisonBook.loads(v['ending_journals'][a]) for a in ['C11','U_grid_029','U_grid_100']}
    fills={x['arm']:x for x in v['audit'] if x['kind']=='modeled_fill'}
    nominal=fills['U_grid_100']['nominal_qty']
    assert fills['C11']['qty']==min(nominal,150),'P0 once after native nominal sizing'
    assert fills['U_grid_029']['qty']==int(__import__('decimal').Decimal(nominal)*__import__('decimal').Decimal('.29'))
    q=fills['C11']['qty'];b=bs['C11']
    assert b.cash==pytest.approx(1_000_000-q*100.1*1.0005),'ask and fee charged once'
    assert b._equity(d.aware(T),fresh=True)==pytest.approx(1_000_000-q*.1-q*100.1*.0005),'mid NAV includes half spread'
    assert v['native_entry_components_connected'] and v['market_PnL'] is None and v['formal_U'] is None
    assert all(not json.loads(x)['payload']['events'] for x in initial.values()),'caller journals unchanged'


def test_ac_own_native_exit_updates_only_own_pf_and_next_gate():
    initial,p,e=setup();a=frame();a['operational']['U_grid_100']['breaker'].update(status='halted',action='halt')
    b=frame(when='2026-11-03T15:00:00+00:00',price=85.)
    v=run(initial,p,e,[a,b])
    assert len(v['own_histories']['C11'])==1 and len(v['own_histories']['U_grid_100'])==0,'closed history is independent'
    decisions=[x for x in v['audit'] if x['frame']==1 and x['kind']=='entry_components']
    assert next(x for x in decisions if x['arm']=='C11')['reason']=='native_entry_filter','own loss activates PF'
    assert next(x for x in decisions if x['arm']=='U_grid_100')['reason']=='native_prebuy_guard','HALT must remain latched'
    assert any(x['kind']=='native_exit' and x['arm']=='C11' for x in v['audit']),'loss protection must run before entry'


def test_ac_reduce_size_caps_native_nominal_not_double_atr_or_multiplier():
    initial,p,e=setup();a=frame();a['operational']['U_grid_100']['dynamic_exposure_cap']=.01
    v=run(initial,p,e,[a]);rows=[x for x in v['audit'] if x['kind']=='entry_components']
    assert next(x for x in rows if x['arm']=='U_grid_100')['nominal_qty']<next(x for x in rows if x['arm']=='C11')['nominal_qty']
    p['guard']['rules']['test-api'].update(action='reduce_size',threshold=0.)
    v=run(initial,p,e,[frame()]);row=next(x for x in v['audit'] if x['kind']=='entry_components')
    assert row['guard']['effective_exposure_cap']==pytest.approx(.375),'native reduce_size halves cap once'


@pytest.mark.parametrize('case',['no_operational','no_anchor','missing_quote','quarantine','exit_only','low_volume','low_ADR'])
def test_ac_input_gaps_and_native_gate_fail_closed(case):
    initial,p,e=setup();a=frame()
    if case=='no_operational':a['operational']={}
    elif case=='no_anchor':a['day_start']=False
    elif case=='missing_quote':a['quotes']={}
    elif case=='quarantine':p['quarantined_symbols'].append('IBM')
    elif case=='exit_only':a['exit_only']=True
    elif case=='low_volume':
        for bar in a['bars']['IBM']:bar['payload']['volume']=1
    elif case=='low_ADR':
        for bar in a['bars']['IBM']:bar['payload'].update(high=100.,low=100.)
    v=run(initial,p,e,[a]);assert not any(x['kind']=='modeled_fill' for x in v['audit']),case
    assert all(not d.core().ComparisonBook.loads(x).lots for x in v['ending_journals'].values()),case


@pytest.mark.parametrize('case',['future_quote','crossed_quote','stale_quote','future_feature','duplicate_feature','missing_feature','future_bar','no_flag','atr_double','PF_bypass','missing_arm','nonempty_seed','reset_day','guard_source'])
def test_ac_corrupt_or_ambiguous_inputs_refused(case):
    initial,p,e=setup();a=frame();frames=[a]
    if case=='future_quote':a['quotes']['IBM']['available_at']='2026-11-03T15:00:00+00:00'
    elif case=='crossed_quote':a['quotes']['IBM']['bid']=102.
    elif case=='stale_quote':a['quotes']['IBM']['as_of']='2026-11-02T14:59:00+00:00'
    elif case=='future_feature':a['features'][0]['available_at']='2026-11-03T15:00:00+00:00'
    elif case=='duplicate_feature':a['features'].append(deepcopy(a['features'][0]))
    elif case=='missing_feature':a['features']=[]
    elif case=='future_bar':a['bars']['IBM'][0]['ingested_at']='2026-11-03T15:00:00+00:00'
    elif case=='no_flag':p.pop('confidence_risk_budget_fix_enabled')
    elif case=='atr_double':p['sizing']['risk_per_share']=20.
    elif case=='PF_bypass':p['filter']['disabled']=True
    elif case=='missing_arm':initial.pop('U_grid_001')
    elif case=='nonempty_seed':initial['C11']=run(initial,p,e,[frame()])['ending_journals']['C11']
    elif case=='reset_day':frames.append(frame(when='2026-11-02T15:01:00+00:00'))
    elif case=='guard_source':
        old=DEP['guard_port_sha256'];DEP['guard_port_sha256']='0'*64
        try:
            with pytest.raises(ValueError):run(initial,p,e,frames)
        finally:DEP['guard_port_sha256']=old
        return
    with pytest.raises((ValueError,KeyError,TypeError)):run(initial,p,e,frames)


def test_ac_prefix_future_invariance_and_no_held_symbol_discard():
    initial,p,e=setup();a=frame();b=frame(when='2026-11-03T15:00:00+00:00',price=110.)
    prefix=run(initial,p,e,[a]);full=run(initial,p,e,[a,b])
    assert all(prefix['checkpoints'][arm][0]==full['checkpoints'][arm][0] for arm in d.ARMS)
    b['quotes']={}
    with pytest.raises(ValueError,match='held-symbol'):run(initial,p,e,[a,b])


def test_ac_empty_calendar_does_not_invent_close_or_market_qualification():
    initial,p,e=setup();a=frame();a['close']=None
    v=run(initial,p,e,[a])
    assert v['sessions']==[] and all(x==[] for x in v['checkpoints'].values())
    assert v['capacity_and_settlement_qualified'] is False and v['economic_qualified'] is False


def test_captured_integer_guard_action_maps_to_same_native_rule_without_mutating_source():
    """Regression 2026-11-26: SAVED_MODELED_EXECUTION_1 failed at GuardAction['3']."""
    initial,p,e=setup();a=frame();before=deepcopy(p)
    expected=run(initial,p,e,[a])
    p['guard']['rules']['test-api']['action']=5
    got=run(initial,p,e,[a])
    assert got['ending_journals']==expected['ending_journals'],'captured enum value and YAML name must agree'
    assert p['guard']['rules']['test-api']['action']==5 and before['guard']['rules']['test-api']['action']=='halt'


@pytest.mark.parametrize('action',[True,99,'unknown',None])
def test_captured_unknown_guard_action_never_defaults_to_allow(action):
    initial,p,e=setup();p['guard']['rules']['test-api']['action']=action
    with pytest.raises((ValueError,KeyError)):run(initial,p,e,[frame()])


def test_actual_source_filter_exceptions_are_explicit_not_silently_removed():
    initial,p,e=setup();a=frame();a['filter_policy']=deepcopy(p['filter'])
    a['filter_policy']['pf_gate_skip_symbols']=['AMD','HPE']
    v=run(initial,p,e,[a]);row=next(x for x in v['audit'] if x['kind']=='entry_components')
    assert row['filter_policy_sha256']==__import__('hashlib').sha256(d.encode(a['filter_policy']).encode()).hexdigest()
    assert any(x['kind']=='modeled_fill' for x in v['audit']),'unchanged source config remains usable'


def test_own_pf_loss_does_not_block_arm_without_that_close():
    initial,p,e=setup();a=frame();a['operational'].pop('U_grid_100')
    b=frame(when='2026-11-03T15:00:00+00:00',price=85.)
    v=run(initial,p,e,[a,b])
    rows=[x for x in v['audit'] if x['frame']==1 and x['kind']=='entry_components']
    assert next(x for x in rows if x['arm']=='C11')['reason']=='native_entry_filter'
    assert next(x for x in rows if x['arm']=='U_grid_100')['status']=='nominal_ready'
    assert len(v['own_histories']['C11'])==1 and v['own_histories']['U_grid_100']==[]


def test_missing_new_entry_context_does_not_prevent_native_risk_reducing_exit():
    initial,p,e=setup();a=frame();b=frame(when='2026-11-03T15:00:00+00:00',price=85.)
    b['operational']={};b['day_start']=False
    v=run(initial,p,e,[a,b])
    assert any(x['frame']==1 and x['kind']=='native_exit' for x in v['audit'])
    assert not any(x['frame']==1 and x['kind']=='modeled_fill' for x in v['audit'])


def test_native_nominal_is_clipped_once_by_cost_inclusive_book_cash():
    initial,p,e=setup(cash=1000.);a=frame(price=99.9,momentum=.20)
    p['sizing'].update(max_risk_per_trade_pct=1.,max_position_notional_pct=1.,max_sector_exposure_pct=1.)
    p['allocation']['stock_new_buy_multiplier']=1.
    for x in a['operational'].values():x['dynamic_exposure_cap']=1.
    v=run(initial,p,e,[a]);f=next(x for x in v['audit'] if x['kind']=='modeled_fill' and x['arm']=='U_grid_100')
    assert (f['nominal_qty'],f['qty'])==(10,9),'cost-inclusive affordability must reduce native quantity once'
    b=d.core().ComparisonBook.loads(v['ending_journals']['U_grid_100'])
    assert b.cash==pytest.approx(99.55) and b.fees==pytest.approx(.45)


def test_unknown_etf_fraction_blocks_only_that_buy_without_removing_universe():
    initial,p,e=setup(('IBM','SOXX'));c=d.core()
    for arm,text in list(initial.items()):
        b=c.ComparisonBook.loads(text)
        initial[arm]=c.ComparisonBook(b.policy,[c.Instrument('IBM','stock','breakout_momentum_v1',0.),
            c.Instrument('SOXX','etf','breakout_momentum_v1_etf',None)]).dumps()
    v=run(initial,p,e,[frame(('IBM','SOXX'))])
    assert any(x.get('reason')=='unknown_look_through_fraction' and x['symbol']=='SOXX' for x in v['audit'])
    assert any(x['kind']=='modeled_fill' and x['symbol']=='IBM' for x in v['audit'])
    assert all(set(d.core().ComparisonBook.loads(text).instruments)=={'IBM','SOXX'} for text in v['ending_journals'].values())


def test_missing_pinned_guard_file_refuses_before_any_accounting():
    initial,p,e=setup()
    with pytest.raises(OSError):
        n.run(initial,[frame()],native_source_root=DEP['native_root'],native_pins=PINS,
            entry_policy=p,exit_policy=e,guard_source=WORK/'nonexistent-guard.py',guard_sha256=DEP['guard_port_sha256'],
            source_ref='test',execution_model=n.MODEL)
    assert all(not json.loads(text)['payload']['events'] for text in initial.values())


def test_native_generated_paths_reach_existing_calibration_in_separate_process():
    import subprocess,sys
    initial,p,e=setup();v=run(initial,p,e,[frame(),
        frame(when='2026-11-03T15:00:00+00:00',price=110.),frame(when='2026-11-04T15:00:00+00:00',price=104.)])
    code='import sys,json;import bridge;v=json.load(sys.stdin);r=bridge.connect(v["checkpoints"],sessions=v["sessions"],evaluation_first_session="2026-11-05",source_ref="native engineering fixture");print(json.dumps({"formal_U":r["formal_selected_scale"],"economic":r["qualification"]["economic_qualified"],"all_zero":r["all_zero_exposure"]}))'
    x=subprocess.run([sys.executable,'-B','-c',code],input=json.dumps(v),capture_output=True,text=True,timeout=20)
    assert x.returncode==0,x.stderr
    assert json.loads(x.stdout)==dict(formal_U=None,economic=False,all_zero=False)


def test_c11_projected_semiconductor_cap_remains_owned_by_book():
    symbols=('NVDA','AMD','AVGO','AMAT','LRCX','KLAC');initial,p,e=setup(symbols);c=d.core()
    for arm,text in list(initial.items()):
        b=c.ComparisonBook.loads(text)
        initial[arm]=c.ComparisonBook(b.policy,[c.Instrument(s,'stock','breakout_momentum_v1',1.) for s in symbols]).dumps()
    a=frame(symbols,momentum=.20)
    for f in a['features']:f['values']['atr']=.1
    p['sizing'].update(max_risk_per_trade_pct=.05,max_position_notional_pct=.5,max_sector_exposure_pct=.9)
    p['allocation']['stock_new_buy_multiplier']=1.
    for x in a['operational'].values():x['dynamic_exposure_cap']=.95
    v=run(initial,p,e,[a])
    assert any(x['kind']=='cap_rejected' and x['arm']=='C11' for x in v['audit']),'fixture must actually reach book cap'
    b=c.ComparisonBook.loads(v['ending_journals']['C11']);s=b.snapshot()
    assert sum(x['qty']*100. for x in b.lots.values())<=.3*s['equity']+1e-8


@pytest.mark.parametrize('case',['bad_json','false_quote','NaN','missing_bid','bad_operational_role'])
def test_public_run_rejects_corrupt_boundary_input_without_changing_initial(case):
    initial,p,e=setup();a=frame();before=deepcopy(initial)
    if case=='bad_json':initial['C11']='{'
    elif case=='false_quote':a['quotes']['IBM']['bid']=False
    elif case=='NaN':a['quotes']['IBM']['bid']=float('nan')
    elif case=='missing_bid':a['quotes']['IBM'].pop('bid')
    elif case=='bad_operational_role':a['operational']['C11']['role']='measured_by_label_only'
    submitted=deepcopy(initial)
    with pytest.raises((ValueError,KeyError,TypeError)):run(initial,p,e,[a])
    assert initial==submitted,'rejected run must not mutate caller inputs'


def test_public_command_is_idempotent_and_refuses_conflicting_output(tmp_path):
    import run_research_paths as cli
    initial,p,e=setup();f=tmp_path/'input.json';out=tmp_path/'result.json'
    f.write_text(json.dumps(dict(initial=initial,frames=[frame()],entry_policy=p,exit_policy=e)))
    args=['--inputs',str(f),'--native-root',DEP['native_root'],'--native-pins',str(WORK/'NATIVE_SOURCE_PINS.json'),
        '--guard-source',str(WORK/'guard_port.py'),'--guard-sha256',DEP['guard_port_sha256'],
        '--source-ref','synthetic-command-test','--context-policy','explicit-engineering','--output',str(out)]
    result=cli.main(args);saved=out.read_bytes();assert result['independent_arms']==101
    cli.main(args);assert out.read_bytes()==saved,'identical retry must not generate a second path'
    # Change the explicit input source, not the prior published artifact.
    data=json.loads(f.read_text());data['frames'][0]['source_ref']='changed-input';f.write_text(json.dumps(data))
    with pytest.raises(Exception,match='conflict'):cli.main(args)
    assert out.read_bytes()==saved


def test_public_command_missing_corrupt_input_and_strict_context_do_not_create_false_results(tmp_path):
    import run_research_paths as cli
    f=tmp_path/'input.json';out=tmp_path/'result.json'
    args=['--inputs',str(f),'--native-root',DEP['native_root'],'--native-pins',str(WORK/'NATIVE_SOURCE_PINS.json'),
        '--guard-source',str(WORK/'guard_port.py'),'--guard-sha256',DEP['guard_port_sha256'],
        '--source-ref','synthetic-command-test','--context-policy','require-observed-context','--output',str(out)]
    with pytest.raises(OSError):cli.main(args)
    assert not out.exists()
    f.write_text('{')
    with pytest.raises(ValueError):cli.main(args)
    assert not out.exists()
    initial,p,e=setup();f.write_text(json.dumps(dict(initial=initial,frames=[frame()],entry_policy=p,exit_policy=e)))
    cli.main(args);v=json.loads(out.read_text())
    assert v['excluded_model_contexts']==101 and v['model_accounting'] is None
    assert v['audit_kind_counts'].get('modeled_fill',0)==0 and v['market_PnL'] is None
