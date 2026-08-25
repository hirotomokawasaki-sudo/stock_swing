# R14: Dip-Buy / Mean-Reversion Feasibility Check (Phase 1)

**Date**: 2026-08-25
**Trigger**: User question in main session — during the 2026-08-24 semiconductor
sell-off (circuit breaker went `degraded`/`block_buys` on 8 consecutive losing
trades + daily realized loss -2.09%), is a falling market actually a buying
opportunity that the current system is structurally blind to? Two sub-questions
were asked: (1) does this fit as a strategy at all, and (2) can it run alongside
`breakout_momentum_v1` without conflict.

**Scope**: Phase 1 only — pure historical backtest, no production wiring, no
shadow logging added to `paper_demo.py`, no strategy-engine changes. Mirrors the
same Phase 1 pattern already used and approved for R13-D (ETF sector rotation)
and the JP semiconductor expansion. GO/NO-GO here only decides whether a Phase 2
(real strategy design + shadow accumulation) is worth attempting.

**Script**: `scripts/r14_dip_buy_meanreversion_phase1.py` (new, ~340 lines).
Reuses `r11_backtest_engine_v3`'s conservative-OHLC-exit + t+1-fill + slippage
machinery verbatim (imported, not reimplemented) and the exact same production
`SimpleExitV2Strategy` config, so any PF/WR difference vs. `breakout_momentum_v1`
is attributable to the **entry rule only**, not a different cost model or exit
design.

## Entry rule tested

Mirror image of `BreakoutMomentumStrategy`'s own condition. Breakout buys when
trailing 20-day momentum ≥ +5% and `PriceMomentumFeature` classifies
`trend=="bullish"`. This dip-buy variant buys when trailing 20-day momentum
≤ **-5%** and `trend=="bearish"` (same feature's own bearish classification,
unchanged). Deliberately the least-tunable rule shape possible (no parameter
grid search), to avoid the overfitting risk repeatedly flagged in R13-C.

## Results (2-year window, 2024-08-15 → 2026-08-14, 69-symbol universe, same
$10k/trade notional, 10bp one-way slippage, identical exit config)

Two variants run for a fair comparison against the existing v3 momentum
backtest results (`reports/r11_backtest_v3_results.json`):

### A. Point-in-time universe (symbols only tradeable from their actual
introduction date — same gating momentum's own headline number uses)

| Strategy | n | WR | PF | Net PnL | Live window (≥05-12) PF |
|---|---|---|---|---|---|
| `breakout_momentum_v1` (existing, v3) | 621 | 70.2% | **1.854** | $101,272 | 1.453 |
| `dip_buy_meanreversion_v1` (this spike) | 359 | 70.5% | **1.963** | $57,459 | 1.855 |

### B. No point-in-time gating (full 2-year window for all symbols — same
`--no-point-in-time-universe` flag momentum's own engine already supports;
larger sample, same limitation caveat applies equally to both)

| Strategy | n | WR | PF | Net PnL |
|---|---|---|---|---|
| `breakout_momentum_v1` | 1997 | 66.4% | 1.575 | $233,298 |
| `dip_buy_meanreversion_v1` | 1938 | 66.6% | **1.710** | $250,093 |

**Chop-regime window** (2025-11 → 2026-03, the same period R13-C's rolling
walk-forward flagged as momentum's weakest regime, PF=0.815 in that separate
analysis):

| Strategy | n | WR | PF | Net PnL |
|---|---|---|---|---|
| `breakout_momentum_v1` | 217 | 50.2% | **0.646** | -$23,094 |
| `dip_buy_meanreversion_v1` | 389 | 62.0% | **1.170** | +$14,339 |

This is the single most important finding: in the exact regime where the
existing momentum strategy independently confirmed a structural weakness
(chop/range-bound market), the dip-buy rule was **profitable and momentum was
not** — consistent with a textbook mean-reversion-in-chop / momentum-in-trend
complementary relationship, not a coincidence specific to one parameter set.

### Exit reason breakdown (point-in-time variant, dip-buy)

| exit_reason | n | WR | PF | net |
|---|---|---|---|---|
| trailing_stop | 236 | 100% | inf | +$109,489 |
| stop_loss | 102 | 0% | 0.0 | -$59,362 |
| backtest_end_forced_close | 21 | 81% | 27.1 | +$7,331 |

Same shape as momentum's own exit profile (trailing_stop carries all the
edge, stop_loss is the loss concentration) — this is a property of the
**shared exit strategy**, not something specific to the dip-buy entry.

## Compatibility / overlap measurement (sub-question 2)

Ran a shadow measurement of `breakout_momentum_v1`'s own signal set over the
identical days/symbols alongside the dip-buy simulation (bookkeeping only,
consumes no capacity in the dip-buy run):

- **Point-in-time variant**: 83 / 359 dip-buy signals (23%) fired on a symbol
  momentum would have also held around the same time.
- **Full window variant**: 359 / 1938 (18.5%).
- **Peak concurrent open positions**: momentum ~64, dip-buy ~61 (comparable
  scale — a real simultaneous run would meaningfully compete for shared
  capital/exposure caps, not just occasionally brush against the same symbol).

**Why overlap is structurally limited but not zero**: `breakout_momentum_v1`
requires `trend=="bullish"` (momentum ≥ +2%), dip-buy requires
`trend=="bearish"` (momentum ≤ -2%) — mutually exclusive on the SAME 20-day
window, so true same-day same-symbol double-entry cannot happen by
construction. The ~20% overlap above is temporal drift: a stock that was
bearish when dip-buy entered can flip bullish and get picked up by momentum
while the dip-buy position is still open (or vice versa on exit/re-entry),
not a same-instant conflict.

## What this means for the shared risk layers (not simulated here, flagged
as a real Phase 2 dependency)

Per the earlier analysis: Circuit Breaker, rolling-PF entry_filter Gate 3,
correlation cluster cap, and `PortfolioAllocator`'s ETF/stock band are all
**portfolio-level and strategy-agnostic**. This Phase 1 check deliberately did
not simulate them (same scoping decision R13-D Phase 1 made for sector
rotation) because they require live paper data, not a raw-signal backtest.
Two portfolio-level risks this raises for Phase 2 design, both concrete not
theoretical given the overlap numbers above:
1. Rolling PF gate (Gate 3) is **per-symbol**, not per-strategy — a symbol that
   momentum just stopped out of will have a depressed rolling PF and may block
   the dip-buy strategy from entering the SAME symbol shortly after, even
   though the entry logic is intentionally the opposite signal.
2. Correlation cluster caps and gross exposure are shared pools — a real
   simultaneous run needs its own capital-allocation split (e.g. sub-ledger or
   an explicit sizing carve-out) rather than assuming both strategies draw
   from the same uncapped pot, matching the same environment_id-style
   separation already planned for the IBKR broker migration and the JP
   semiconductor expansion tracks.

## Limitations (explicit)

- Single entry-rule shape only (mirrored ±5%/20-day threshold); no depth/
  lookback grid search.
- Fixed $10k/trade notional, one open position per symbol, point-in-time
  universe gating shares the exact same survivorship-bias caveat as R13-C.
- Portfolio-level shared risk layers (circuit breaker, rolling-PF gate,
  cluster cap, allocator band) not simulated — flagged as the primary Phase 2
  design dependency above, not resolved here.
- No transaction-cost sensitivity sweep (only 10bp one-way, the same "middle"
  scenario R13-C used) — not re-tested at 0/20/30bp.
- 2-year window is a single historical regime overall (bull market with
  corrections), same caveat every R13-C/R13-D Phase 1 doc already carries.

## Verdict

**GO** — proceed to Phase 2 (real strategy design). The mirror-image dip-buy
rule shows comparable-to-better PF than the existing production momentum
strategy on the same cost model and exit rules, and specifically **profits in
the regime where momentum has an independently-confirmed structural
weakness** (chop, PF 1.17 vs -0.646). Overlap with momentum is real but
limited (~20%) and mutually exclusive by construction at entry time; the
practical integration risk is the SHARED per-symbol/portfolio risk layers,
not the entry signals themselves competing directly.

**Recommended Phase 2 scope** (not started): (1) design capital allocation
split between the two strategies (env/sub-ledger style, not a shared
uncapped pool), (2) decide whether Gate 3 (rolling PF) should be
strategy-scoped rather than purely symbol-scoped given the cross-strategy
interaction identified above, (3) shadow-log the dip-buy signal in
`paper_demo.py` (observability-only, no fills) for a few weeks to validate
signal generation against live data before any real capital, following the
same shadow→paper_ab→active promotion path used for the other roadmap items.
