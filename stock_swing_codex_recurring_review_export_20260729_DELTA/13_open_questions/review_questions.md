# Open Questions for Codex Review (SSR-20260729-01)

## From Previous Review (Pending Items)

### OQ-01: Sector Shock Paper A/B
- RF-7b (sector_shock paper A/B) is still pending
- current_valid_shadow_count = 3 (target: 10)
- Question: Is shadow-only mode sufficient for Go/No-Go, or is 10+ shadows required?

### OQ-02: stop_loss WR vs Correct Stop Rate
- WR target of 30% has been replaced by "correct stop rate >= 70%"
- Measured: 89.6% (all) / 100% (07-10+)
- Question: Is WR 24.1% acceptable given the new evaluation framework?

### OQ-03: Go/No-Go Criteria — PF vs Stop-Loss Evaluation
- overall PF (all period): 0.62 (target: 1.20)
- trailing_stop PF: 3.48 (target: 1.50 ✅)
- Question: Should Go/No-Go be split into stop_loss and trailing_stop dimensions?

### OQ-04: tiered_min_hold Plan A
- Deployed (commit 52736ca) but only simulated, not real-paper-run-verified
- Estimated improvement: +$41K reduction in stop_loss losses
- Question: What evidence is needed for VERIFIED_COMPLETE?

### OQ-05: current_mode console display
- Previous review noted current_state and last_run should be separated
- Status: partially addressed in console (needs verification)
- Question: Is the separation clearly visible in the current console?

### OQ-06: actual vs estimated token separation
- has_actual_tokens / has_estimated_tokens separation exists in decision files
- Coverage: see 11_ai_usage/ai_usage_summary.json
- Question: Is the coverage level acceptable?

### OQ-07: RF-8c stop_loss root cause
- 06-25 sector shock identified as primary cause
- sector_shock_hold shadow only (3/10 needed)
- Question: Can we accept sector shock risk at 08-20 live start without A/B completion?

## System AI Questions for Codex
1. Are the 7 commits after baseline that touch broker/reconcile/ledger introducing regression risk?
2. Does the Plan A tiered_min_hold implementation have any lookahead leakage risk?
3. Is the 68-commit delta too large for DELTA mode, or is the self-contained export sufficient?
4. Is RF-7b (sector_shock paper A/B at shadow_count=3) a blocking or non-blocking risk?
5. ADBE phantom close bug (36d6af3) — is the fix complete and regression-tested?
