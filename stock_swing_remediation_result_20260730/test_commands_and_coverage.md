# Test Commands

- `./venv/bin/python -m pytest tests/unit/test_cron_observability.py tests/unit/test_guardrail_day_start.py tests/unit/test_fill_ledger_exactly_once.py tests/unit/test_source_lineage.py tests/unit/test_cumulative_allocation.py tests/integration/test_p6_end_to_end.py tests/unit/test_token_accounting.py -v`
- `./venv/bin/python -m pytest tests/unit/test_remediation_20260730.py tests/unit/test_console_self_check_service.py tests/unit/test_reconcile_orders.py -q`
- `./venv/bin/python -m pytest --tb=short -q`

Coverage note: full-suite pass was verified; explicit changed-line/branch coverage artifacts were not regenerated in this turn.
