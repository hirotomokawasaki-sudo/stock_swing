# stock_swing Cron Schedule - Complete Automation

## 🎯 Overview

This document defines the complete cron schedule for stock_swing system automation, optimized for US market hours with daylight saving time and holiday support.

## 🏛️ US Market Hours Reference

### Trading Sessions (ET)
- **Pre-market**: 4:00 AM - 9:30 AM
- **Regular**: 9:30 AM - 4:00 PM
- **After-hours**: 4:00 PM - 8:00 PM

### JST Conversion
| Period | Summer (DST) | Winter (Standard) |
|--------|-------------|-------------------|
| Pre-market | 17:00-22:30 JST | 18:00-23:30 JST |
| Regular | 22:30-05:00 JST (next day) | 23:30-06:00 JST (next day) |
| After-hours | 05:00-09:00 JST (next day) | 06:00-10:00 JST (next day) |

### Daylight Saving Time
- **Summer Time**: 2nd Sunday of March to 1st Sunday of November
- **ET Offset**: JST - 13 hours (summer), JST - 14 hours (winter)

### US Market Holidays
Market is closed on:
- New Year's Day (Jan 1)
- MLK Jr. Day (3rd Monday in Jan)
- Presidents' Day (3rd Monday in Feb)
- Good Friday (Friday before Easter)
- Memorial Day (Last Monday in May)
- Juneteenth (Jun 19)
- Independence Day (Jul 4)
- Labor Day (1st Monday in Sep)
- Thanksgiving (4th Thursday in Nov)
- Christmas (Dec 25)

## 📊 Complete Cron Schedule

### Daily Timeline (JST, Summer Time)

```
00:00 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      📊 PERFORMANCE ANALYSIS (Daily)
      - PerformanceAnalyzer
      - ParameterRecommender  
      - RecommendationReporter
      - Generate daily reports
      Duration: ~15 minutes

01:00 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      🧹 MAINTENANCE (Daily)
      - Clean old data
      - Rotate logs
      - Backup databases
      Duration: ~10 minutes

02:00 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      📡 DATA COLLECTION - Macro/Fundamental
      - FREDClient (macro indicators)
      - SECClient (filings, disclosures)
      Duration: ~10 minutes

02:20 ──────────────────────────────────────────
      📝 NORMALIZATION
      - FredNormalizer
      - SecNormalizer
      Duration: ~5 minutes

03:00 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      🔍 FEATURE EXTRACTION - Macro
      - MacroRegimeFeature
      Duration: ~5 minutes

06:00 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      📡 DATA COLLECTION - Market Data
      - FinnhubClient (earnings calendar, sentiment)
      - BrokerClient (positions check)
      Duration: ~10 minutes

06:20 ──────────────────────────────────────────
      📝 NORMALIZATION
      - FinnhubNormalizer
      - BrokerNormalizer
      Duration: ~5 minutes

07:00 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      🔍 FEATURE EXTRACTION - Events & Momentum
      - EarningsEventFeature
      - PriceMomentumFeature
      Duration: ~10 minutes

08:00 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      🎯 STRATEGY GENERATION
      - EventSwingStrategy
      - BreakoutMomentumStrategy
      - SignalSummarizer
      Duration: ~10 minutes

09:00 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      💡 DECISION MAKING (Pre-market)
      - DecisionEngine
      - RiskValidator
      - KillSwitch check
      - DecisionSummarizer
      Duration: ~5 minutes

10:00-18:00 ═════════════════════════════════════
      📡 PERIODIC DATA COLLECTION (Every 2 hours)
      - 10:00, 12:00, 14:00, 16:00, 18:00
      - FinnhubClient, BrokerClient
      - Quick updates only

18:00 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      📡 DATA COLLECTION - Pre-Market Prep
      - BrokerClient (final position check)
      - FinnhubClient (late-breaking news)
      Duration: ~10 minutes

20:00 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      📊 ANALYSIS UPDATE
      - Feature extraction
      - Strategy update
      Duration: ~15 minutes

21:00 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      🎯 DECISION UPDATE (Pre-market decision)
      - DecisionEngine
      - RiskValidator
      - Final pre-market decisions
      Duration: ~5 minutes

22:00 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      ⚠️  MARKET PREP
      - System health check
      - Kill switch status
      - Connectivity test
      Duration: ~5 minutes

22:30 ═══════════════════════════════════════════
      ⚡ MARKET OPEN (Summer Time)
      - Regular hours begin
      - Monitoring active
      
23:00-05:00 ═════════════════════════════════════
      🔴 LIVE MONITORING (Market Hours)
      - Real-time data collection (every 15 min)
      - Position monitoring
      - Risk checks
      - NO automatic execution (paper mode only)

05:00 ═══════════════════════════════════════════
      ⚡ MARKET CLOSE (Summer Time)
      - Regular hours end
      - After-hours begins

06:00 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      🔄 RECONCILIATION (After market close)
      - Reconciler
      - Compare orders vs fills
      - Position verification
      - ExecutionSummarizer
      Duration: ~10 minutes

09:00 ═══════════════════════════════════════════
      ⚡ AFTER-HOURS CLOSE (Summer Time)
      - Extended hours end
      - EOD data finalization
```

## 🤖 Agent Execution Groups

### Group 1: Data Collection (4 agents)
**Schedule**: Every 2 hours (offset at :40 for low API load)
- FinnhubClient
- FREDClient  
- SECClient
- BrokerClient

### Group 2: Data Processing (5 agents)
**Schedule**: 20 minutes after collection
- RawIngestor
- FinnhubNormalizer
- FredNormalizer
- SecNormalizer
- BrokerNormalizer

### Group 3: Feature Extraction (3 agents)
**Schedule**: 4 times daily (03:00, 07:00, 14:00, 20:00)
- MacroRegimeFeature
- EarningsEventFeature
- PriceMomentumFeature

### Group 4: Strategy Generation (2 agents)
**Schedule**: 3 times daily (08:00, 15:00, 20:30)
- EventSwingStrategy
- BreakoutMomentumStrategy

### Group 5: Decision Making (2 agents)
**Schedule**: 2 times daily (09:00, 21:00)
- DecisionEngine
- RiskValidator

### Group 6: Order Execution (3 agents)
**Schedule**: On-demand (manual trigger only in current phase)
- PaperExecutor (automatic in paper mode)
- LiveGuardedExecutor (manual approval required)
- ProductionExecutor (disabled in current phase)

### Group 7: Reconciliation (1 agent)
**Schedule**: Once daily after market close (06:00)
- Reconciler

### Group 8: Performance Analysis (3 agents)
**Schedule**: Once daily (00:00)
- PerformanceAnalyzer
- ParameterRecommender
- SafeRangeValidator

### Group 9: Human Interface (4 agents)
**Schedule**: After each major pipeline stage
- SignalSummarizer (after strategy generation)
- DecisionSummarizer (after decision making)
- ExecutionSummarizer (after execution)
- RecommendationReporter (after performance analysis)

### Group 10: Safety & Audit (3 agents)
**Schedule**: Always active / on-demand
- RiskValidator (before every decision)
- KillSwitch (checked before execution)
- AuditLogger (logs all operations)

## 📅 Cron Job Definitions

### Job 1: Performance Analysis
```yaml
name: stock_swing_performance_analysis
schedule: "0 0 * * *"  # Daily at 00:00 JST
timeout: 900s (15 min)
```

### Job 2: Maintenance
```yaml
name: stock_swing_maintenance
schedule: "0 1 * * *"  # Daily at 01:00 JST
timeout: 600s (10 min)
```

### Job 3: Macro Data Collection
```yaml
name: stock_swing_macro_collection
schedule: "0 2 * * *"  # Daily at 02:00 JST
timeout: 600s (10 min)
```

### Job 4: Macro Feature Extraction
```yaml
name: stock_swing_macro_features
schedule: "0 3 * * *"  # Daily at 03:00 JST
timeout: 300s (5 min)
```

### Job 5: Market Data Collection
```yaml
name: stock_swing_market_collection
schedule: "0 6 * * *"  # Daily at 06:00 JST
timeout: 600s (10 min)
```

### Job 6: Event Feature Extraction
```yaml
name: stock_swing_event_features
schedule: "0 7 * * *"  # Daily at 07:00 JST
timeout: 600s (10 min)
```

### Job 7: Strategy Generation
```yaml
name: stock_swing_strategy_generation
schedule: "0 8,15,20 * * *"  # 3x daily
timeout: 600s (10 min)
```

### Job 8: Decision Making
```yaml
name: stock_swing_decision_making
schedule: "0 9,21 * * *"  # 2x daily (pre-market)
timeout: 300s (5 min)
```

### Job 9: Periodic Data Updates
```yaml
name: stock_swing_periodic_updates
schedule: "40 */2 * * *"  # Every 2 hours at :40
timeout: 600s (10 min)
```

### Job 10: Pre-Market Prep
```yaml
name: stock_swing_premarket_prep
schedule: "0 18 * * *"  # Daily at 18:00 JST
timeout: 600s (10 min)
```

### Job 11: Market Prep Check
```yaml
name: stock_swing_market_prep
schedule: "0 22 * * *"  # Daily at 22:00 JST
timeout: 300s (5 min)
```

### Job 12: Market Close Reconciliation
```yaml
name: stock_swing_reconciliation
schedule: "0 6 * * *"  # Daily at 06:00 JST (after market close)
timeout: 600s (10 min)
```

## 🔧 Winter Time Adjustments

When DST ends (1st Sunday of November), adjust these jobs by +1 hour:
- Market Prep: 22:00 → 23:00
- Pre-Market Decision: 21:00 → 22:00
- After-Market Reconciliation: 06:00 → 07:00

**Recommendation**: Use market calendar utility to auto-adjust or run both schedules with market open check.

## 🚨 Holiday Handling

On US market holidays:
- Skip all market-hours jobs (22:30-09:00)
- Run maintenance and analysis as usual
- Data collection runs but may return empty results
- Use `is_us_holiday()` utility before execution

## 📊 Monitoring & Alerts

### Critical Alerts
- Decision making failures
- Kill switch activation
- Reconciliation discrepancies
- API rate limit hits

### Info Alerts  
- Performance analysis reports
- Parameter recommendations
- Daily execution summary

## 🔄 Backup & Recovery

### Automated Backups
- Cron jobs: After every change (via backup_cron_jobs.sh)
- Data: Daily at 01:00
- Logs: Rotated daily, kept for 30 days
- Configurations: Git-tracked

### Recovery Procedure
1. Restore cron jobs from `cron_backup/jobs.json`
2. Verify data integrity
3. Check kill switch status
4. Resume operations

---

**Last Updated**: 2026-03-27
**Next Review**: Before DST transition (March/November)
