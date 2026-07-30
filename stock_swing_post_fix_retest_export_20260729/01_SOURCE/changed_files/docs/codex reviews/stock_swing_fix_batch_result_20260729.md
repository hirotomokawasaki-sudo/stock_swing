# Fix Batch Implementation Result — 2026-07-29

## Summary

| Task | Status | Commit | Tests Added |
|---|---|---|---|
| FIX-001 | VERIFIED_COMPLETE | `40bcc1d` | 7 |
| FIX-002 | VERIFIED_COMPLETE | `c948f57` | 3 |
| FIX-003 | VERIFIED_COMPLETE | `c948f57` | 4 |
| FIX-004 | IN_PROGRESS | `c948f57` | 1 |
| FIX-005 | VERIFIED_COMPLETE | `c948f57` | 3 |
| FIX-006 | VERIFIED_COMPLETE | `c948f57` | 2 |
| FIX-007 | VERIFIED_COMPLETE | `687c5c5` | 1 |
| FIX-009 | VERIFIED_COMPLETE | `992188e` | 2 |
| FIX-010 | VERIFIED_COMPLETE | `c948f57` | 2 |
| roadmap_merge | VERIFIED_COMPLETE | `0faccfc` | 0 |

## Changed files

- `docs/console_improvement_tasks.md`
- `src/stock_swing/cli/collect_data.py`
- `src/stock_swing/core/types.py`
- `src/stock_swing/risk/portfolio_allocator.py`
- `src/stock_swing/cli/paper_demo.py`
- `src/stock_swing/cli/reconcile_orders.py`
- `src/stock_swing/core/run_context.py`
- `src/stock_swing/decision_engine/decision_engine.py`
- `src/stock_swing/guardrails/risk_snapshot.py`
- `src/stock_swing/utils/context_budget.py`
- `config/strategy/simple_exit_v2.yaml`
- `console/app.py`
- `tests/unit/test_collect_data_fix001.py`
- `tests/unit/test_allocation_fix002.py`
- `tests/unit/test_reconcile_fix003.py`
- `tests/unit/test_guardrail_fix005.py`
- `tests/unit/test_p6_join_fix006.py`
- `tests/unit/test_fix007_yaml_disable.py`
- `tests/unit/test_console_security_fix009.py`
- `docs/test_evidence/pytest_output_fix_batch_20260729.txt`
- `docs/test_evidence/pytest_report_fix_batch_20260729.json`

## Test command and result

```bash
python -m pytest tests/ --tb=short -q
```

Result: 1118 passed, 2 skipped, 1 warning

Evidence:
- `docs/test_evidence/pytest_output_fix_batch_20260729.txt`
- `docs/test_evidence/pytest_report_fix_batch_20260729.json`

Note:
- `pytest --json-report` was not available in this environment, so the JSON file is a generated summary from captured pytest output.

## Before/after metrics

- synthetic production fallback code paths: 6 -> 0
- raw snapshot lineage envelope: partial -> `event_time/available_at/ingested_at/source_id/revision_id/quality_status/is_synthetic`
- allocation projected-band enforcement: pre-sizing only -> post-sizing enforced with real preview qty
- recently sold suppression: unbounded history -> 30 minute window
- guardrail daily total loss baseline: implicit `prev_unrealized_pnl=0` -> explicit run-start baseline passed
- decision join metadata: evidence-only -> top-level `run_id/experiment_id/config_hash/decision_time`
- token accounting source: implicit estimated/rule mix -> `provider_actual/estimated/rule_based_zero`
- 7d tier enabled: true -> false
- console bind: `0.0.0.0` -> `127.0.0.1`
- console write endpoints: enabled by code path -> disabled by default unless `CONSOLE_WRITE_ENABLED=true`

## Unresolved risks

- FIX-004 is only partially closed. The repo did not contain a standalone `closed_trades.csv` exporter to patch directly, so a canonical export-row mapper was added in `paper_demo.py`, but any external/export-only scripts outside the repo still need the same alias mapping.
- Final evidence JSON is synthesized because the `pytest-json-report` plugin is not installed in this environment.
- This batch did not touch production ledgers, broker state, or rebuild scripts, so data-level acceptance items still require clean scheduled run validation.

## Rollback procedures

1. Revert the fix-batch commits in reverse order:
   - `git revert 992188e`
   - `git revert 687c5c5`
   - `git revert c948f57`
   - `git revert 40bcc1d`
   - `git revert 0faccfc`
2. Re-run `python -m pytest tests/ --tb=short -q`.
3. Confirm console bind/write behavior and strategy YAML values before restarting automation.

## Go/No-Go for next task

- Status: NO-GO for live readiness.
- Reason: FIX-004 remains partially open, and promotion requirements in the roadmap still require clean exporter validation plus post-fix scheduled-run evidence.
