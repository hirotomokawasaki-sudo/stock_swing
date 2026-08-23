# R13-D ETF Sector Rotation Phase 1: Robustness Checks

## Execution-lag sensitivity (simulating signal-to-fill delay)

| lag (days) | total_return | Sharpe | maxDD |
|---|---|---|---|
| 0 (same-day, as in main run) | +100.32% | 1.370 | 29.43% |
| 1 | +100.40% | 1.372 | 29.36% |
| 2 | +105.99% | 1.424 | 28.93% |

Result is NOT sensitive to execution lag (monthly rebalance frequency makes
a 1-2 day fill delay immaterial) -- this is expected and reassuring, unlike
R13-C's core strategy where t+1 fill materially changed the picture (daily
signal frequency there made same-bar lookahead a real distortion).

## Walk-forward split (period1 vs period2, top-2/63d/21d config)

| period | dates | Sharpe |
|---|---|---|
| period1 | 2024-11-14 to 2025-09-30 | 1.069 |
| period2 | 2025-10-01 to 2026-08-14 | 1.622 |

Both periods independently beat the SPY baseline's full-period Sharpe
(0.967) and the equal-weight-all-sectors baseline's full-period Sharpe
(1.255) is beaten in period2 but not period1 alone -- a caveat, not a
disqualifier, given period1 alone still clears the SPY baseline
comfortably.

## Removing single-ETF "sectors" (QTUM/QQQ/SKYY/SPY as own group)

Restricting to only genuinely multi-member sectors (robotics_ai n=2,
semiconductor n=8, software n=7) with top_n=1: total_return=+128.02%,
Sharpe=1.473, maxDD=28.51% -- still clears both baselines. This addresses
the concern that a single volatile ETF (e.g. QTUM, quantum computing) with
no averaging partner might be driving the whole result via noise; it is
not the sole driver.

## Parameter sensitivity (round-number alternatives, not grid-searched)

| config | total_return | Sharpe | maxDD |
|---|---|---|---|
| top_n=1, lookback=63d, hold=21d | +162.32% | 1.627 | 27.91% |
| top_n=3, lookback=63d, hold=21d | +91.98% | 1.366 | 26.48% |
| top_n=2, lookback=126d, hold=21d | +88.42% | 1.390 | 27.62% |
| top_n=2, lookback=63d, hold=42d | +122.80% | 1.549 | 29.43% |

All four alternate configurations still beat both baselines on Sharpe
(baseline Sharpes: equal-weight=1.255, SPY=0.967). Result is not fragile
to a single specific parameter choice.

## Honest limitations (from the script's own docstring, repeated here)

- Equal-weighted sector "index" is a simplification (not cap-weighted).
- No transaction costs/slippage modeled at this Phase 1 stage -- this is a
  feasibility check on the raw momentum signal, not a tradeable-strategy
  backtest.
- Single historical regime (2024-08 to 2026-08 bull market with two
  corrections); no claim of regime robustness beyond what's shown above.
- Uses the CURRENTLY tracked ETF universe retroactively (same class of
  caveat as R13-C's point-in-time-universe discussion, though ETF universe
  selection is far less hindsight-prone than individual stock selection).
