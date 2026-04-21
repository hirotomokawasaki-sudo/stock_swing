.PHONY: daily-log reconcile-orders collect-data analyze-data

daily-log:
	python scripts/create_daily_improvement_log.py

reconcile-orders:
	python -m stock_swing.cli.reconcile_orders

collect-data:
	python -m stock_swing.cli.collect_data

analyze-data:
	python -m stock_swing.cli.analyze_data
