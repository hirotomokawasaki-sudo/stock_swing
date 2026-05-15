from argparse import Namespace

from scripts.rebuild_pnl_state_from_broker import resolve_tracking_metadata


def test_resolve_tracking_metadata_prefers_cli_over_existing_state():
    args = Namespace(
        baseline_equity=1000000.0,
        baseline_date='2026-05-12',
        created_at='2026-05-12T00:17:00+00:00',
        tracking_label='alpaca_account_epoch_2026-05-12',
        performance_scope='current_account_since_baseline',
        archive_path='data/archive/account_old',
        migration_note_path='docs/account_migration_2026-05-12.md',
    )
    existing = {
        'created_at': '2026-05-14T00:23:58+00:00',
        'baseline_date': '2026-05-14',
        'baseline_equity': 999999.0,
        'tracking_label': 'broker_rebuilt_20260514_002358',
        'performance_scope': 'broker_order_history',
        'archive_path': None,
        'migration_note_path': None,
        'archived_from_account_id': 'old-account',
    }

    resolved = resolve_tracking_metadata(args, existing, '2026-05-15T00:00:00+00:00')

    assert resolved['created_at'] == '2026-05-12T00:17:00+00:00'
    assert resolved['baseline_date'] == '2026-05-12'
    assert resolved['baseline_equity'] == 1000000.0
    assert resolved['tracking_label'] == 'alpaca_account_epoch_2026-05-12'
    assert resolved['performance_scope'] == 'current_account_since_baseline'
    assert resolved['archive_path'] == 'data/archive/account_old'
    assert resolved['migration_note_path'] == 'docs/account_migration_2026-05-12.md'
    assert resolved['archived_from_account_id'] == 'old-account'


def test_resolve_tracking_metadata_falls_back_to_existing_state():
    args = Namespace(
        baseline_equity=None,
        baseline_date=None,
        created_at=None,
        tracking_label=None,
        performance_scope=None,
        archive_path=None,
        migration_note_path=None,
    )
    existing = {
        'created_at': '2026-05-12T00:17:00+00:00',
        'baseline_date': '2026-05-12',
        'baseline_equity': 1000000.0,
        'tracking_label': 'alpaca_account_epoch_2026-05-12',
        'performance_scope': 'current_account_since_baseline',
        'archive_path': 'data/archive/account_old',
        'migration_note_path': 'docs/account_migration_2026-05-12.md',
        'archived_from_account_id': 'old-account',
    }

    resolved = resolve_tracking_metadata(args, existing, '2026-05-15T00:00:00+00:00')

    assert resolved == existing
