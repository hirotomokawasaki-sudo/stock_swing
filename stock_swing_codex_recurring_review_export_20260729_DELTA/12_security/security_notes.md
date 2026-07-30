# Security Review
generated_at_utc: 2026-07-29T02:29:07.554816+00:00
runtime_mode: PAPER
no_live_credentials_in_export: true
secret_scan_method: focused scan for account identifiers and literal credential assignments in exported files

## Export Hygiene
- .env files: excluded
- local virtualenv directories: excluded
- broker_order_id: anonymized in CSV outputs
- broker_account_id: raw state file excluded; summary only
- config/accounts.json: copied in redacted form

## Result
- Residual findings remain; see secret_scan_results.txt
