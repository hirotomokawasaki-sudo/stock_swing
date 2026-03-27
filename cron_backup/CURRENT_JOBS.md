# Current Cron Jobs Status

## Overview
- **Total Jobs**: 2
- **Last Updated**: 2026-03-27 17:42 JST
- **Backup Location**: `~/stock_swing/cron_backup/jobs.json`

## Active Jobs

### 1. Data Collection
- **ID**: `4d76bf16-bd96-4ff3-b5db-a735f62c2d35`
- **Name**: `stock_swing_data_collection`
- **Schedule**: Every 2 hours at X:40 (e.g., 0:40, 2:40, 4:40...)
- **Cron Expression**: `40 */2 * * *`
- **Timezone**: Asia/Tokyo
- **Frequency**: 12 times/day
- **Timeout**: 600 seconds (10 minutes)
- **Status**: ✅ Enabled
- **Next Run**: 2026-03-27 18:40:00 JST

**Purpose**: Collect data from all sources (Finnhub, FRED, SEC, Broker)
**Targets**: AAPL, MSFT, GOOGL, AMZN, TSLA

**Command**:
```bash
cd ~/stock_swing && \
source venv/bin/activate && \
python -m stock_swing.cli.collect_data --symbols AAPL,MSFT,GOOGL,AMZN,TSLA
```

---

### 2. Data Analysis
- **ID**: `630f2a52-6d11-4635-9066-776d63901859`
- **Name**: `stock_swing_data_analysis`
- **Schedule**: Every 4 hours at 0:00, 4:00, 8:00, 12:00, 16:00, 20:00
- **Cron Expression**: `0 0,4,8,12,16,20 * * *`
- **Timezone**: Asia/Tokyo
- **Frequency**: 6 times/day
- **Timeout**: 900 seconds (15 minutes)
- **Status**: ✅ Enabled
- **Next Run**: 2026-03-27 20:00:00 JST

**Purpose**: Full analysis pipeline execution
**Targets**: AAPL, MSFT, GOOGL, AMZN, TSLA

**Pipeline**:
1. Normalize raw data → canonical records
2. Extract features (MacroRegime, EarningsEvent, PriceMomentum)
3. Generate signals (EventSwing, BreakoutMomentum strategies)
4. Create decisions (DecisionEngine + RiskValidator)
5. Generate reports

**Command**:
```bash
cd ~/stock_swing && \
source venv/bin/activate && \
python -m stock_swing.cli.analyze_data --symbols AAPL,MSFT,GOOGL,AMZN,TSLA
```

---

## Daily Schedule (JST)

```
Time    Job
------  -----------------------------------------------
00:00   📊 Data Analysis
00:40   📡 Data Collection
02:40   📡 Data Collection
04:00   📊 Data Analysis
04:40   📡 Data Collection
06:40   📡 Data Collection
08:00   📊 Data Analysis
08:40   📡 Data Collection
10:40   📡 Data Collection
12:00   📊 Data Analysis
12:40   📡 Data Collection
14:40   📡 Data Collection
16:00   📊 Data Analysis
16:40   📡 Data Collection
18:40   📡 Data Collection ← Next
20:00   📊 Data Analysis ← Next
20:40   📡 Data Collection
22:40   📡 Data Collection
```

**Total executions per day**: 18
- Collection: 12 times
- Analysis: 6 times

## Management Commands

### View Jobs
```bash
openclaw cron list
openclaw cron status
```

### Pause/Resume
```bash
# Pause data collection
openclaw cron update --id 4d76bf16-bd96-4ff3-b5db-a735f62c2d35 \
  --patch '{"enabled": false}'

# Resume data collection
openclaw cron update --id 4d76bf16-bd96-4ff3-b5db-a735f62c2d35 \
  --patch '{"enabled": true}'

# Pause data analysis
openclaw cron update --id 630f2a52-6d11-4635-9066-776d63901859 \
  --patch '{"enabled": false}'

# Resume data analysis
openclaw cron update --id 630f2a52-6d11-4635-9066-776d63901859 \
  --patch '{"enabled": true}'
```

### View Execution History
```bash
# Data collection history
openclaw cron runs --id 4d76bf16-bd96-4ff3-b5db-a735f62c2d35

# Data analysis history
openclaw cron runs --id 630f2a52-6d11-4635-9066-776d63901859
```

### Backup
```bash
# Manual backup
~/stock_swing/scripts/utils/backup_cron_jobs.sh

# Backup and commit to Git
~/stock_swing/scripts/utils/backup_cron_jobs.sh --auto-commit
```

## Future Jobs (Planned)

Based on `docs/operations/CRON_SCHEDULE.md`, the following jobs are planned:

1. **Performance Analysis** - Daily at 00:00
2. **Maintenance** - Daily at 01:00
3. **Macro Collection** - Daily at 02:00
4. **Market Collection** - Daily at 06:00
5. **Strategy Generation** - 3x daily (08:00, 15:00, 20:00)
6. **Decision Making** - 2x daily (09:00, 21:00)
7. **Market Prep** - Daily at 22:00
8. **Reconciliation** - Weekdays at 06:00

Use `~/stock_swing/scripts/utils/setup_optimal_crons.sh` to set up all planned jobs.

## Notes

- All jobs use `sessionTarget: isolated` for clean execution environments
- All jobs have `delivery.mode: announce` for notifications
- Jobs automatically retry on transient failures
- Logs are saved to `~/stock_swing/logs/`
- Cron jobs are backed up to Git at `~/stock_swing/cron_backup/jobs.json`

## API Keys Required

For jobs to work properly, configure API keys in `~/stock_swing/.env`:
- `FINNHUB_API_KEY` - Finnhub data
- `FRED_API_KEY` - FRED macro data
- `BROKER_API_KEY` - Alpaca broker
- `BROKER_API_SECRET` - Alpaca secret

---

**Last Review**: 2026-03-27 17:42 JST
**Next Review**: When adding new jobs or changing schedule
