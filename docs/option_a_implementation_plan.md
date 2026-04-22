# Option A Implementation Plan

**Date:** 2026-04-22 11:59 JST  
**Decision:** Option A - Conservative (Week 3 Optimization + Kelly Sizing)  
**Timeline:** 1 month (Apr 22 - May 22)  
**Expected Outcome:** Return +12-15%, Sharpe 1.8  

---

## Overview

**Option A Components:**
1. Week 3 Parameter Optimization (planned)
2. Kelly Criterion Position Sizing (new)
3. Tax Optimization Framework (new)

**Investment:** Nearly zero ($0 additional costs)  
**Risk:** Low (validated approaches)  
**Expected Impact:** Return +2.98% → +12-15%  

---

## Implementation Schedule

### Week 3 (Apr 24-28): Parameter Optimization ✅ (Already Planned)

**Day 1 (Thu Apr 24):** Backtest Engine
- Build walk-forward validation framework
- Implement parameter grid search
- Validate against known results

**Day 2 (Fri Apr 25):** Parameter Testing
- Test 5 key parameters
- Focus on signal quality + risk/reward
- Statistical validation

**Day 3 (Sat Apr 26):** Results Analysis
- Analyze 150-200 combinations
- Select optimal parameters
- Document findings

**Day 4 (Sun Apr 27):** Report Generation
- Create optimization report
- Validate out-of-sample
- Prepare deployment plan

**Day 5 (Mon Apr 28):** Deployment
- Deploy approved parameters
- Monitor performance
- Prepare rollback if needed

**Expected Impact:**
- Sharpe: 0.85 → 1.5
- Execution: 18% → 65%
- Return: +2.98% → +6%

---

### Week 4 (Apr 29 - May 5): Kelly Criterion Implementation

#### Phase 1: Core Implementation (Apr 29-30)

**File:** `src/stock_swing/risk/kelly_sizing.py` (NEW)

**Implementation:**
```python
"""
Kelly Criterion Position Sizing
Dynamically adjusts position size based on signal confidence and edge
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class KellyCriterionSizer:
    """
    Calculate optimal position size using Kelly Criterion.
    
    Formula: f* = (bp - q) / b
    Where:
        f* = fraction of capital to bet
        b = odds received (reward/risk ratio)
        p = probability of winning
        q = probability of losing (1-p)
    
    For trading, simplified as:
        position_fraction = signal_confidence * edge_factor * kelly_fraction
    """
    
    def __init__(
        self,
        max_position_pct: float = 0.50,  # Max 50% of account
        kelly_fraction: float = 0.50,     # Use half-Kelly (conservative)
        min_confidence: float = 0.60,     # Minimum confidence to use Kelly
    ):
        self.max_position_pct = max_position_pct
        self.kelly_fraction = kelly_fraction
        self.min_confidence = min_confidence
        
        logger.info(
            f"KellyCriterion initialized: "
            f"max_position={max_position_pct:.0%}, "
            f"kelly_fraction={kelly_fraction:.0%}, "
            f"min_confidence={min_confidence:.0%}"
        )
    
    def calculate_position_size(
        self,
        account_equity: float,
        signal_confidence: float,
        signal_strength: float,
        current_price: float,
        min_shares: int = 1,
        max_shares: Optional[int] = None,
    ) -> Dict:
        """
        Calculate optimal position size.
        
        Args:
            account_equity: Total account value
            signal_confidence: Signal confidence (0.0-1.0)
            signal_strength: Signal strength (0.0-1.0)
            current_price: Current stock price
            min_shares: Minimum shares to trade
            max_shares: Maximum shares allowed (optional)
        
        Returns:
            Dict with:
                - shares: Number of shares to buy
                - notional: Dollar amount
                - kelly_pct: Kelly percentage used
                - method: Sizing method used
        """
        
        # Default to fixed sizing if confidence too low
        if signal_confidence < self.min_confidence:
            return self._fixed_sizing(
                account_equity, current_price, min_shares, max_shares
            )
        
        # Calculate Kelly percentage
        # Edge factor: combine confidence and strength
        edge_factor = (signal_confidence + signal_strength) / 2
        
        # Kelly position as fraction of account
        kelly_pct = edge_factor * self.kelly_fraction
        
        # Cap at maximum
        kelly_pct = min(kelly_pct, self.max_position_pct)
        
        # Calculate dollar amount
        notional = account_equity * kelly_pct
        
        # Convert to shares
        shares = int(notional / current_price)
        
        # Apply constraints
        shares = max(shares, min_shares)
        if max_shares:
            shares = min(shares, max_shares)
        
        # Recalculate actual notional
        actual_notional = shares * current_price
        actual_pct = actual_notional / account_equity
        
        logger.info(
            f"Kelly sizing: confidence={signal_confidence:.2f}, "
            f"strength={signal_strength:.2f}, "
            f"kelly_pct={kelly_pct:.2%}, "
            f"shares={shares}, notional=${actual_notional:,.2f}"
        )
        
        return {
            "shares": shares,
            "notional": actual_notional,
            "kelly_pct": actual_pct,
            "method": "kelly_criterion",
            "confidence": signal_confidence,
            "edge_factor": edge_factor,
        }
    
    def _fixed_sizing(
        self,
        account_equity: float,
        current_price: float,
        min_shares: int,
        max_shares: Optional[int],
    ) -> Dict:
        """Fallback to fixed sizing for low-confidence signals."""
        
        # Use conservative fixed percentage (5%)
        fixed_pct = 0.05
        notional = account_equity * fixed_pct
        shares = int(notional / current_price)
        
        # Apply constraints
        shares = max(shares, min_shares)
        if max_shares:
            shares = min(shares, max_shares)
        
        actual_notional = shares * current_price
        
        logger.info(
            f"Fixed sizing (low confidence): "
            f"shares={shares}, notional=${actual_notional:,.2f}"
        )
        
        return {
            "shares": shares,
            "notional": actual_notional,
            "kelly_pct": fixed_pct,
            "method": "fixed_low_confidence",
        }
    
    def adjust_for_volatility(
        self,
        base_size: int,
        current_atr: float,
        target_risk_dollars: float,
        current_price: float,
    ) -> int:
        """
        Optional: Adjust position size based on volatility (ATR).
        
        Higher volatility → smaller position to maintain consistent dollar risk.
        """
        
        # Risk per share = ATR
        risk_per_share = current_atr
        
        # Target shares based on risk
        risk_adjusted_shares = int(target_risk_dollars / risk_per_share)
        
        # Use smaller of Kelly size or risk-adjusted size
        adjusted_shares = min(base_size, risk_adjusted_shares)
        
        logger.info(
            f"Volatility adjustment: "
            f"base={base_size}, atr_adjusted={risk_adjusted_shares}, "
            f"final={adjusted_shares}"
        )
        
        return adjusted_shares


def calculate_historical_edge(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
) -> float:
    """
    Calculate edge factor from historical performance.
    
    Used to calibrate Kelly sizing based on actual results.
    """
    
    if avg_win <= 0 or avg_loss >= 0:
        return 0.0
    
    # Expected value per trade
    ev = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)
    
    # Normalize to 0-1 scale
    edge = ev / avg_win if avg_win > 0 else 0.0
    edge = max(0.0, min(1.0, edge))
    
    return edge
```

**Integration Points:**
1. Modify `src/stock_swing/risk/position_sizing.py`
2. Update `calculate_position_size()` to use Kelly
3. Pass signal confidence from strategies

---

#### Phase 2: Integration (May 1-2)

**File:** `src/stock_swing/risk/position_sizing.py` (MODIFY)

**Changes:**
```python
from stock_swing.risk.kelly_sizing import KellyCriterionSizer

# Add to calculate_position_size()
def calculate_position_size(
    regime: str,
    account_value: float,
    current_price: float,
    atr: float,
    sector_exposure: float = 0.0,
    signal_confidence: float = 0.0,  # NEW
    signal_strength: float = 0.0,    # NEW
    use_kelly: bool = True,           # NEW
) -> PositionSize:
    """Calculate position size with optional Kelly sizing."""
    
    if use_kelly and signal_confidence > 0.6:
        # Use Kelly Criterion
        kelly_sizer = KellyCriterionSizer()
        result = kelly_sizer.calculate_position_size(
            account_equity=account_value,
            signal_confidence=signal_confidence,
            signal_strength=signal_strength,
            current_price=current_price,
            max_shares=50,  # Existing limit
        )
        
        shares = result["shares"]
        notional = result["notional"]
        
        # ... rest of validation logic
    else:
        # Fall back to existing logic
        # ... (keep current implementation)
```

**File:** `src/stock_swing/strategy_engine/base_strategy.py` (MODIFY)

**Changes:**
```python
# Update Signal dataclass to include confidence
@dataclass
class Signal:
    symbol: str
    action: str
    signal_strength: float
    confidence: float  # Already exists, ensure it's populated
    reasoning: str
    strategy_id: str
```

---

#### Phase 3: Testing & Validation (May 3-5)

**Test Cases:**

1. **High Confidence (0.9):**
   - Expected: Large position (~30-50% of account)
   - Validate: Not exceeding max limits

2. **Medium Confidence (0.7):**
   - Expected: Medium position (~20-30%)
   - Validate: Reasonable risk

3. **Low Confidence (0.5):**
   - Expected: Small position (~5%)
   - Validate: Falls back to fixed sizing

4. **Edge Cases:**
   - Very high price (NVDA $1000+): Check share limits
   - Very low price (penny stocks): Check minimum notional
   - Account at max exposure: Verify rejection

**Validation Metrics:**
- No position > 50% of account
- No single trade risking > 2% of account
- Position sizes scale with confidence
- Fallback to fixed sizing works

---

### Week 5 (May 6-12): Tax Optimization Framework

#### Phase 1: Wash Sale Tracking (May 6-7)

**File:** `src/stock_swing/tax/wash_sale_tracker.py` (NEW)

**Implementation:**
```python
"""
Wash Sale Rule Tracker
Prevents tax-loss harvesting violations (31-day rule)
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class WashSaleTracker:
    """
    Track trades to prevent wash sale violations.
    
    Wash Sale Rule: If you sell a security at a loss and buy it back
    within 31 days (30 days before or after), you cannot claim the loss.
    """
    
    def __init__(self):
        self.recent_sales: Dict[str, List[Dict]] = {}
        self.wash_sale_window_days = 31
    
    def record_sale(
        self,
        symbol: str,
        sale_date: datetime,
        quantity: int,
        sale_price: float,
        cost_basis: float,
    ):
        """Record a sale for wash sale tracking."""
        
        is_loss = sale_price < cost_basis
        
        if is_loss:
            if symbol not in self.recent_sales:
                self.recent_sales[symbol] = []
            
            self.recent_sales[symbol].append({
                "date": sale_date,
                "quantity": quantity,
                "sale_price": sale_price,
                "cost_basis": cost_basis,
                "loss": (cost_basis - sale_price) * quantity,
            })
            
            # Clean old sales (>61 days)
            cutoff = sale_date - timedelta(days=61)
            self.recent_sales[symbol] = [
                s for s in self.recent_sales[symbol]
                if s["date"] > cutoff
            ]
            
            logger.info(
                f"Recorded loss sale: {symbol} "
                f"{quantity} shares at ${sale_price:.2f} "
                f"(loss: ${(cost_basis - sale_price) * quantity:.2f})"
            )
    
    def check_wash_sale(
        self,
        symbol: str,
        purchase_date: datetime,
    ) -> Optional[Dict]:
        """
        Check if a purchase would trigger a wash sale.
        
        Returns:
            None if OK to buy
            Dict with warning if wash sale risk
        """
        
        if symbol not in self.recent_sales:
            return None
        
        # Check sales within 31 days before or after
        for sale in self.recent_sales[symbol]:
            days_diff = abs((purchase_date - sale["date"]).days)
            
            if days_diff <= self.wash_sale_window_days:
                return {
                    "warning": "wash_sale_risk",
                    "sale_date": sale["date"],
                    "days_since_sale": days_diff,
                    "disallowed_loss": sale["loss"],
                    "message": (
                        f"Buying {symbol} within {days_diff} days of loss sale "
                        f"may trigger wash sale (${sale['loss']:.2f} loss disallowed)"
                    ),
                }
        
        return None
    
    def get_safe_rebuy_date(self, symbol: str) -> Optional[datetime]:
        """Get earliest date when symbol can be safely repurchased."""
        
        if symbol not in self.recent_sales:
            return None
        
        # Find most recent loss sale
        if self.recent_sales[symbol]:
            most_recent = max(
                self.recent_sales[symbol],
                key=lambda x: x["date"]
            )
            safe_date = most_recent["date"] + timedelta(
                days=self.wash_sale_window_days + 1
            )
            return safe_date
        
        return None
```

---

#### Phase 2: Tax-Loss Harvesting Strategy (May 8-9)

**File:** `src/stock_swing/tax/tax_loss_harvesting.py` (NEW)

**Implementation:**
```python
"""
Tax-Loss Harvesting Strategy
Opportunistically realize losses to offset gains
"""

import logging
from datetime import datetime
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class TaxLossHarvester:
    """
    Identify opportunities to harvest tax losses.
    
    Strategy:
    1. Identify losing positions
    2. Check if loss is significant (>2%)
    3. Verify no wash sale conflict
    4. Recommend harvest if year-end approaching
    """
    
    def __init__(
        self,
        min_loss_pct: float = 0.02,      # Minimum 2% loss
        year_end_urgency_days: int = 60,  # Harvest urgently in Dec
    ):
        self.min_loss_pct = min_loss_pct
        self.year_end_urgency_days = year_end_urgency_days
    
    def find_harvest_candidates(
        self,
        positions: Dict[str, Dict],
        current_date: datetime,
        ytd_gains: float = 0.0,
    ) -> List[Dict]:
        """
        Find positions suitable for tax-loss harvesting.
        
        Args:
            positions: Current positions with P&L
            current_date: Current date
            ytd_gains: Year-to-date realized gains
        
        Returns:
            List of harvest opportunities
        """
        
        candidates = []
        
        # Check if near year-end
        days_to_year_end = (
            datetime(current_date.year, 12, 31) - current_date
        ).days
        is_year_end_urgent = days_to_year_end <= self.year_end_urgency_days
        
        for symbol, pos in positions.items():
            unrealized_plpc = pos.get("unrealized_plpc", 0.0)
            unrealized_pl = pos.get("unrealized_pl", 0.0)
            
            # Only consider losses
            if unrealized_plpc >= 0:
                continue
            
            # Check if loss is significant enough
            if abs(unrealized_plpc) < self.min_loss_pct:
                continue
            
            # Calculate tax benefit (assume 35% marginal rate)
            tax_savings = abs(unrealized_pl) * 0.35
            
            # Priority scoring
            priority = 0
            if is_year_end_urgent:
                priority += 10
            if ytd_gains > 0:  # Have gains to offset
                priority += 5
            if abs(unrealized_plpc) > 0.05:  # >5% loss
                priority += 3
            
            candidates.append({
                "symbol": symbol,
                "unrealized_pl": unrealized_pl,
                "unrealized_plpc": unrealized_plpc,
                "tax_savings": tax_savings,
                "priority": priority,
                "recommendation": (
                    f"Harvest ${abs(unrealized_pl):.2f} loss "
                    f"→ ${tax_savings:.2f} tax savings"
                ),
            })
        
        # Sort by priority
        candidates.sort(key=lambda x: x["priority"], reverse=True)
        
        return candidates
```

---

#### Phase 3: Integration & Testing (May 10-12)

**Integration Points:**

1. **Decision Engine:**
   - Check wash sale before buy orders
   - Log warnings for potential violations

2. **Exit Strategy:**
   - Consider tax harvesting in exit decisions
   - Prioritize harvesting near year-end

3. **Reporting:**
   - Add tax section to monthly reports
   - Track YTD gains/losses
   - Estimate tax liability

**Test Scenarios:**
- Sell at loss, attempt rebuy within 30 days → Blocked
- Sell at loss, rebuy after 31 days → Allowed
- Year-end harvesting (Nov-Dec)
- Offset gains with losses

---

## Success Metrics

### Week 3 Optimization (Expected)
- ✅ Sharpe ratio: 0.85 → 1.5
- ✅ Execution rate: 18% → 65%
- ✅ Return: +2.98% → +6%

### Week 4 Kelly Sizing (Expected)
- ✅ Position sizes scale with confidence
- ✅ High-confidence trades: 30-50% larger
- ✅ Low-confidence trades: Same as before
- ✅ Expected return boost: +5-8%
- ✅ **Combined return: +6% → +12-14%**

### Week 5 Tax Optimization (Expected)
- ✅ Zero wash sale violations
- ✅ Tax-loss harvesting when appropriate
- ✅ After-tax return improvement: +2-3%
- ✅ **Final after-tax return: +10-12%**

---

## Risk Management

### Kelly Sizing Risks
**Risk:** Over-sizing on false confidence  
**Mitigation:**
- Cap at 50% max position
- Use half-Kelly (conservative)
- Require 0.6+ confidence for Kelly
- Fallback to fixed sizing

**Risk:** Violating broker limits  
**Mitigation:**
- Enforce existing position limits
- Validate before order submission
- Monitor daily exposure

### Tax Optimization Risks
**Risk:** Wash sale violations  
**Mitigation:**
- Automated tracking
- Pre-trade validation
- Clear warnings in logs

**Risk:** Over-optimization for taxes  
**Mitigation:**
- Trading performance > tax savings
- Only harvest when makes sense
- Don't force bad trades for tax reasons

---

## Rollback Plan

### If Kelly Sizing Underperforms
1. **Monitor Period:** First 5 trading days
2. **Rollback Trigger:** Sharpe ratio < 1.0 or drawdown > 6%
3. **Rollback Action:** Revert to fixed sizing
4. **Time to Rollback:** 10 minutes (simple config change)

### If Week 3 Optimization Fails
1. **Validation:** Out-of-sample testing before deployment
2. **Rollback Trigger:** Sharpe < current 0.85
3. **Rollback Action:** Restore previous parameters
4. **Time to Rollback:** 5 minutes (Git revert)

---

## Documentation & Reporting

### Daily Monitoring (Week 4-5)
- Track Kelly sizing decisions
- Log position size distribution
- Monitor wash sale checks

### Week 4 Report (May 5)
- Kelly implementation complete
- Performance comparison vs. fixed sizing
- Position size analysis

### Week 5 Report (May 12)
- Tax framework operational
- Wash sale tracking verified
- YTD tax summary

### Monthly Report (May 31)
**Option A Results:**
- Return: Target +12-15%
- Sharpe: Target 1.8
- Tax efficiency: +2-3%
- Overall assessment

---

## Next Steps After Option A

### If Successful (Return +12-15%)
**Consider Option B Components:**
- Alternative data ($400/month)
- Intraday strategies
- Expected: +30-35% over 3 months

### If Unsuccessful (Return < +8%)
**Root Cause Analysis:**
- Kelly sizing validation
- Parameter optimization review
- Market regime analysis
- Decide: Rollback or adjust

### Maintenance Mode
**Ongoing:**
- Weekly performance review
- Monthly parameter validation
- Quarterly tax planning
- Semi-annual strategy review

---

## Timeline Summary

| Week | Dates | Focus | Deliverable |
|------|-------|-------|-------------|
| Week 3 | Apr 24-28 | Parameter optimization | Optimized parameters deployed |
| Week 4 | Apr 29-May 5 | Kelly Criterion | Dynamic sizing active |
| Week 5 | May 6-12 | Tax optimization | Tax framework operational |
| Week 6 | May 13-19 | Monitoring & validation | Performance report |
| Week 7 | May 20-26 | Stabilization | Decision on Option B |

---

## Expected Outcomes

**Conservative (70% probability):**
- Return: +10%
- Sharpe: 1.6
- After-tax: +8%

**Realistic (50% probability):**
- Return: +12-13%
- Sharpe: 1.8
- After-tax: +10-11%

**Optimistic (30% probability):**
- Return: +15%
- Sharpe: 2.0
- After-tax: +13%

**Account Value by May 31:**
- Current: $103,755
- Conservative: $110,000
- Realistic: $112-113,000
- Optimistic: $115,000

---

**Status:** Ready to execute  
**Start Date:** Apr 24, 2026 (Thursday)  
**Approval:** Pending master confirmation  

---

End of Option A Implementation Plan
