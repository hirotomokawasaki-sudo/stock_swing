# Data Pipeline Summary
as_of_utc: 2026-07-29T02:23:32.337045+00:00
sources:
  - name: Finnhub
    purpose: price data, news, fundamentals
    symbols: see symbol_registry.yaml
    coverage: see data/raw/
  - name: Alpaca Markets (paper)
    purpose: order execution, broker fills, positions
    coverage: paper account only (runtime_mode=paper)
  - name: price_cache
    purpose: local cache of fetched price data
    coverage: see data/price_cache/
  - name: backtest_price_cache
    purpose: historical price data for counterfactual
    coverage: see data/backtest_price_cache/
  - name: benchmarks
    purpose: SPY, QQQ, SMH, SOXX, SOXQ benchmark prices
    coverage: see data/benchmarks/
note: event_time vs available_at separation — see DATA_DICTIONARY.md
