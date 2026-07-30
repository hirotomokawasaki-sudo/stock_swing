# Review Index — SSR-20260729-01
mode: DELTA_SELF_CONTAINED
generated_at_utc: 2026-07-29T02:23:38.489408+00:00
baseline_commit: 744e3fa (2026-07-21)
current_commit: 0ae1ce6926a6b757093d484bdb9a0b8b30e0e52e
branch: main

## Quick Navigation

| Section | Key Files |
|---------|-----------|
| Control | 00_control/EXPORT_MANIFEST.json, EXPORT_VALIDATION.json, MISSING_DATA.csv |
| Roadmap | 01_context_and_roadmap/console_improvement_tasks.md, Go/No-Go docs |
| Source diff | 02_source_and_config/git_diff_stat.txt, git_diff_full.patch, changed_files/ |
| Config | 02_source_and_config/config/ (current config, redacted where needed) |
| Tests | 03_tests_and_quality/pytest_output_plain.txt |
| Operations | 04_runtime_and_operations/circuit_breaker.json, daily logs |
| Ledger | 05_ledger_and_broker/ledger_invariants.json, closed_trades.csv |
| Performance | 06_performance_and_risk/performance_by_window.json, equity_curve.csv |
| Strategy | 07_strategy_and_counterfactual/, exit_variant_comparison.json |
| Pipeline | 08_data_pipeline/data_pipeline_summary.md |
| Guardrails | 09_guardrails_experiments_learning/circuit_breaker.json |
| Console | 10_console/api_summary.json, latest_console_summary.json |
| AI Usage | 11_ai_usage/ai_usage_summary.json |
| Security | 12_security/secret_scan_results.txt |
| Questions | 13_open_questions/review_questions.md |

## Key Facts (as of 2026-07-29T02:23:38.489408+00:00)
- runtime_mode: PAPER
- ledger_quality: NEEDS_REVIEW
- allocation: Stock 85% / ETF 15%
- closed_trades: 205
- quarantined_trades: 101
- cumulative_realized_pnl: $-74666.19
- daily_snapshots: 131
- commits_since_baseline: 68
- files_changed_since_baseline: 129
