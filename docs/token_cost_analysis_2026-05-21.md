# Token Cost Analysis - 2026-05-21

## Current Cron Jobs Analysis

### Daily Execution Frequency

| Job | Frequency | Count/Day | Exec Time | Model | Priority |
|-----|-----------|-----------|-----------|-------|----------|
| **reconciliation_market_hours** | Every 30min (20:00-06:59) | ~22 | 23s | GPT-5.4 | Medium |
| **reconciliation_off_hours** | Every 1h (07:00-19:00) | 13 | 27s | GPT-5.4 | Low |
| **news_collection** | Every 2h | 12 | 27s | GPT-5.4 | Low |
| **paper_demo_premarket** | Daily 23:00 (Mon-Fri) | 1 | 221s | GPT-5.4 | High |
| **paper_demo_market_open** | Daily 23:05 (Mon-Fri) | 1 | 175s | GPT-5.4 | High |
| **paper_demo_midday** | Daily 02:00 (Tue-Sat) | 1 | 170s | GPT-5.4 | High |
| **paper_demo_market_close** | Daily 05:55 (Tue-Sat) | 1 | 244s | GPT-5.4 | High |
| **daily_audit** | Daily 06:00 | 1 | 36s | GPT-5.4 | Medium |
| **daily_report_morning** | Daily 09:00 (Mon-Fri) | 0.7 | 36s | GPT-5.4 | Low |
| **update_price_overrides** | Daily 22:00 | 1 | 51s | GPT-5.4 | High |
| **weekly_full_audit** | Weekly Mon 07:00 | 0.14 | 34s | GPT-5.4 | Low |

### Total Executions per Day
- **Reconciliation**: 35 runs/day (22 + 13)
- **News collection**: 12 runs/day
- **Paper demo**: 4 runs/day (平日のみ)
- **Audit/Report**: 2 runs/day
- **Total**: ~53 runs/day

---

## Token Cost Estimation (Rough)

Assumptions:
- lightContext=true: ~10K tokens/run
- Full context: ~50K tokens/run
- GPT-5.4: $5/M input tokens

### Current Daily Cost (平日)

| Category | Runs | Tokens/Run | Total Tokens | Cost |
|----------|------|------------|--------------|------|
| Reconciliation | 35 | 10K | 350K | $1.75 |
| News collection | 12 | 10K | 120K | $0.60 |
| Paper demo | 4 | 10K | 40K | $0.20 |
| Audit/Report | 2 | 10K | 20K | $0.10 |
| **Total** | **53** | - | **530K** | **$2.65** |

**Note**: This is a conservative estimate. Actual cost depends on:
- Actual prompt sizes
- Tool output sizes
- Model response lengths

If actual cost is $10-15/day, the multiplier is ~4-6x higher than baseline.

---

## Cost Reduction Proposals

### Option A: Aggressive (Target: -60% token usage)

1. **News collection: Every 2h → Every 4h** (-50%, -6 runs/day)
   - Savings: $0.30/day
   - Impact: Minimal (news isn't critical for real-time trading)

2. **Reconciliation off-hours: Every 1h → Every 3h** (-67%, -9 runs/day)
   - Savings: $0.45/day
   - Impact: Low (off-hours activity is minimal)

3. **Reconciliation market-hours: Every 30min → Every 1h** (-50%, -11 runs/day)
   - Savings: $0.55/day
   - Impact: Medium (delayed order tracking)

4. **Paper demo: 4 runs → 2 runs** (premarket + market_close only)
   - Savings: $0.10/day
   - Impact: Medium (fewer trading opportunities)

**Total reduction: -26 runs/day (-49%)**
**Estimated savings: ~$1.40/day (baseline), ~$5-8/day (actual)**

---

### Option B: Moderate (Target: -40% token usage)

1. **News collection: Every 2h → Every 3h** (-33%, -4 runs/day)
   - Savings: $0.20/day
   - Impact: Minimal

2. **Reconciliation off-hours: Every 1h → Every 2h** (-50%, -6.5 runs/day)
   - Savings: $0.33/day
   - Impact: Low

3. **Paper demo: 4 runs → 3 runs** (remove midday)
   - Savings: $0.05/day
   - Impact: Low (midday is less volatile)

**Total reduction: -11.5 runs/day (-22%)**
**Estimated savings: ~$0.58/day (baseline), ~$2-4/day (actual)**

---

### Option C: Conservative (Target: -20% token usage)

1. **News collection: Every 2h → Every 3h** (-33%, -4 runs/day)
   - Savings: $0.20/day

2. **Reconciliation off-hours: Disable completely** (-100%, -13 runs/day)
   - Savings: $0.65/day
   - Impact: Low (can rely on market-hours + daily audit)

**Total reduction: -17 runs/day (-32%)**
**Estimated savings: ~$0.85/day (baseline), ~$3-5/day (actual)**

---

## Additional Optimizations

### 1. Model Downgrade for Low-Priority Jobs

Switch to Claude Sonnet 4 (cheaper) for:
- News collection
- Reconciliation (both)
- Daily report

**Estimated savings: 20-30% on those jobs**

### 2. Direct Python Execution (No Agent)

Jobs that don't need LLM intervention:
- `update_price_overrides` (already shell script)
- `daily_audit` (can be shell script)
- `news_collection` (can be direct Python)

Convert these to direct cron → Python execution:
- No agent overhead
- No token cost
- **Savings: ~$0.90/day**

---

## Recommended Action Plan

### Phase 1 (Immediate - This Week)
1. ✅ **Reconciliation off-hours: Disable**
   - Savings: $0.65/day baseline, ~$3/day actual
   - Risk: Very low (daily audit catches issues)

2. ✅ **News collection: Every 2h → Every 4h**
   - Savings: $0.30/day baseline, ~$1.5/day actual
   - Risk: Minimal (news lag is acceptable)

**Phase 1 Total: ~$4.5/day savings**

### Phase 2 (Next Week)
3. **Reconciliation market-hours: Every 30min → Every 1h**
   - Savings: $0.55/day baseline, ~$2.5/day actual
   - Monitor for any order tracking delays

4. **Convert to direct Python execution:**
   - `news_collection`
   - `daily_audit`
   - `update_price_overrides`
   - Savings: ~$0.90/day baseline, ~$4/day actual

**Phase 2 Total: ~$6.5/day additional savings**

---

## Total Savings Projection

- **Phase 1**: $4.5/day → $135/month
- **Phase 1 + 2**: $11/day → $330/month

If current cost is $10-15/day ($300-450/month):
- Phase 1 alone → **$6-10/day** ($180-300/month)
- Phase 1 + 2 → **$4-7/day** ($120-210/month) ✅ Target achieved

---

## Monitoring Plan

After implementing changes:
1. Track daily token usage via OpenClaw logs
2. Monitor for:
   - Missed order fills
   - Delayed reconciliation
   - News coverage gaps
3. Adjust thresholds if issues arise

---

---

## Phase 2 Implementation Plan (実施予定: 2026-05-28)

### Prerequisites
- Phase 1 を1週間運用し、問題がないことを確認
- Daily token usage が予想通り削減されていることを確認

### Task 1: Reconciliation market-hours の頻度削減

**Current:**
```yaml
jobId: 32c3be71-3e86-470f-92e1-f50d8c77d533
schedule: "*/30 20-23,0-6 * * *"  # Every 30 minutes
runs: 22/day
```

**Proposed:**
```yaml
schedule: "0 20-23,0-6 * * *"  # Every 1 hour
runs: 11/day
reduction: -11 runs/day (-50%)
```

**Implementation:**
```bash
openclaw cron update --id 32c3be71-3e86-470f-92e1-f50d8c77d533 \
  --patch '{"schedule": {"kind": "cron", "expr": "0 20-23,0-6 * * *", "tz": "Asia/Tokyo"}}'
```

**Savings:** ~$2.5/day

**Risk:** Medium
- Order tracking が最大1時間遅れる
- Filled orders の記録が遅延する可能性

**Monitoring:**
- Order fill から reconciliation までの遅延時間
- Missed fills の有無
- User からの「注文が反映されない」報告

---

### Task 2: Direct Python Execution への変換

#### 2-1. News Collection

**Current:**
- Agent-based cron job
- Tokens: ~10K/run × 6 runs/day = 60K/day

**Proposed:**
Direct Python execution via system cron:

```bash
# Add to system crontab (or launchd)
0 */4 * * * cd ~/stock_swing && source venv/bin/activate && \
  python -u -m stock_swing.cli.collect_data --sources finnhub \
  --symbols MRVL,CIEN,DELL,RBRK,PLTR,NOW,INTU,NBIS >> ~/stock_swing/logs/news_collection.log 2>&1
```

**Then disable OpenClaw cron:**
```bash
openclaw cron update --id 0a5ae126-cc03-44af-b4a8-b12b9821bd6f --patch '{"enabled": false}'
```

**Savings:** ~$0.30/day (full token elimination)

---

#### 2-2. Daily Audit

**Current:**
- Job: `stock_swing_daily_audit`
- Agent-based execution

**Proposed:**
```bash
# System cron
0 6 * * * cd ~/stock_swing && ./scripts/cron/run_audit.sh >> ~/stock_swing/logs/audit.log 2>&1
```

**Disable OpenClaw cron:**
```bash
# Find job ID first
openclaw cron list | grep daily_audit
openclaw cron update --id <JOB_ID> --patch '{"enabled": false}'
```

**Savings:** ~$0.10/day

---

#### 2-3. Update Price Overrides

**Current:**
- Job: `stock_swing_update_price_overrides`
- Already using shell script, but via agent

**Proposed:**
```bash
# System cron
0 22 * * * cd ~/stock_swing && ./scripts/cron/update_price_overrides.sh >> ~/stock_swing/logs/price_overrides.log 2>&1
```

**Disable OpenClaw cron:**
```bash
openclaw cron update --id 46c13997-20ef-43d5-bb39-f0e710c45ede --patch '{"enabled": false}'
```

**Savings:** ~$0.20/day

---

### Phase 2 Total Savings

| Task | Runs Reduced | Token Savings | Cost Savings |
|------|--------------|---------------|-------------|
| Reconciliation market-hours | -11/day | ~110K | ~$2.5/day |
| News collection (direct) | -6/day | ~60K | ~$0.30/day |
| Daily audit (direct) | -1/day | ~10K | ~$0.10/day |
| Price overrides (direct) | -1/day | ~10K | ~$0.20/day |
| **Total** | **-19/day** | **~190K** | **~$3.1/day** |

**Combined Phase 1 + 2:**
- Runs reduced: -38/day (from 53 to 15)
- Cost reduction: ~$7.6/day (baseline), **~$11/day (actual)**
- **Target achieved: $4-7/day** ✅

---

### Implementation Checklist

#### Pre-implementation (1 week before)
- [ ] Verify Phase 1 has been stable for 7 days
- [ ] Confirm daily token usage is tracking as expected
- [ ] Review any issues from Phase 1

#### Implementation Day
- [ ] Task 1: Reduce reconciliation frequency
- [ ] Task 2-1: Convert news collection to direct Python
- [ ] Task 2-2: Convert daily audit to direct Python
- [ ] Task 2-3: Convert price overrides to direct Python
- [ ] Update daily log with changes

#### Post-implementation (1 week after)
- [ ] Monitor order tracking delays
- [ ] Verify all direct Python jobs are running
- [ ] Check log files for errors
- [ ] Measure actual token usage reduction
- [ ] Adjust if needed

---

**Last updated:** 2026-05-21 12:36 JST
