"""Post-migration consumers must not erase lineage or revive stale economics."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tests.unit.test_r22_history_migration import fixture_plan
from stock_swing.tracking.history_migration import apply_migration
from stock_swing.tracking.ledger_transaction import FILES, LedgerConflict

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def migrated(tmp_path):
    _, _, plan = fixture_plan(tmp_path)
    apply_migration(tmp_path, plan)
    return tmp_path


def test_csv_does_not_override_corrected_ledger(migrated):
    from console.services.performance_breakdown_service import _load_trades
    (migrated/'exports').mkdir()
    (migrated/'exports/closed_trades.csv').write_text('symbol,pnl\nAMAT,999999\n')
    rows, warnings = _load_trades(migrated)
    state = json.loads((migrated/'data/tracking/pnl_state.json').read_bytes())
    assert sum(r['pnl'] for r in rows) == pytest.approx(sum(r['pnl'] for r in state['trades']))
    assert any('historical_correction_unqualified' in w for w in warnings)


def test_snapshot_enrichment_preserves_original_observation(migrated):
    from console.services.dashboard_service import DashboardService
    state = json.loads((migrated/'data/tracking/pnl_state.json').read_bytes())
    service = DashboardService.__new__(DashboardService)
    result = service._enrich_daily_snapshots(state['daily_snapshots'], state['trades'], {'available':True,'summary':{'gross_exposure':999}})
    assert result == state['daily_snapshots']


def test_read_detects_event_only_revision_damage(migrated):
    from console.services.dashboard_service import DashboardService
    path = migrated/'data/tracking/pnl_state.json'
    DashboardService._load_json_cached(path)
    events = migrated/'data/tracking/trade_events.jsonl'
    lines = events.read_bytes().splitlines(keepends=True)
    events.write_bytes(b''.join(line for line in lines if json.loads(line)['event_type']!='history_supersession'))
    with pytest.raises(LedgerConflict):
        DashboardService._load_json_cached(path)


def test_old_formatter_refuses_before_backup_or_write(migrated):
    (migrated/'scripts').mkdir()
    script = migrated/'scripts/fix_pnl_state_format.py'
    shutil.copy2(ROOT/'scripts/fix_pnl_state_format.py', script)
    before = {n:(migrated/'data/tracking'/n).read_bytes() for n in FILES}
    result = subprocess.run([sys.executable,str(script)],cwd=migrated,env={**os.environ,'PYTHONPATH':str(ROOT/'src')},capture_output=True,text=True)
    assert result.returncode != 0
    assert 'legacy maintenance blocked' in result.stderr
    assert before == {n:(migrated/'data/tracking'/n).read_bytes() for n in FILES}
    assert not (migrated/'data/tracking/pnl_state_before_fix.json').exists()


GUARDED_SCRIPTS = '''adjust_individual_pnl backfill_asset_class backfill_daily_snapshots
backfill_entry_signal_strength backfill_open_position_count backfill_open_trade_peak_prices
cleanup_alpaca_anomalies_20260511 cleanup_dell_anomaly_20260511 cleanup_high_return_trades_20260511
correct_anomalous_prices_with_market_data fetch_and_fix_pnl fix_pnl_tracking init_peak_prices
migrate_quarantine_invalid_trades rebuild_pnl_source_of_truth rebuild_pnl_state_from_broker
recover_exit_reasons rf8b_recover_attribution sync_pnl_with_broker verify_rebuild_integrity
cleanup_anomalous_trades merge_pnl_data rebuild_pnl_from_orders'''.split()


@pytest.mark.parametrize('name', GUARDED_SCRIPTS)
def test_legacy_programs_refuse_migrated_copy_without_io(migrated, name):
    (migrated/'scripts').mkdir()
    script = migrated/'scripts'/f'{name}.py'
    shutil.copy2(ROOT/'scripts'/f'{name}.py', script)
    before = {p.relative_to(migrated):p.read_bytes() for p in migrated.rglob('*') if p.is_file()}
    result = subprocess.run([sys.executable,str(script)],cwd=migrated,env={**os.environ,'PYTHONPATH':str(ROOT/'src')},capture_output=True,text=True,timeout=15)
    assert result.returncode != 0, result.stdout
    assert 'legacy maintenance blocked' in result.stderr, result.stderr
    assert before == {p.relative_to(migrated):p.read_bytes() for p in migrated.rglob('*') if p.is_file()}


def test_readers_do_not_share_mutable_cache(migrated):
    from stock_swing.tracking.compatibility import read_tracking_state
    path = migrated/'data/tracking/pnl_state.json'
    first = read_tracking_state(path)
    first['trades'].clear()
    assert read_tracking_state(path)['trades']


def test_read_only_path_refuses_prepared_journal_without_recovery(migrated):
    from stock_swing.tracking.compatibility import read_tracking_state, legacy_maintenance
    journal = migrated/'data/tracking/.ledger_transaction.json'
    journal.write_text('{"unfinished":true}')
    before = {p.name:p.read_bytes() for p in journal.parent.iterdir() if p.is_file()}
    for action in [lambda:read_tracking_state(journal.with_name('pnl_state.json')), lambda:legacy_maintenance(migrated).__enter__()]:
        with pytest.raises(LedgerConflict, match='writer recovery'):action()
    assert before == {p.name:p.read_bytes() for p in journal.parent.iterdir() if p.is_file()}


def test_missing_state_never_revives_export_or_zero_risk(migrated):
    from console.services.performance_breakdown_service import _load_trades
    from stock_swing.risk.risk_budget import compute_open_risk
    (migrated/'exports').mkdir()
    (migrated/'exports/closed_trades.csv').write_text('symbol,pnl\nAMAT,999999\n')
    (migrated/'data/tracking/pnl_state.json').unlink()
    rows, warnings = _load_trades(migrated)
    assert rows == [] and any('version mismatch' in w for w in warnings)
    assert compute_open_risk(migrated, 1_000_000)['is_blocked'] is True


def test_legacy_guard_serializes_against_migration(tmp_path):
    import threading
    from stock_swing.tracking.compatibility import legacy_maintenance
    _, _, plan = fixture_plan(tmp_path)
    started, done = threading.Event(), threading.Event()
    results=[]
    def migrate():
        started.set();results.append(apply_migration(tmp_path,plan));done.set()
    with legacy_maintenance(tmp_path):
        worker=threading.Thread(target=migrate);worker.start()
        assert started.wait(2)
        assert not done.wait(.05)
    worker.join(5)
    assert done.is_set() and results[0]['status']=='applied'
    with pytest.raises(LedgerConflict, match='legacy maintenance blocked'):
        with legacy_maintenance(tmp_path):pytest.fail('must not enter')


def test_dashboard_capture_preserves_snapshots_and_withholds_mixed_performance(migrated, monkeypatch):
    from console.services.dashboard_service import DashboardService
    from stock_swing.tracking.pnl_tracker import PnLTracker
    service=DashboardService.__new__(DashboardService)
    service.project_root=migrated;service._tracker=PnLTracker(migrated)
    monkeypatch.setattr(service,'_get_broker_positions',lambda:[])
    monkeypatch.setattr(service,'get_positions',lambda:{'available':False})
    monkeypatch.setattr(service,'_get_market_status_detail',lambda _: {})
    before=json.loads((migrated/'data/tracking/pnl_state.json').read_bytes())
    result=service.get_trading()
    assert result['available'] is True, result
    assert result['daily_snapshots']==before['daily_snapshots']
    assert result['strategy_daily_snapshots']==[]
    assert result['daily_pnl_stats']['available'] is False
    assert result['measurement_lineage']['promotion_ready'] is False
    assert service._get_performance_attribution(result)['available'] is False
    assert service._tracker.get_summary()['tracking_context']['measurement_lineage']==result['measurement_lineage']


def test_remote_reports_event_damage_as_unavailable(migrated, monkeypatch):
    from console import remote_readonly_app as app
    monkeypatch.setattr(app,'PNL_STATE_PATH',migrated/'data/tracking/pnl_state.json')
    assert app.load_recent_trades()['measurement_lineage']['promotion_ready'] is False
    (migrated/'data/tracking/trade_events.jsonl').write_bytes(b'')
    result=app.load_recent_trades()
    assert result['available'] is False and 'version mismatch' in result['error']


def rehearsal_module():
    import importlib.util
    spec=importlib.util.spec_from_file_location('cutover_rehearsal',ROOT/'docs/r22_cutover_compatibility_20261021/rehearsal.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_cutover_and_exact_restore_then_late_write_refusal(tmp_path):
    _,inputs,plan=fixture_plan(tmp_path)
    result=rehearsal_module().run_rehearsal(inputs,plan)
    assert result['exact_four_file_restore']=='passed'
    assert result['late_write_rollback']=='refused_preserved'
    assert result['damaged_backup']=='refused_preserved'


def test_restore_recovers_after_prepared_interruption(migrated,monkeypatch):
    from stock_swing.tracking import ledger_transaction as lt
    from stock_swing.tracking.pnl_tracker import PnLTracker
    module=rehearsal_module();(migrated/'.r22-rehearsal-copy').touch()
    before=module.snapshot(migrated)
    tracker=PnLTracker(migrated);tracker.state.last_updated='2026-10-21T07:00:00Z';tracker._save_state()
    after=module.snapshot(migrated)
    recover=lt._recover;calls=[]
    def interrupt(folder):
        calls.append(1)
        if len(calls)==2:raise OSError('power loss after durable prepare')
        return recover(folder)
    monkeypatch.setattr(lt,'_recover',interrupt)
    with pytest.raises(OSError):module.restore_copy(migrated,before,after['sha256'])
    with pytest.raises(LedgerConflict,match='writer recovery'):module.snapshot(migrated)
    monkeypatch.setattr(lt,'_recover',recover)
    with lt.ledger_transaction(migrated):pass
    assert module.snapshot(migrated)['bytes']==before['bytes']


def test_stale_generated_summary_is_not_accepted(migrated,monkeypatch):
    from console import remote_readonly_app as app
    from stock_swing.tracking.pnl_tracker import PnLTracker
    report=migrated/'summary.json';report.write_text('{}')
    monkeypatch.setattr(app,'SUMMARY_PATH',report)
    monkeypatch.setattr(app,'PNL_STATE_PATH',migrated/'data/tracking/pnl_state.json')
    assert app.load_console_summary()['available'] is False
    report.write_text(json.dumps({'ledger_quality':PnLTracker(migrated).get_ledger_quality_report()}))
    assert app.load_console_summary()['_remote_meta']['available'] is True


@pytest.mark.parametrize('rel',['src/stock_swing/cli/backfill_pnl_state.py','src/stock_swing/tracking/pnl_tracker_fix.py'])
def test_importable_legacy_cli_also_refuses(migrated,rel):
    script=migrated/rel;script.parent.mkdir(parents=True);shutil.copy2(ROOT/rel,script)
    before={n:(migrated/'data/tracking'/n).read_bytes() for n in FILES}
    result=subprocess.run([sys.executable,str(script)],cwd=migrated,env={**os.environ,'PYTHONPATH':str(ROOT/'src')},capture_output=True,text=True,timeout=15)
    assert 'legacy maintenance blocked' in result.stderr
    assert before=={n:(migrated/'data/tracking'/n).read_bytes() for n in FILES}


def test_measurement_uncertainty_cannot_pass_economics(migrated):
    from scripts.check_go_no_go import check_economic_viability, _load
    state=_load(migrated/'data/tracking/pnl_state.json')
    state['trades']=[{'status':'closed','exit_time':'2026-10-21','pnl':9999} for _ in range(40)]
    result=check_economic_viability(state,'2026-08-14')
    assert result['pass'] is False and result['actual']=='historical_correction_unqualified'


def test_imported_save_cannot_bypass_main_guard(migrated):
    from stock_swing.cli.backfill_pnl_state import save_state
    from stock_swing.tracking.pnl_tracker import PnLTracker
    tracker=PnLTracker(migrated);before={n:(migrated/'data/tracking'/n).read_bytes() for n in FILES}
    with pytest.raises(LedgerConflict,match='legacy maintenance blocked'):
        save_state(migrated/'data/tracking/pnl_state.json',tracker.state)
    assert before=={n:(migrated/'data/tracking'/n).read_bytes() for n in FILES}


def test_summary_and_baseline_do_not_mix_history_epochs(migrated):
    from console.services.summary_service import SummaryService
    from stock_swing.analysis.baseline_metrics import calculate_baseline_metrics
    service=SummaryService(migrated)
    result=service.generate_daily_summary()
    assert result['pnl_summary']['measurement_lineage']['promotion_ready'] is False
    assert any(a.get('code')=='historical_correction_unqualified' for a in result['alerts'])
    assert service.generate_weekly_summary()['available'] is False
    state=json.loads((migrated/'data/tracking/pnl_state.json').read_bytes())
    assert calculate_baseline_metrics(state)['error']=='historical_correction_unqualified'
