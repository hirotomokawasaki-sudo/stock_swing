# Cron Definitions
Cron jobs are managed by OpenClaw Gateway.
Export of live cron state requires Gateway API.
Known scheduled jobs (from memory/documentation):
- stock_swing_order_reconciliation: every 15min
- stock_swing_news_collection: every 2h
- stock_swing_paper_demo_market_open: market hours (America/New_York)
- stock_swing_paper_demo_after_hours: after hours
- daily_report_morning: 09:00 JST weekdays
