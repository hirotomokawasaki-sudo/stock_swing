"""Acceptance: execution leg events, R22 AMAT incident 2026-10-14 (base 681b0c1).

This covers event idempotence, not atomicity of tracker + fill/event files.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from stock_swing.tracking.pnl_tracker import PnLTracker
from stock_swing.tracking.trade_event_store import TradeEvent, TradeEventStore


def entry(tracker, qty=10, order='buy-a', decision='decision-a'):
    tracker.record_submission('AAPL', 's1', 'buy', qty, 100, order, decision)


def closed_events(tracker):
    return [e for e in tracker.event_store.read_all() if e.event_type == 'trade_closed']


def test_each_fifo_leg_emits_own_economics(tmp_path):
    tracker = PnLTracker(tmp_path)
    entry(tracker)
    entry(tracker, 5, 'buy-b', 'different-b')
    tracker.record_exit('AAPL', 110, exit_qty=12, broker_order_id='sell')
    events = closed_events(tracker)
    assert len(events) == 2, 'one sell spanning two lots needs two events'
    assert [e.payload['exit_qty'] for e in events] == [10, 2], 'quantities must be incremental per lot'
    assert sum(e.payload['pnl'] for e in events) == pytest.approx(120), 'events must conserve ledger realized PnL'
    assert {e.payload['entry_broker_order_id'] for e in events} == {'buy-a', 'buy-b'}, 'both entry identities must survive'
    assert len({e.payload['execution_leg_id'] for e in events}) == 2, 'full and partial legs need distinct identities'


def test_partial_then_full_same_order_not_deduplicated(tmp_path):
    tracker = PnLTracker(tmp_path)
    entry(tracker, 144)
    tracker.record_exit('AAPL', 110, 98, 'sell', fill_id='sell')
    tracker = PnLTracker(tmp_path)
    tracker.record_exit('AAPL', 111, 46, 'sell', fill_id='sell')
    events = closed_events(tracker)
    assert [e.payload['exit_qty'] for e in events] == [98, 46], 'partial and final legs must both survive'
    assert len({e.event_id for e in events}) == 2, 'order ID alone is not a leg ID'
    assert all(e.payload['exit_fill_id_kind'] == 'order_aggregate' for e in events), 'do not mislabel order IDs as executions'
    assert all(e.payload['broker_executed_at'] is None for e in events), 'receipt time is not execution time'


def test_requested_exit_larger_than_inventory_records_only_closed_qty(tmp_path):
    tracker = PnLTracker(tmp_path)
    entry(tracker, 5)
    tracker.record_exit('AAPL', 110, 10)
    event = closed_events(tracker)[0]
    assert event.payload['exit_qty'] == 5, 'event quantity must not exceed actual closed inventory'
    assert event.payload['exit_fill_id_kind'] == 'missing', 'unknown identity must stay unknown'


def test_same_cumulative_observation_retry_deduplicates_state_and_events(tmp_path):
    from stock_swing.tracking.settle_sell import settle_sell
    entry(PnLTracker(tmp_path))
    order = dict(id='sell', symbol='AAPL', side='sell', filled_qty=5,
                 filled_avg_price=110, filled_at='2026-10-21T14:00:00Z')
    settle_sell(tmp_path, order)
    assert settle_sell(tmp_path, order) is None, 'same cumulative snapshot is a retry, not another incremental fill'
    tracker = PnLTracker(tmp_path)
    assert len(closed_events(tracker)) == 1
    assert sum(t['qty'] for t in tracker.state.trades if t['status']=='open') == 5


def event(qty=5):
    return TradeEvent.create('trade_closed', symbol='AAPL', payload={'exit_qty': qty}, idempotency_key='leg-1')


def test_retry_same_economics_keeps_original_bytes(tmp_path):
    store = TradeEventStore(tmp_path)
    original = event()
    store.append(original)
    before = store.path.read_bytes()
    store.append(replace(event(), run_id='retry-run'))
    assert store.path.read_bytes() == before, 'retry must preserve first observed event bytes'


def test_conflicting_same_identity_rejected_without_append(tmp_path):
    store = TradeEventStore(tmp_path)
    store.append(event())
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match='conflicting'):
        store.append(event(6))
    assert store.path.read_bytes() == before, 'conflict must not overwrite or append'


@pytest.mark.parametrize('content', ['{broken\n', '{}\n', '[]\n'])
def test_corrupt_store_blocks_append(tmp_path, content):
    store = TradeEventStore(tmp_path)
    store.path.write_text(content)
    with pytest.raises(ValueError, match='corrupt'):
        store.append(event())
    assert store.path.read_text() == content, 'corruption must remain available for investigation'


def test_concurrent_writers_append_once(tmp_path):
    def write(_):
        TradeEventStore(tmp_path).append(event())
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(24)))
    assert len(TradeEventStore(tmp_path).read_all()) == 1, 'lock must cover both identity check and append'


def test_quarantine_not_emitted_as_clean_close(tmp_path):
    tracker = PnLTracker(tmp_path)
    entry(tracker)
    tracker.state.trades[0]['entry_time'] = '2099-01-01T00:00:00+00:00'
    tracker._save_state()  # concurrent-safe mutations reload persisted state
    tracker.record_exit('AAPL', 110, 5, 'sell')
    assert not closed_events(tracker), 'quarantined losses or gains must not enter clean event aggregates'
    assert len([e for e in tracker.event_store.read_all() if e.event_type == 'trade_quarantined']) == 1, 'quarantine needs separate evidence'
