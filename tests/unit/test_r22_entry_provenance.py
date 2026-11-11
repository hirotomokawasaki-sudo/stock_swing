"""R22: one sell may consume several buys; sell identity cannot prove entry origin.

Synthetic fixtures, no broker calls or real order/account IDs. Preserve genuine
same-buy attribution without propagating already contaminated future decisions.
"""
from copy import deepcopy
import json

import pytest

from scripts.rebuild_pnl_state_from_broker import load_existing_attribution, apply_attribution


def trade(**changes):
    return dict(symbol='TEST', status='closed', broker_order_id='buy-a',
                exit_broker_order_id='sell-shared', entry_time='2026-06-02T14:00:00Z',
                exit_time='2026-06-05T14:00:00Z', qty=10, pnl=50.,
                strategy_id='strategy-v2', original_strategy_id='strategy-v1',
                strategy_version_id='strategy-v2', decision_id='decision-a',
                run_id='run-a', exit_strategy_id='exit-v1', exit_reason='stop_loss') | changes


def decision(**changes):
    return dict(decision_id='decision-a', symbol='TEST', action='buy',
                generated_at='2026-06-02T13:59:00+00:00', strategy_id='strategy-v1',
                strategy_version_id='strategy-v2', run_id='run-a') | changes


def fresh(**changes):
    result = trade(**changes)
    for key in ('decision_id', 'run_id', 'strategy_version_id', 'exit_strategy_id'):
        result.pop(key, None)
    result.update(strategy_id='broker_reconstructed', original_strategy_id='broker_reconstructed',
                  exit_reason='broker_fill')
    return result


def load(tmp_path, rows, decisions=None):
    tracking = tmp_path / 'data/tracking'
    tracking.mkdir(parents=True, exist_ok=True)
    path = tracking / 'pnl_state.json'
    path.write_text(json.dumps(dict(trades=rows, quarantined_trades=[{'trade_id': 'synthetic-q'}])))
    directory = tmp_path / 'data/decisions'
    directory.mkdir(exist_ok=True)
    for i, d in enumerate(decisions if decisions is not None else [decision()]):
        (directory / f'{i}.json').write_text(json.dumps(d))
    return load_existing_attribution(path)


def test_shared_sell_does_not_copy_entry_decision_to_another_buy(tmp_path):
    attr = load(tmp_path, [trade()])
    state = {'trades': [fresh(), fresh(broker_order_id='buy-b')]}
    stats = apply_attribution(state, attr)
    assert state['trades'][0]['decision_id'] == 'decision-a', 'Acceptance failed: shared_sell_does_not_copy_entry_decision_to_another_buy'
    assert state['trades'][0]['exit_strategy_id'] == 'exit-v1', 'Acceptance failed: shared_sell_does_not_copy_entry_decision_to_another_buy'
    assert 'decision_id' not in state['trades'][1], 'Acceptance failed: shared_sell_does_not_copy_entry_decision_to_another_buy'
    assert 'exit_strategy_id' not in state['trades'][1], 'Acceptance failed: shared_sell_does_not_copy_entry_decision_to_another_buy'
    assert stats['provenance_restored'] == 1, 'Acceptance failed: shared_sell_does_not_copy_entry_decision_to_another_buy'
    assert stats['provenance_unresolved'] == 1, 'Acceptance failed: shared_sell_does_not_copy_entry_decision_to_another_buy'


@pytest.mark.parametrize('change', [dict(broker_order_id=''), dict(symbol='OTHER'),
    dict(entry_time='2026-06-02T13:58:00Z'), dict(entry_time='2026-06-02T14:00:00'),
    dict(entry_time=None)])
def test_destination_requires_buy_identity_and_aware_pre_entry_decision(tmp_path, change):
    attr = load(tmp_path, [trade()])
    state = {'trades': [fresh(**change)]}
    apply_attribution(state, attr)
    assert 'decision_id' not in state['trades'][0], 'Acceptance failed: destination_requires_buy_identity_and_aware_pre_entry_decision'


@pytest.mark.parametrize('change', [dict(generated_at='2026-06-03T14:00:00Z'),
    dict(generated_at='bad'), dict(generated_at=None), dict(generated_at='2026-06-02T13:59:00'),
    dict(symbol='OTHER'), dict(action='sell'), dict(run_id='different'),
    dict(strategy_id='different'), dict(decision_id='different')])
def test_unproven_or_future_source_is_not_reused(tmp_path, change):
    attr = load(tmp_path, [trade()], [decision(**change)])
    state = {'trades': [fresh()]}
    apply_attribution(state, attr)
    assert 'decision_id' not in state['trades'][0], 'Acceptance failed: unproven_or_future_source_is_not_reused'
    assert attr['provenance_diagnostics']['rejected_source_rows'] == 1, 'Acceptance failed: unproven_or_future_source_is_not_reused'


@pytest.mark.parametrize('records', [[], [None], [decision(), decision()]])
def test_missing_malformed_duplicate_decision_evidence_is_unknown(tmp_path, records):
    attr = load(tmp_path, [trade()], records)
    state = {'trades': [fresh()]}
    apply_attribution(state, attr)
    assert 'decision_id' not in state['trades'][0], 'Acceptance failed: missing_malformed_duplicate_decision_evidence_is_unknown'


def test_unreadable_decision_json_is_unknown(tmp_path):
    load(tmp_path, [], [])
    (tmp_path / 'data/decisions/broken.json').write_text('{bad')
    attr = load(tmp_path, [trade()], [])
    state = {'trades': [fresh()]}
    apply_attribution(state, attr)
    assert 'decision_id' not in state['trades'][0], 'Acceptance failed: unreadable_decision_json_is_unknown'


@pytest.mark.parametrize('reverse', [False, True])
def test_conflicting_same_buy_candidates_are_not_last_write_wins(tmp_path, reverse):
    rows = [trade(), trade(decision_id='decision-b')]
    attr = load(tmp_path, rows[::-1] if reverse else rows,
                [decision(), decision(decision_id='decision-b')])
    state = {'trades': [fresh()]}
    apply_attribution(state, attr)
    assert 'decision_id' not in state['trades'][0], 'Acceptance failed: conflicting_same_buy_candidates_are_not_last_write_wins'
    assert attr['provenance_diagnostics']['ambiguous_entry_keys'] == 1, 'Acceptance failed: conflicting_same_buy_candidates_are_not_last_write_wins'


def test_open_and_partial_legs_preserve_valid_origin_and_economics_idempotently(tmp_path):
    attr = load(tmp_path, [trade(), trade(qty=4, pnl=20., exit_broker_order_id='sell-other')])
    state = {'trades': [fresh(qty=6, pnl=30.), fresh(qty=4, pnl=20., exit_broker_order_id='sell-other'),
                        fresh(status='open', exit_broker_order_id=None)]}
    economics = [{k: t.get(k) for k in ('broker_order_id', 'exit_broker_order_id', 'qty', 'pnl',
                                      'entry_time', 'exit_time')} for t in state['trades']]
    stats = apply_attribution(state, attr)
    assert stats['provenance_restored'] == 3, 'Acceptance failed: open_and_partial_legs_preserve_valid_origin_and_economics_idempotently'
    assert state['quarantined_trades'] == [{'trade_id': 'synthetic-q'}], 'Acceptance failed: open_and_partial_legs_preserve_valid_origin_and_economics_idempotently'
    assert economics == [{k: t.get(k) for k in economics[0]} for t in state['trades']], 'Acceptance failed: open_and_partial_legs_preserve_valid_origin_and_economics_idempotently'
    once = deepcopy(state)
    apply_attribution(state, attr)
    assert state == once, 'Acceptance failed: open_and_partial_legs_preserve_valid_origin_and_economics_idempotently'


def test_open_source_preserves_attribution_on_later_close(tmp_path):
    attr = load(tmp_path, [trade(status='open', exit_broker_order_id=None)])
    state = {'trades': [fresh()]}
    apply_attribution(state, attr)
    assert state['trades'][0]['decision_id'] == 'decision-a', 'Acceptance failed: open_source_preserves_attribution_on_later_close'


def test_valid_row_does_not_override_a_tainted_same_buy_candidate(tmp_path):
    attr = load(tmp_path, [trade(), trade(entry_time='2026-06-02T13:58:00Z')])
    state = {'trades': [fresh()]}
    apply_attribution(state, attr)
    assert 'decision_id' not in state['trades'][0], 'Acceptance failed: valid_row_does_not_override_a_tainted_same_buy_candidate'
    assert attr['provenance_diagnostics']['withheld_tainted_entry_keys'] == 1, 'Acceptance failed: valid_row_does_not_override_a_tainted_same_buy_candidate'


@pytest.mark.parametrize('change', [dict(broker_order_id=[]), dict(decision_id=[]), dict(symbol=None)])
def test_malformed_source_identity_cannot_be_indexed(tmp_path, change):
    attr = load(tmp_path, [trade(**change)])
    state = {'trades': [fresh()]}
    apply_attribution(state, attr)
    assert 'decision_id' not in state['trades'][0], 'Acceptance failed: malformed_source_identity_cannot_be_indexed'


def test_conflicting_exit_strategy_is_not_last_write_wins(tmp_path):
    attr = load(tmp_path, [trade(), trade(exit_strategy_id='another-exit')])
    state = {'trades': [fresh()]}
    apply_attribution(state, attr)
    assert state['trades'][0]['decision_id'] == 'decision-a', 'Acceptance failed: conflicting_exit_strategy_is_not_last_write_wins'
    assert 'exit_strategy_id' not in state['trades'][0], 'Acceptance failed: conflicting_exit_strategy_is_not_last_write_wins'


def test_legacy_sell_or_pnl_fallback_cannot_restore_entry_origin():
    state = {'trades': [fresh()]}
    attr = dict(provenance_by_exit_order_id={'sell-shared': {'decision_id': 'wrong'}},
                provenance_by_key={('TEST', '2026-06-05T14:00:00', 50): {'decision_id': 'wrong'}})
    apply_attribution(state, attr)
    assert 'decision_id' not in state['trades'][0], 'Acceptance failed: legacy_sell_or_pnl_fallback_cannot_restore_entry_origin'
