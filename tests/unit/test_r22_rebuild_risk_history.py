"""R22 2026-10-20 regression: 8/24 rebuild reset DD and resolve dropped history.

Acceptance: preserve the same risk epoch; fail before broker reads or writes on
missing/corrupt/inconsistent evidence. No automatic historical DD repair.
"""
from argparse import Namespace
from copy import deepcopy
import json

import pytest

from scripts.rebuild_pnl_state_from_broker import (
    load_existing_tracking_metadata, resolve_tracking_metadata, rebuild_pnl_state,
)


class EmptyBroker:
    def fetch_all_orders(self, **kwargs):
        return {'orders': []}

    def fetch_positions(self):
        return []

    def fetch_account(self):
        return {'id': 'test-account'}


class NoBrokerReads:
    def __getattr__(self, name):
        raise AssertionError(f'Invalid history must stop before broker access: {name}')


def args(**changes):
    base = dict(baseline_equity=None, baseline_date=None, created_at=None,
                tracking_label=None, performance_scope=None, archive_path=None,
                migration_note_path=None)
    return Namespace(**(base | changes))


def metadata(**changes):
    return dict(baseline_equity=100., baseline_date='2026-06-01',
                peak_equity=120., max_drawdown_pct=.25,
                daily_snapshots=[{'date': '2026-06-05', 'equity': 120.},
                                 {'date': '2026-06-06', 'equity': 90.}],
                strategy_daily_snapshots=[{'date': '2026-06-06', 'strategy_id': 's'}]) | changes


def test_ac_risk_history_survives_load_resolve_rebuild_and_second_rebuild(tmp_path):
    state_file = tmp_path / 'pnl_state.json'
    original = metadata()
    state_file.write_text(json.dumps(original))
    loaded = load_existing_tracking_metadata(state_file)
    resolved = resolve_tracking_metadata(args(), loaded, '2026-06-07T00:00:00+00:00')
    rebuilt = rebuild_pnl_state(EmptyBroker(), resolved)
    for key in ('peak_equity', 'max_drawdown_pct', 'daily_snapshots', 'strategy_daily_snapshots'):
        assert rebuilt[key] == original[key], f'{key} must survive the full metadata path'
    assert rebuilt['cumulative_realized_pnl'] == pytest.approx(0), 'realized PnL is not equity risk history'
    state_file.write_text(json.dumps(rebuilt))
    again = rebuild_pnl_state(EmptyBroker(), resolve_tracking_metadata(
        args(), load_existing_tracking_metadata(state_file), '2026-06-08T00:00:00+00:00'))
    for key in ('peak_equity', 'max_drawdown_pct', 'daily_snapshots'):
        assert again[key] == rebuilt[key], 'repeated rebuild must not reset risk history'


@pytest.mark.parametrize('change', [
    {'peak_equity': 110.}, {'max_drawdown_pct': .1}, {'peak_equity': None},
    {'max_drawdown_pct': None}, {'peak_equity': float('nan')},
    {'max_drawdown_pct': float('inf')}, {'peak_equity': True},
    {'max_drawdown_pct': -.1}, {'max_drawdown_pct': 1.1},
    {'daily_snapshots': [{'date': '2026-06-01', 'equity': None}]},
    {'daily_snapshots': [{'date': 'bad', 'equity': 110.}]},
    {'daily_snapshots': [{'date': '2026-05-01', 'equity': 110.}]},
    {'daily_snapshots': None}, {'daily_snapshots': [None]},
])
def test_ac_invalid_or_unknown_risk_history_stops_before_broker(change):
    state = metadata(**change)
    with pytest.raises(ValueError, match='risk history'):
        rebuild_pnl_state(NoBrokerReads(), state)


@pytest.mark.parametrize('contents', [None, '{broken', '[]'])
def test_ac_missing_or_corrupt_file_does_not_bootstrap_zero_dd(tmp_path, contents):
    p = tmp_path / 'pnl_state.json'
    if contents is not None:
        p.write_text(contents)
    loaded = load_existing_tracking_metadata(p)
    resolved = resolve_tracking_metadata(args(), loaded, '2026-06-07T00:00:00+00:00')
    with pytest.raises(ValueError, match='risk history'):
        rebuild_pnl_state(NoBrokerReads(), resolved)


@pytest.mark.parametrize('change', [dict(baseline_date='2026-06-02'),
                                  dict(baseline_equity=200.),
                                  dict(performance_scope='another_scope')])
def test_ac_cli_epoch_change_cannot_silently_reuse_old_dd(change):
    with pytest.raises(ValueError, match='risk history'):
        resolve_tracking_metadata(args(**change), metadata(performance_scope='current_account_since_baseline'),
                                  '2026-06-07T00:00:00+00:00')


def test_ac_rounding_tolerance_and_unobserved_high_water_are_preserved():
    state = metadata(peak_equity=130., max_drawdown_pct=.3000,
                     daily_snapshots=[{'date': '2026-06-05', 'equity': 100.},
                                      {'date': '2026-06-06', 'equity': 69.996}])
    original = deepcopy(state)
    rebuilt = rebuild_pnl_state(EmptyBroker(), state)
    assert rebuilt['peak_equity'] == 130., 'do not discard a separately recorded high-water mark'
    assert rebuilt['max_drawdown_pct'] == .3, 'respect the existing four-decimal rounding'
    assert state == original, 'validation must not rewrite its input'


def test_ac_empty_snapshot_list_preserves_known_risk_not_perfect_performance():
    rebuilt = rebuild_pnl_state(EmptyBroker(), metadata(daily_snapshots=[]))
    assert rebuilt['max_drawdown_pct'] == .25, 'absence of snapshots does not imply zero loss'
