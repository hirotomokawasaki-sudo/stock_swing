"""R22 AC: retain receipt/recording time without inventing valuation/session time."""
from datetime import datetime, timedelta, timezone

import pytest

from stock_swing.tracking.pnl_tracker import PnLTracker


@pytest.mark.parametrize('observed,expected_date', [
    ('2026-07-08T03:30:00+00:00', '2026-07-07'),
    ('2026-01-08T04:30:00+00:00', '2026-01-07'),
    ('2026-03-08T07:01:00+00:00', '2026-03-08'),
])
def test_receipt_date_dst_does_not_claim_exchange_session(tmp_path, observed, expected_date):
    tracker = PnLTracker(tmp_path)
    snap = tracker.record_daily_snapshot(100000, equity_observed_at=datetime.fromisoformat(observed),
        equity_source='alpaca_paper:/v2/account', run_id='run-1', environment_id='alpaca_paper')
    evidence = snap.valuation_evidence
    assert evidence['observed_et_date'] == expected_date, 'ET conversion must follow DST'
    assert evidence['valuation_at'] is None, 'receipt timestamp does not establish valuation timestamp'
    assert evidence['session_date'] is None, 'ET civil date is not a verified exchange session'
    assert evidence['cashflow_status'] == 'unverified', 'cashflow must not be assumed zero'
    assert evidence['run_id'] == 'run-1', 'snapshot must be joinable to the run'
    saved = PnLTracker(tmp_path).state.daily_snapshots[-1]['valuation_evidence']
    assert saved == evidence, 'all evidence must survive serialization and reload'


def test_no_observation_timestamp_remains_unknown(tmp_path):
    snap = PnLTracker(tmp_path).record_daily_snapshot(100000)
    assert snap.valuation_evidence['observed_at'] is None, 'legacy callers must not fabricate observation time'
    assert snap.valuation_evidence['recorded_at'], 'local persistence time is known separately'
    assert snap.valuation_evidence['source'] is None, 'unknown source must not be labeled broker'


@pytest.mark.parametrize('observed', [datetime(2026, 1, 1), 'invalid', datetime.now(timezone.utc) + timedelta(days=365)])
def test_invalid_observation_rejected_before_state_changes(tmp_path, observed):
    tracker = PnLTracker(tmp_path)
    tracker.record_daily_snapshot(100000)
    before = tracker.state_path.read_bytes()
    with pytest.raises(ValueError, match='observation'):
        tracker.record_daily_snapshot(110000, equity_observed_at=observed)
    assert tracker.state_path.read_bytes() == before, 'invalid metadata must not change peak, DD or history'


def test_adding_evidence_does_not_change_economic_metrics(tmp_path):
    left, right = PnLTracker(tmp_path/'old'), PnLTracker(tmp_path/'new')
    a = left.record_daily_snapshot(90000)
    b = right.record_daily_snapshot(90000, equity_observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    from dataclasses import asdict
    a, b = asdict(a), asdict(b)
    a.pop('valuation_evidence'); b.pop('valuation_evidence')
    assert a == b, 'observation evidence must not redefine existing snapshot economics'
    assert left.state.max_drawdown_pct == right.state.max_drawdown_pct, 'DD unchanged by metadata'
