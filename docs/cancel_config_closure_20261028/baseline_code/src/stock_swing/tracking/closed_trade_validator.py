"""R0-v2-B: Canonical validator for closed trades.

Enforces integrity invariants before a trade is recorded as closed:
  - holding_days must be computed (non-None, non-negative)
  - entry_time <= exit_time (chronology correct)
  - qty > 0
  - prices > 0 (entry_price, exit_price when present)
  - trade_id must not already exist in quarantined_trades (exclusivity)
  - pnl arithmetic: |pnl - (exit-entry)*qty| <= tolerance

This validator is called by PnLTracker.record_exit() as a pre-write gate.
Trades failing validation are quarantined instead of being marked closed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TradeValidationResult:
    """Result of canonical validator check."""

    valid: bool
    issues: list[str] = field(default_factory=list)

    @property
    def quarantine_reason(self) -> str | None:
        """Compact reason string for quarantine metadata."""
        return "; ".join(self.issues) if self.issues else None


def validate_closed_trade(
    trade: dict,
    *,
    quarantined_ids: set[str] | None = None,
    pnl_tolerance_usd: float = 0.05,
) -> TradeValidationResult:
    """Validate a trade dict before recording it as closed.

    Args:
        trade: Trade dict (status may still be 'open' at this point).
        quarantined_ids: Set of trade_id values already in quarantined_trades.
            If provided, triggers overlap check (exclusivity invariant).
        pnl_tolerance_usd: Allowed arithmetic rounding error in PnL.

    Returns:
        TradeValidationResult with valid=True when all checks pass.
    """
    issues: list[str] = []

    # 1. holding_days: must be computed, non-negative
    hd = trade.get("holding_days")
    if hd is None:
        issues.append("holding_days is None — must be computed from entry_time/exit_time")
    elif float(hd) < 0:
        issues.append(
            f"holding_days={float(hd):.4f} is negative (entry_time > exit_time)"
        )

    # 2. Chronology: entry_time <= exit_time
    entry_str = trade.get("entry_time")
    exit_str = trade.get("exit_time")
    if entry_str and exit_str:
        try:
            e = datetime.fromisoformat(str(entry_str).replace("Z", "+00:00"))
            x = datetime.fromisoformat(str(exit_str).replace("Z", "+00:00"))
            if e > x:
                issues.append(
                    f"reversed chronology: entry {str(entry_str)[:10]} > exit {str(exit_str)[:10]}"
                )
        except Exception as exc:
            issues.append(f"unparseable timestamps: {exc}")

    # 3. qty > 0
    qty = trade.get("qty")
    try:
        if qty is None or float(qty) <= 0:
            issues.append(f"qty={qty} is not positive")
    except (TypeError, ValueError):
        issues.append(f"qty={qty!r} is not numeric")

    # 4. Prices > 0
    for price_field in ("entry_price", "exit_price"):
        price = trade.get(price_field)
        if price is not None:
            try:
                if float(price) <= 0:
                    issues.append(f"{price_field}={price} is not positive")
            except (TypeError, ValueError):
                issues.append(f"{price_field}={price!r} is not numeric")

    # 5. PnL arithmetic check
    entry_price = trade.get("entry_price")
    exit_price = trade.get("exit_price")
    recorded_pnl = trade.get("pnl")
    if qty is not None and entry_price is not None and exit_price is not None and recorded_pnl is not None:
        try:
            expected_pnl = (float(exit_price) - float(entry_price)) * float(qty)
            if abs(float(recorded_pnl) - expected_pnl) > pnl_tolerance_usd:
                issues.append(
                    f"pnl arithmetic mismatch: recorded={float(recorded_pnl):.4f} "
                    f"expected={(expected_pnl):.4f} "
                    f"diff={abs(float(recorded_pnl) - expected_pnl):.4f}"
                )
        except (TypeError, ValueError):
            pass  # already caught in price/qty checks above

    # 6. Quarantine exclusivity
    if quarantined_ids is not None:
        tid = trade.get("trade_id")
        if tid and tid in quarantined_ids:
            issues.append(
                f"trade_id={tid} already exists in quarantined_trades "
                "(closed/quarantine overlap violation)"
            )

    return TradeValidationResult(valid=len(issues) == 0, issues=issues)
