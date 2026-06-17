# Phase 2 Token Cost Reduction Plan

**Scheduled:** 2026-05-28 (1 week after Phase 1)  
**Goal:** Reduce daily cost from $6-10 to $4-7

---

## Prerequisites

Before implementing Phase 2:

1. ✅ **Phase 1 has been stable for 7 days**
   - No reconciliation issues
   - No news coverage gaps
   - No user complaints

2. ✅ **Token usage reduction confirmed**
   - Daily cost reduced by ~$4.5/day
   - Current cost: $6-10/day

3. ✅ **System monitoring shows no issues**
   - Order tracking is accurate
   - News collection is sufficient
   - All cron jobs running normally

---

## Implementation Steps

### Step 1: Reduce Reconciliation Frequency

**Job:** `stock_swing_order_reconciliation_market_hours`  
**ID:** `32c3be71-3e86-470f-92e1-f50d8c77d533`

**Current:**
- Schedule: `*/30 20-23,0-6 * * *` (every 30 minutes)
- Runs: 22/day

**Change to:**
- Schedule: `0 20-23,0-6 * * *` (every 1 hour)
- Runs: 11/day

**Command:**
```bash
openclaw cron update --id 32c3be71-3e86-470f-92e1-f50d8c77d533 \
  --patch '{"schedule": {"kind": "cron", "expr": "0 20-23,0-6 * * *", "tz": "Asia/Tokyo"}}'
```

**Savings:** ~$2.5/day  
**Risk:** Medium (order tracking delayed by up to 1 hour)

**Monitoring:**
- Check for missed order fills
- Monitor time between order submission and reconciliation
- Watch for user reports of "order not reflected"

---

### Step 2: Convert to Direct Python Execution

#### 2.1 News Collection

**Current Job:** `stock_swing_news_collection`  
**ID:** `0a5ae126-cc03-44af-b4a8-b12b9821bd6f`

**Step 2.1.1: Add to system crontab**
```bash
# Edit crontab
crontab -e

# Add this line:
0 */4 * * * cd /Users/hirotomookawasaki/stock_swing && source venv/bin/activate && python -u -m stock_swing.cli.collect_data --sources finnhub --symbols MRVL,CIEN,DELL,RBRK,PLTR,NOW,INTU,NBIS >> /Users/hirotomookawasaki/stock_swing/logs/news_collection.log 2>&1
```

**Step 2.1.2: Disable OpenClaw cron**
```bash
openclaw cron update --id 0a5ae126-cc03-44af-b4a8-b12b9821bd6f --patch '{"enabled": false}'
```

**Step 2.1.3: Create log directory**
```bash
mkdir -p ~/stock_swing/logs
```

**Savings:** ~$0.30/day

---

#### 2.2 Daily Audit

**Current Job:** `stock_swing_daily_audit` (find ID with `openclaw cron list`)

**Step 2.2.1: Add to system crontab**
```bash
# Add to crontab
0 6 * * * cd /Users/hirotomookawasaki/stock_swing && ./scripts/cron/run_audit.sh >> /Users/hirotomookawasaki/stock_swing/logs/audit.log 2>&1
```

**Step 2.2.2: Disable OpenClaw cron**
```bash
# Find job ID
openclaw cron list | grep daily_audit

# Disable (replace <JOB_ID> with actual ID)
openclaw cron update --id <JOB_ID> --patch '{"enabled": false}'
```

**Savings:** ~$0.10/day

---

#### 2.3 Update Price Overrides

**Current Job:** `stock_swing_update_price_overrides`  
**ID:** `46c13997-20ef-43d5-bb39-f0e710c45ede`

**Step 2.3.1: Add to system crontab**
```bash
# Add to crontab
0 22 * * * cd /Users/hirotomookawasaki/stock_swing && ./scripts/cron/update_price_overrides.sh >> /Users/hirotomookawasaki/stock_swing/logs/price_overrides.log 2>&1
```

**Step 2.3.2: Disable OpenClaw cron**
```bash
openclaw cron update --id 46c13997-20ef-43d5-bb39-f0e710c45ede --patch '{"enabled": false}'
```

**Savings:** ~$0.20/day

---

## Total Savings

| Category | Runs Reduced | Cost Savings |
|----------|--------------|--------------|
| Reconciliation frequency | -11/day | ~$2.5/day |
| News collection (direct) | -6/day | ~$0.30/day |
| Daily audit (direct) | -1/day | ~$0.10/day |
| Price overrides (direct) | -1/day | ~$0.20/day |
| **Total** | **-19/day** | **~$3.1/day** |

**Combined Phase 1 + 2:**
- Phase 1: ~$4.5/day
- Phase 2: ~$3.1/day
- **Total: ~$7.6/day** (baseline) → **~$11/day** (actual)
- **Final cost: $4-7/day** ✅

---

## Post-Implementation Checklist

### Day 1 (Implementation Day)
- [ ] All changes applied successfully
- [ ] System crontab verified
- [ ] OpenClaw cron jobs disabled
- [ ] Log files created and writable
- [ ] Update daily log with changes

### Week 1 (Days 1-7)
- [ ] Monitor reconciliation delays
- [ ] Check for missed order fills
- [ ] Verify system cron jobs are running
- [ ] Review log files for errors
- [ ] Check news collection output
- [ ] Verify audit is running
- [ ] Confirm price overrides are updating

### Week 2 (Days 8-14)
- [ ] Measure actual token usage
- [ ] Compare to Phase 1 baseline
- [ ] Verify target cost ($4-7/day) achieved
- [ ] Collect user feedback
- [ ] Document any issues

### If Issues Arise
- Reconciliation delays causing problems?
  - → Revert to 30-minute frequency
- System cron jobs not running?
  - → Check crontab syntax
  - → Verify file permissions
  - → Check log files for errors
- News/audit data missing?
  - → Re-enable OpenClaw cron temporarily
  - → Debug system cron execution

---

## Rollback Plan

If Phase 2 causes issues, rollback is straightforward:

### Rollback Step 1: Re-enable OpenClaw cron jobs
```bash
openclaw cron update --id 0a5ae126-cc03-44af-b4a8-b12b9821bd6f --patch '{"enabled": true}'
openclaw cron update --id <AUDIT_JOB_ID> --patch '{"enabled": true}'
openclaw cron update --id 46c13997-20ef-43d5-bb39-f0e710c45ede --patch '{"enabled": true}'
```

### Rollback Step 2: Remove system crontab entries
```bash
crontab -e
# Delete the added lines
```

### Rollback Step 3: Restore reconciliation frequency
```bash
openclaw cron update --id 32c3be71-3e86-470f-92e1-f50d8c77d533 \
  --patch '{"schedule": {"kind": "cron", "expr": "*/30 20-23,0-6 * * *", "tz": "Asia/Tokyo"}}'
```

---

## Success Criteria

Phase 2 is considered successful if:

1. **Cost reduction achieved**
   - Daily cost: $4-7
   - Monthly cost: $120-210
   - Reduction from baseline: ~$11/day

2. **No operational issues**
   - Order tracking accurate (within 1 hour)
   - News collection complete
   - Daily audit running
   - Price overrides updating

3. **No user complaints**
   - No reports of missed orders
   - No reports of stale data
   - No reports of system unavailability

---

**Created:** 2026-05-21 12:36 JST  
**Review:** 2026-05-28 (implementation day)
