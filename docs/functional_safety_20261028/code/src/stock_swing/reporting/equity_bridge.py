"""R0-v2-B: Broker equity bridge.

Computes the reconciliation between our tracker's implied equity and the
broker's reported equity.  Surfaces where the gap comes from so operators
can verify that nothing is unexpectedly missing.

Formula (tracker side):
    tracker_computed = baseline_equity + external_cash_adjustment
        + tracker_realized + realized_pnl_adjustment + tracker_unrealized - fees

Typical sources of diff (broker_equity - tracker_computed):
    1. Historical realized-P&L drift caused by malformed FIFO/corporate-action rows.
    2. Historical untracked activity: trades executed before our tracker epoch
       that the broker absorbed into its equity.
    3. Rounding / price discrepancies between tracker and broker mark-to-market.

Within-tolerance definition:
    We flag ``within_tolerance=False`` when |unexplained_diff| > tolerance_usd.
    ``unexplained_diff = diff_usd - quarantined_pnl_adjustment``
    Raw quarantined P&L remains visible but is not applied unless independently
    verified. Reconstruction-corrupt P&L must never be treated as economic truth.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EquityBridgeResult:
    """Full equity reconciliation snapshot."""

    baseline_equity: float
    tracker_realized: float
    tracker_unrealized: float
    fees: float
    raw_tracker_computed: float      # baseline + realized + unrealized
    realized_pnl_adjustment: float   # broker cash-flow reconciliation adjustment
    external_cash_adjustment: float  # deposits/withdrawals after baseline
    tracker_computed: float          # adjusted tracker-implied equity
    broker_equity: float
    diff_usd: float                  # broker_equity - tracker_computed  (+ means broker > tracker)
    diff_bp: float                   # |diff| / broker_equity * 10_000
    quarantined_pnl: float           # raw, potentially corrupt quarantine PnL
    quarantined_pnl_adjustment: float  # independently verified amount applied
    unexplained_diff: float          # diff_usd - quarantined_pnl_adjustment
    within_tolerance: bool           # |unexplained_diff| <= tolerance_usd
    tolerance_usd: float

    def to_dict(self) -> dict:
        return {
            "baseline_equity": round(self.baseline_equity, 2),
            "tracker_realized": round(self.tracker_realized, 2),
            "tracker_unrealized": round(self.tracker_unrealized, 2),
            "fees": round(self.fees, 2),
            "raw_tracker_computed": round(self.raw_tracker_computed, 2),
            "realized_pnl_adjustment": round(self.realized_pnl_adjustment, 2),
            "external_cash_adjustment": round(self.external_cash_adjustment, 2),
            "tracker_computed": round(self.tracker_computed, 2),
            "broker_equity": round(self.broker_equity, 2),
            "diff_usd": round(self.diff_usd, 2),
            "diff_bp": round(self.diff_bp, 1),
            "quarantined_pnl": round(self.quarantined_pnl, 2),
            "quarantined_pnl_adjustment": round(self.quarantined_pnl_adjustment, 2),
            "unexplained_diff": round(self.unexplained_diff, 2),
            "within_tolerance": self.within_tolerance,
            "tolerance_usd": self.tolerance_usd,
        }


def compute_equity_bridge(
    *,
    broker_equity: float,
    baseline_equity: float,
    tracker_realized: float,
    tracker_unrealized: float,
    quarantined_pnl: float = 0.0,
    fees: float = 0.0,
    realized_pnl_adjustment: float = 0.0,
    external_cash_adjustment: float = 0.0,
    quarantined_pnl_adjustment: float = 0.0,
    tolerance_usd: float = 5_000.0,
) -> EquityBridgeResult:
    """Compute reconciliation between tracker-implied and broker equity.

    Args:
        broker_equity: Current equity reported by the broker API.
        baseline_equity: Starting equity at tracker epoch (from pnl_state.json).
        tracker_realized: Cumulative realized PnL (clean trades only, excl. quarantined).
        tracker_unrealized: Sum of unrealized PnL on open positions.
        quarantined_pnl: Raw PnL of quarantined rows, for observability only.
        fees: Cumulative fees charged by broker (0 for paper trading).
        realized_pnl_adjustment: Audited broker cash-flow adjustment to tracker realized P&L.
        external_cash_adjustment: Deposits/withdrawals after the equity baseline.
        quarantined_pnl_adjustment: Independently verified quarantine P&L to apply.
        tolerance_usd: Maximum allowed |unexplained_diff| before flagging as out-of-tolerance.

    Returns:
        EquityBridgeResult with full reconciliation breakdown.
    """
    raw_tracker_computed = baseline_equity + tracker_realized + tracker_unrealized
    tracker_computed = (
        raw_tracker_computed
        + realized_pnl_adjustment
        + external_cash_adjustment
        - fees
    )
    diff = broker_equity - tracker_computed
    diff_bp = abs(diff) / broker_equity * 10_000 if broker_equity else 0.0
    # A genuine broker-only quarantine loss makes broker equity lower, so both
    # diff and the verified adjustment are negative. Raw quarantine PnL can be
    # reconstruction-corrupt and is never applied automatically.
    unexplained = diff - quarantined_pnl_adjustment
    within_tol = abs(unexplained) <= tolerance_usd

    return EquityBridgeResult(
        baseline_equity=baseline_equity,
        tracker_realized=tracker_realized,
        tracker_unrealized=tracker_unrealized,
        fees=fees,
        raw_tracker_computed=raw_tracker_computed,
        realized_pnl_adjustment=realized_pnl_adjustment,
        external_cash_adjustment=external_cash_adjustment,
        tracker_computed=tracker_computed,
        broker_equity=broker_equity,
        diff_usd=diff,
        diff_bp=diff_bp,
        quarantined_pnl=quarantined_pnl,
        quarantined_pnl_adjustment=quarantined_pnl_adjustment,
        unexplained_diff=unexplained,
        within_tolerance=within_tol,
        tolerance_usd=tolerance_usd,
    )
