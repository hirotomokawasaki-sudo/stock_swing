"""FIX-06/fa8159a + FIX-02/05: financial transactions must not own intents.

Acceptance: auxiliary durable journals remain writable/readable without a
financial state, and survive a failed financial unit of work before HTTP.
"""
import pytest
from stock_swing.tracking.ledger_transaction import ledger_transaction, stage_bytes
from stock_swing.tracking.trade_event_store import TradeEvent, TradeEventStore

@pytest.mark.parametrize('rel', [
    'data/tracking/submission_intents/fixture.jsonl',
    'data/tracking/cancel_intents/fixture.jsonl',
    'reports/config_instances/fixture.jsonl',
])
def test_ac_auxiliary_receipt_survives_financial_abort(tmp_path, rel):
    store = TradeEventStore(tmp_path, rel)
    event = TradeEvent.create('fixture_prepared', payload={'namespace':'fixture'})
    with pytest.raises(RuntimeError, match='abort after durable preparation'):
        with ledger_transaction(tmp_path):
            stage_bytes(tmp_path, tmp_path/'data/tracking/pnl_state.json', b'{}')
            store.append(event)
            raise RuntimeError('abort after durable preparation')
    assert not (tmp_path/'data/tracking/pnl_state.json').exists(), 'financial write must be discarded'
    assert store.read_all() == [event], 'prepared intent must not disappear with the financial transaction'
    assert store.read_raw() == [event], 'auxiliary journals have no economic supersession view'

def test_ac_canonical_event_does_not_escape_financial_abort(tmp_path):
    store = TradeEventStore(tmp_path)
    with pytest.raises(RuntimeError, match='abort financial event'):
        with ledger_transaction(tmp_path):
            store.append(TradeEvent.create('fixture_event'))
            raise RuntimeError('abort financial event')
    assert not store.path.exists(), 'canonical events must remain in the four-file transaction'
