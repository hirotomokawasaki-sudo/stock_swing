# R13-C v3: Bootstrap CI on live-window PF (conservative_ohlc + 10bp one-way slippage)

n(live, entry_date >= 2026-05-12) = 471
PF = 1.453, net = +$45,725, WR = 66.0%

90% bootstrap CI on PF: [1.210, 1.750] (2000 resamples)
Fraction of resamples with PF > 1: 100.0%

Comparison across engine versions (live-window only):

| Engine | n | PF | 90% CI |
|---|---|---|---|
| Live production (attributable) | 49 | 1.082 | [0.564, 2.125] |
| v2 (t+1 fill + point-in-time universe, no slippage, close-only exit) | 284 | 1.448 | [1.099, 1.891] |
| v3 (+ conservative OHLC exit + 10bp one-way slippage) | 471 | 1.453 | [1.210, 1.750] |
