# RISK_POLICY.md

## 1. Risk stance
The system is deny-first.
No signal is allowed to become actionable unless it passes explicit risk checks.

## 2. Initial hard rules
- Unknown runtime mode -> deny
- Missing critical data -> deny
- Stale broker price data -> deny
- Duplicate active decision for same symbol/strategy/window -> deny
- Daily realized loss limit breached -> deny new entries
- Max symbol allocation breached -> deny
- Max concurrent positions breached -> deny
- Market closed or restricted window -> deny

## 3. Initial recommended paper limits
- Max position count: 5
- Max per-symbol notional: 20% of account equity
- Max daily realized loss stop: 2%
- Max new entries per day per symbol: 1
- Cooldown after stop-out: same day no re-entry by default

## 4. Event freeze
During critical macro events, new entries may be blocked until post-event rules confirm stability.
Applicable examples:
- CPI
- FOMC decision
- FOMC press conference
- Non-Farm Payrolls

## 5. Data freshness requirements
- broker quotes/bars: strategy-specific freshness threshold
- macro data: must align with latest intended release cycle
- filing data: must be timestamped and source-attributed
- fundamental event data: must not be stale beyond configured window
