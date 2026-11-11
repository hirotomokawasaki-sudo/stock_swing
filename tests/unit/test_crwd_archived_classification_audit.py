"""Regression: 2026-11-10 daily audit / immutable CRWD replacement metadata.

Acceptance: recover only exact archived BUY classification in a labeled audit
view, retain raw failures/economic bytes, refuse missing or contradictory proof.
All history is synthetic; no claim of historical performance qualification.
"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import audit_trades_with_market_data as audit
from stock_swing.tracking.history_migration import prepare_migration, apply_migration
from stock_swing.tracking.ledger_transaction import FILES, digest
from stock_swing.tracking.compatibility import read_analysis_snapshot


def fixture(tmp_path, *, source_change=None, target_change=None, conflict=False):
    old = dict(trade_id='archived-lot', symbol='CRWD', status='closed', side='buy',
               broker_order_id='buy-fixture', exit_broker_order_id='sell-fixture',
               entry_time='2026-05-20T13:00:00Z', exit_time='2026-05-22T13:00:00Z',
               qty=10, entry_price=100.0, exit_price=110.0, pnl=100.0,
               holding_days=2, asset_class='stock')
    new = dict(old, trade_id='corrected-lot', execution_leg_id='leg-fixture')
    new.pop('asset_class')
    if source_change:
        old.update(source_change)
    if target_change:
        new.update(target_change)
    originals = [old]
    if conflict:
        originals.append(dict(old, trade_id='archived-conflict', asset_class='etf'))
    original = dict(trades=originals, quarantined_trades=[],
                    cumulative_realized_pnl=100.0 * len(originals))
    inputs = {name: b'' for name in FILES}
    inputs['pnl_state.json'] = json.dumps(original).encode()
    inputs['fill_consumed_ledger.json'] = b'{"fills":[]}'
    plan = prepare_migration(inputs, row_changes=[], corporate_plans=[dict(
        retire_records=[dict(collection='trades', row_index=i, before=row)
                        for i, row in enumerate(originals)], candidate_rows=[new])],
        evidence_sha256='a' * 64, recorded_at='2026-11-09T00:00:00Z',
        reason='synthetic archived metadata regression')
    folder = tmp_path / 'data/tracking'
    folder.mkdir(parents=True)
    for name, raw in inputs.items():
        (folder / name).write_bytes(raw)
    apply_migration(tmp_path, plan)
    return read_analysis_snapshot(folder / 'pnl_state.json')[0]


def test_ac_recovers_exact_archived_classification_without_raw_or_economic_mutation(tmp_path):
    state = fixture(tmp_path)
    original = deepcopy(state)
    before = {n: (tmp_path / 'data/tracking' / n).read_bytes() for n in FILES}
    assert audit.check_ledger_invariants(state)['ac_unknown_count'] == 1
    view, receipt = audit.recover_archived_asset_classes(state)
    assert receipt['recovered'] == 1 and receipt['unresolved'] == 0
    assert view['trades'][0]['asset_class'] == 'stock'
    view['trades'][0].pop('asset_class')
    assert view == original and state == original, 'only audit-view classification may change'
    assert before == {n: (tmp_path / 'data/tracking' / n).read_bytes() for n in FILES}
    assert audit.recover_archived_asset_classes(state)[1] == receipt, 'deterministic retry'
    assert receipt['promotion_ready'] is False and receipt['raw_ledger_modified'] is False
    assert receipt['rows'][0]['archived_sources'][0]['row_sha256']


@pytest.mark.parametrize('change', [dict(broker_order_id='other'), dict(symbol='OTHER'),
                                  dict(entry_time='2026-05-20T14:00:00Z'), dict(side='sell')])
def test_ac_symbol_or_partial_identity_does_not_restore_classification(tmp_path, change):
    state = fixture(tmp_path, source_change=change)
    try:
        view, receipt = audit.recover_archived_asset_classes(state)
    except ValueError:
        return  # incomplete/invalid archived BUY identity is unavailable, not recovered
    assert receipt['recovered'] == 0 and receipt['unresolved'] == 1
    assert audit.check_ledger_invariants(view)['passed'] is False


@pytest.mark.parametrize('asset_class', [None, '', 'unknown', 'invalid'])
def test_ac_absent_or_invalid_archived_class_stays_unknown(tmp_path, asset_class):
    state = fixture(tmp_path, source_change=dict(asset_class=asset_class))
    view, receipt = audit.recover_archived_asset_classes(state)
    assert receipt['recovered'] == 0 and receipt['unresolved'] == 1
    assert audit.check_ledger_invariants(view)['passed'] is False


def test_ac_conflicting_archive_cannot_choose_convenient_class(tmp_path):
    state = fixture(tmp_path, conflict=True)
    view, receipt = audit.recover_archived_asset_classes(state)
    assert receipt['recovered'] == 0 and audit.check_ledger_invariants(view)['passed'] is False


@pytest.mark.parametrize('fault', ['archive', 'digest', 'intent', 'lineage', 'missing_archive', 'retired_row'])
def test_ac_corrupt_archival_bindings_fail_closed(tmp_path, fault):
    state = fixture(tmp_path)
    h = state['history_migrations'][0]
    if fault == 'archive':
        h['original_state_b64'] = 'invalid'
    elif fault == 'digest':
        h['before_sha256']['pnl_state.json'] = '0' * 64
    elif fault == 'intent':
        h['intent']['reason'] = 'changed'
    elif fault == 'lineage':
        state['measurement_lineage']['ledger_revision'] = 'other'
    elif fault == 'missing_archive':
        h.pop('original_state_b64')
    else:
        h['intent']['retire_records'][0]['before']['asset_class'] = 'etf'
    with pytest.raises(ValueError, match='classification archive unavailable'):
        audit.recover_archived_asset_classes(state)


def test_ac_nonreplacement_gap_and_duplicate_are_not_silently_repaired(tmp_path):
    state = fixture(tmp_path)
    state['trades'][0]['trade_id'] = 'not-a-replacement'
    assert audit.recover_archived_asset_classes(state)[1]['recovered'] == 0
    state = fixture(tmp_path / 'other')
    state['trades'].append(deepcopy(state['trades'][0]))
    with pytest.raises(ValueError, match='duplicate replacement'):
        audit.recover_archived_asset_classes(state)


def test_ac_legacy_without_history_is_not_classified_from_symbol(tmp_path):
    state = fixture(tmp_path)
    state.pop('history_migrations')
    view, receipt = audit.recover_archived_asset_classes(state)
    assert receipt['recovered'] == 0 and audit.check_ledger_invariants(view)['passed'] is False


def test_ac_audit_output_keeps_raw_gap_visible_and_performance_unqualified(tmp_path, capsys):
    state = fixture(tmp_path)
    assert audit.audit_ledger_invariants(state)['passed'] is True
    lines = capsys.readouterr().out.splitlines()
    receipts = {line.split('=', 1)[0]: json.loads(line.split('=', 1)[1])
                for line in lines if '_JSON=' in line}
    assert receipts['RAW_LEDGER_INVARIANTS_JSON']['passed'] is False
    assert receipts['RAW_LEDGER_INVARIANTS_JSON']['ac_unknown_count'] == 1
    assert receipts['AUDIT_VIEW_INVARIANTS_JSON']['passed'] is True
    assert receipts['CLASSIFICATION_RECOVERY_JSON']['promotion_ready'] is False
    assert any('raw historical rows remain immutable' in line for line in lines)


def test_ac_ledger_only_uses_real_reader_and_cannot_call_broker_or_market(tmp_path, monkeypatch, capsys):
    fixture(tmp_path)
    before = {n: digest((tmp_path / 'data/tracking' / n).read_bytes()) for n in FILES}
    monkeypatch.setattr(audit, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr('sys.argv', ['audit', '--ledger-only'])
    def forbidden(*args, **kwargs):
        pytest.fail('ledger-only must never call an external broker or market service')
    monkeypatch.setattr(audit, 'BrokerClient', forbidden)
    monkeypatch.setattr(audit, 'fetch_yahoo_finance_bars', forbidden)
    assert audit.main() == 0
    output = capsys.readouterr().out
    assert '"broker_check": "not_checked"' in output
    assert '"price_checks": "not_checked"' in output
    assert before == {n: digest((tmp_path / 'data/tracking' / n).read_bytes()) for n in FILES}


@pytest.mark.parametrize('missing', ['pnl_state.json', 'trade_events.jsonl'])
def test_ac_missing_pair_cannot_become_a_clean_empty_audit(tmp_path, monkeypatch, missing):
    fixture(tmp_path)
    (tmp_path / 'data/tracking' / missing).unlink()
    monkeypatch.setattr(audit, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr('sys.argv', ['audit', '--ledger-only'])
    assert audit.main() != 0


@pytest.mark.parametrize('outcome,expected', [('ok', 0), ('broker_error', 1), ('price_unavailable', 2)])
def test_ac_default_daily_path_recovers_metadata_without_hiding_other_failures(tmp_path, monkeypatch, outcome, expected):
    fixture(tmp_path)
    monkeypatch.setattr(audit, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr('sys.argv', ['audit'] + ([] if outcome == 'price_unavailable' else ['--recent-days', '1']))
    monkeypatch.setenv('BROKER_API_KEY', 'synthetic-not-a-key')
    monkeypatch.setenv('BROKER_API_SECRET', 'synthetic-not-a-secret')
    class FixtureBroker:
        def __init__(self, **kwargs):
            assert kwargs['paper_mode'] is True
        def fetch_positions(self):
            if outcome == 'broker_error':
                raise RuntimeError('synthetic broker unavailable')
            return SimpleNamespace(payload=[])
    monkeypatch.setattr(audit, 'BrokerClient', FixtureBroker)
    monkeypatch.setattr(audit, 'fetch_yahoo_finance_bars', lambda *args: {})
    assert audit.main() == expected
