"""R0-v2-B: Broker equity bridge.

Computes the reconciliation between our tracker's implied equity and the
broker's reported equity.  Surfaces where the gap comes from so operators
can verify that nothing is unexpectedly missing.

Formula (tracker side):
    tracker_computed = baseline_equity + tracker_realized + tracker_unrealized - fees

Typical sources of diff (broker_equity - tracker_computed):
    1. quarantined_pnl: trades quarantined in our ledger still executed at the broker.
       The broker's equity reflects these fills; our tracker intentionally excludes them.
    2. Historical untracked activity: trades executed before our tracker epoch
       that the broker absorbed into its equity.
    3. Rounding / price discrepancies between tracker and broker mark-to-market.

Within-tolerance definition:
    We flag ``within_tolerance=False`` when |unexplained_diff| > tolerance_usd.
    ``unexplained_diff = diff_usd - quarantined_pnl``
    A diff fully explained by quarantined PnL is expected and not flagged.
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
    tracker_computed: float          # baseline + realized + unrealized - fees
    broker_equity: float
    diff_usd: float                  # broker_equity - tracker_computed  (+ means broker > tracker)
    diff_bp: float                   # |diff| / broker_equity * 10_000
    quarantined_pnl: float           # total PnL of quarantined trades (executed at broker)
    unexplained_diff: float          # diff_usd - quarantined_pnl
    within_tolerance: bool           # |unexplained_diff| <= tolerance_usd
    tolerance_usd: float

    def to_dict(self) -> dict:
        return {
            "baseline_equity": round(self.baseline_equity, 2),
            "tracker_realized": round(self.tracker_realized, 2),
            "tracker_unrealized": round(self.tracker_unrealized, 2),
            "fees": round(self.fees, 2),
            "tracker_computed": round(self.tracker_computed, 2),
            "broker_equity": round(self.broker_equity, 2),
            "diff_usd": round(self.diff_usd, 2),
            "diff_bp": round(self.diff_bp, 1),
            "quarantined_pnl": round(self.quarantined_pnl, 2),
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
    tolerance_usd: float = 5_000.0,
) -> EquityBridgeResult:
    """Compute reconciliation between tracker-implied and broker equity.

    Args:
        broker_equity: Current equity reported by the broker API.
        baseline_equity: Starting equity at tracker epoch (from pnl_state.json).
        tracker_realized: Cumulative realized PnL (clean trades only, excl. quarantined).
        tracker_unrealized: Sum of unrealized PnL on open positions.
        quarantined_pnl: Total PnL of quarantined trades (executed at broker, excluded from tracker).
        fees: Cumulative fees charged by broker (0 for paper trading).
        tolerance_usd: Maximum allowed |unexplained_diff| before flagging as out-of-tolerance.

    Returns:
        EquityBridgeResult with full reconciliation breakdown.
    """
    tracker_computed = baseline_equity + tracker_realized + tracker_unrealized - fees
    diff = broker_equity - tracker_computed
    diff_bp = abs(diff) / broker_equity * 10_000 if broker_equity else 0.0
    # Quarantined trades executed at broker → broker equity is higher (their losses are ours)
    # If quarantined_pnl is negative, broker absorbed those losses → diff should be positive
    # unexplained = what's left after accounting for quarantined PnL
    unexplained = diff - quarantined_pnl
    within_tol = abs(unexplained) <= tolerance_usd

    return EquityBridgeResult(
        baseline_equity=baseline_equity,
        tracker_realized=tracker_realized,
        tracker_unrealized=tracker_unrealized,
        fees=fees,
        tracker_computed=tracker_computed,
        broker_equity=broker_equity,
        diff_usd=diff,
        diff_bp=diff_bp,
        quarantined_pnl=quarantined_pnl,
        unexplained_diff=unexplained,
        within_tolerance=within_tol,
        tolerance_usd=tolerance_usd,
    )
