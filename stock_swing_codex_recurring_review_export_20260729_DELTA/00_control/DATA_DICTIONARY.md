# Data Dictionary
schema_version: "1.0"
generated_at_utc: 2026-07-29T02:23:38.489408+00:00

## Timezone Convention
- All timestamps in this export: ISO 8601 UTC ("+00:00" or "Z")
- Market timezone: America/New_York (ET)
- decision_time, entry_time, exit_time: UTC
- daily_snapshot date: America/New_York date (YYYY-MM-DD)
- cron schedules defined in: America/New_York

## Key Fields

### closed_trades.csv / quarantined_trades.csv
- trade_id: internal unique ID (stable across runs with --preserve-attribution)
- symbol: ticker symbol
- asset_class: "stock" | "etf" | null (null = pre-backfill)
- entry_time: ISO 8601 UTC, when position was opened
- exit_time: ISO 8601 UTC, when position was closed
- holding_days: calendar days, computed from timestamps (may be None for legacy)
- realized_pnl: USD, net of qty*entry/exit prices (broker fees NOT included)
- exit_reason: "trailing_stop" | "stop_loss" | "breakeven_stop" | "broker_fill" | "timeout" | etc.
- experiment_id: null if not assigned (pre-experiment era)
- decision_id: ID linking to decisions/ file (may be null for legacy)
- broker_order_id_anon: SHA-256 hash prefix of actual broker_order_id

### daily_equity_snapshots.csv
- date: America/New_York date string
- equity: estimated total equity (open positions marked at last close + cash estimate)
- cumulative_pnl: cumulative realized PnL since tracking start

### decisions_summary.csv
- decision_id: unique per decision call
- run_id: links to scheduled run
- experiment_id: A/B experiment assignment
- signal_strength: 0.0–1.0 AI confidence proxy
- model: actual AI model used
- input_tokens: actual provider tokens if available, else estimated

## Population and Exclusions
- Performance metrics: closed trades only, quarantined excluded
- Validity status: NEEDS_REVIEW
- Cohort identifier: tracking_label in pnl_state_summary.json
- Cost/slippage: NOT included in realized_pnl

## Allocation Policy
- Stock target: 85% | ETF target: 15%
- Source of truth: config/strategy/portfolio_allocation.yaml

## available_at vs event_time
- event_time: when market event occurred
- available_at: when data was available to the decision system
- Note: price_cache does not currently track available_at separately
- Look-ahead leakage mitigation: decisions use prices from prior close only
