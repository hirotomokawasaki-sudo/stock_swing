"""One cumulative SELL observation -> recoverable state/fill/event transaction."""
from .execution_cost import incremental_sell_fill, ExecutionCostError
from .fill_ledger import FillLedger, FillQuarantinedError
from .ledger_transaction import ledger_transaction, LedgerConflict
from .pnl_tracker import PnLTracker


def settle_sell(project_root, order, *, exit_strategy_id=None, exit_reason=None, expected_delta=None):
    """No broker call. Recheck cumulative economics and inventory under shared lock.

    Historical consume/state gaps are NOT auto-repaired. record_exit itself
    remains an incremental-lot primitive; retry deduplication belongs here.
    """
    with ledger_transaction(project_root):
        tracker=PnLTracker(project_root)
        ledger=FillLedger(project_root)
        snapshot=dict(order,qty=order.get('filled_qty'))
        key=ledger.ingest(snapshot,quarantine_on_missing=True)
        fill=ledger.get(key)
        if fill.get('quarantine_reason'):
            raise FillQuarantinedError('unverified sell observation')
        delta=incremental_sell_fill(order,list(tracker.state.trades)+list(tracker.state.quarantined_trades),
                                    consumed_qty=fill.get('consumed_qty',0))
        if not delta.qty:
            return None
        if expected_delta is not None and delta!=expected_delta:
            raise LedgerConflict('sell observation changed after validation; retry with fresh evidence')
        if fill.get('consumed_qty',0)!=delta.prior_qty:
            raise LedgerConflict('historical fill/state quantity gap; no automatic backfill')
        before=sum(t['qty'] for t in tracker.state.trades if t.get('symbol')==order['symbol'] and t.get('status')=='open')
        if before<delta.qty: raise ExecutionCostError('sell exceeds recorded open inventory')
        closed=tracker.record_exit(order['symbol'],float(delta.price),delta.qty,order['id'],
                                   exit_strategy_id,exit_reason,fill_id=key)
        after=sum(t['qty'] for t in tracker.state.trades if t.get('symbol')==order['symbol'] and t.get('status')=='open')
        if closed is None or before-after!=delta.qty:
            raise LedgerConflict('settlement did not close the exact incremental quantity')
        ledger.consume(key,trade_id=f"settled:{order['id']}:{delta.prior_qty}->{delta.prior_qty+delta.qty}",qty=delta.qty)
        return closed
