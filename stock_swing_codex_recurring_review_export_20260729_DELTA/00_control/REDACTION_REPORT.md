# Redaction Report
generated_at_utc: 2026-07-29T02:29:07.554754+00:00
request_id: SSR-20260729-01

## Redacted or Excluded Items
1. broker_order_id: anonymized with SHA-256 prefix "OID_" in closed_trades.csv
2. .env files: excluded from export
3. local virtualenv directories: excluded from export
4. API key and secret values: excluded from export
5. account_number fields: redacted in copied config/tests artifacts
6. broker_account_id: omitted from exported pnl summaries
7. user home path: generalized to [USER_HOME] in generated narrative files

## Notes
- config/accounts.json is included only in redacted form
- raw pnl_state.json is not exported
- dashboard_source/.env was removed during final cleanup

## Secret scan result
See 12_security/secret_scan_results.txt
