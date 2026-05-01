# Alpaca Account Migration - 2026-05-01

## Summary

Migrated from Alpaca Paper Trading account `PA3K84BB63MJ` to new account `PA3T26AU8F7W`.

## Migration Details

### Old Account
- Account Number: `PA3K84BB63MJ`
- Account ID: `57cb5ae6-fd73-47bc-bcd3-d467c6d52ae8`
- Final Equity: $104,675
- Final Cash: $60,058
- Open Positions: 10
- Pattern Day Trader: Yes

### New Account
- Account Number: `PA3T26AU8F7W`
- Account ID: `2bf02097-8ccd-4f4f-93ce-1e2f5c33c5ed`
- Initial Equity: $1,000,000
- Initial Cash: $1,000,000
- Open Positions: 0
- Pattern Day Trader: No

## What Was Preserved

✅ **Learning Data (Continues to be used)**
- Strategy configurations (`config/strategy/`)
- Decision history (`data/decisions/`)
- Signal history (`data/signals/`)
- News data (`data/news/`)
- Benchmark data (`data/benchmarks/`)
- All machine learning models and parameters

## What Was Reset

🔄 **Account-Specific Data (Started fresh)**
- PnL Tracker state (`data/tracking/pnl_state.json`)
- Trading history (no trades in new account)
- Position tracking (no positions in new account)
- Account statistics

## Backup Location

Old account data backed up to:
```
data/archive/account_PA3K84BB63MJ_20260501/
├── audits/          (Audit logs and reports)
└── tracking/        (PnL state and trading history)
```

## Changes Made

### 1. Environment Variables (`.env`)
```bash
# Updated (not committed to git):
BROKER_API_KEY=PKOMHC5E5GCMU67ATYNRVRYAMT
BROKER_API_SECRET=HFUJryjshJFU3QhZZuKuaDwBi71AytP5J1wFH1ZuQj1d
BROKER_ACCOUNT_ID=2bf02097-8ccd-4f4f-93ce-1e2f5c33c5ed
```

### 2. PnL Tracker State
- Old state moved to `data/tracking/pnl_state.json.old`
- New state will be initialized automatically on first trade

### 3. Services
- Console server restarted with new credentials
- Successfully connected to new account
- Verified equity: $1,000,000

## Verification

### API Connection Test
```bash
✅ BrokerClient initialized
✅ fetch_account() successful
✅ Account equity: $1,000,000
✅ Account cash: $1,000,000
✅ fetch_positions() successful (0 positions)
```

### Dashboard API Test
```bash
✅ Dashboard API responding
✅ Account available: true
✅ Equity: $1,000,000
✅ Cash: $1,000,000
✅ Position count: 0
✅ Trading summary: 0 trades, 0.0 win rate (expected for new account)
```

## Impact on Strategy

### No Impact (Continues normally)
- Signal generation continues with learned models
- Exit strategies use same parameters
- Portfolio allocation rules remain unchanged
- Risk management thresholds unchanged

### Expected Behavior
- New trades will start fresh in new account
- Performance metrics will reset (0 trades initially)
- Win rate/return metrics will build up from zero
- Strategy optimization continues with historical learning data

## Notes

- **Learning Data Continuity**: All ML models, historical signals, and decision patterns are preserved
- **Performance Tracking**: Trading performance will start fresh, but strategy intelligence is retained
- **Capital Increase**: New account has significantly more capital ($1M vs $104K)
- **Day Trading**: New account is not flagged as PDT, allowing more flexibility

## Migration Date

- Date: 2026-05-01
- Time: 19:32 JST
- Migration Type: Account switch (preserving learning data)
- Status: ✅ Successful
