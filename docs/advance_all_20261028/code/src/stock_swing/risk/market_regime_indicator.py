"""R11 follow-up (2026-08-15): market chop/regime indicator (observability-only).

Purpose
-------
The 2026-08-15 R11-B parameter search and R11-C regime-filter follow-ups
found that BreakoutMomentumStrategy's edge is real but regime-dependent: it
degrades sharply (PF=0.56 in the historical validation window) during a
high-volatility sideways ("choppy"/whipsaw) market regime, and that neither
parameter tuning, entry-side SMA trend filters, nor the existing guardrail's
halt/reduce_size behavior fully protects against this (each mitigates at
most ~10%). See docs/console_improvement_tasks.md "R11-B付随" / "R11-C付随"
/ "R0-v2/R9付随" / "R0-v2/R9付随(2)" sections for the full analysis.

This module computes a simple, transparent chop indicator from the SPY/QQQ
daily bars already collected by stock_swing_update_benchmark_all (data/
benchmarks/{SYMBOL}_daily.json), so the console can surface "how choppy is
the market right now" continuously going forward -- not to block anything,
but so a human reviewing the dashboard (or a scheduled review job) has a
standing early-warning signal instead of having to re-run a historical
backtest to notice the regime has turned unfavorable.

Why observability-only (not wired into signal_strength/sizing/entry)
----------------------------------------------------------------------
Same rationale as Plan B/C/D/E and the R11-C regime-filter finding itself:
the 2026-08-15 backtest already showed that blocking BUYs on an SMA-based
trend signal does NOT meaningfully fix the underlying problem (validation
PF only moved from 0.56 to 0.58-0.63), so wiring this into a hard block
would add decision-making risk without the offsetting benefit that
justified Plan A's cooldown block. This module only computes and reports a
score; it never blocks or resizes anything.

Indicator design
-----------------
Two pure signals, both computed from the same historical benchmark data
used in the 2026-08-15 backtests:
  1. trend_state: is the regime symbol (default SPY) above or below its
     SMA(sma_period), and is that SMA itself rising or falling over
     trend_window days. Mirrors the two R11-C addendum filter variants
     (price_below_sma / sma_declining) exactly, but reports rather than
     blocks.
  2. range_width_pct: (max-min)/min over the trailing range_window days,
     as a simple, no-new-data-required proxy for "how much whipsaw" is
     happening (a wide range with a flat/oscillating SMA is the chop
     signature found in the 2026-08-15 correction window, which ranged
     648-695 on SPY without a sustained one-directional trend).

Combined into a single `chop_score` (0-100, higher = more chop-like) and a
human-readable `regime_label` for the console panel. Thresholds are
deliberately simple and documented as illustrative, not backtested/
optimized (avoiding the same overfitting risk flagged throughout the 2026-
08-15 R11 investigation) -- this is a reporting aid, not a new gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MarketRegimeIndicator:
    regime_symbol: str
    latest_close: float | None
    sma_short: float | None  # SMA(sma_period)
    sma_short_prior: float | None  # SMA(sma_period) trend_window days ago
    above_sma: bool | None
    sma_rising: bool | None
    range_width_pct: float | None  # over range_window days
    chop_score: float | None  # 0-100, higher = more chop-like
    regime_label: str
    insufficient_data: bool = False


def _load_benchmark_closes(benchmark_dir: Path, symbol: str) -> list[dict[str, Any]]:
    import json

    path = Path(benchmark_dir) / f"{symbol}_daily.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return sorted(data, key=lambda b: b.get("date", ""))
    except Exception:
        return []


def compute_market_regime_indicator(
    benchmark_dir: Path | str,
    *,
    regime_symbol: str = "SPY",
    sma_period: int = 50,
    trend_window: int = 5,
    range_window: int = 20,
) -> MarketRegimeIndicator:
    """Compute the chop/regime indicator from cached benchmark daily bars.

    Returns insufficient_data=True (all numeric fields None) if fewer than
    sma_period + trend_window bars are available, rather than raising --
    this is a best-effort console panel, not a hard dependency.
    """
    bars = _load_benchmark_closes(Path(benchmark_dir), regime_symbol)
    closes = [b["close"] for b in bars if isinstance(b.get("close"), (int, float))]

    min_bars_needed = sma_period + trend_window
    if len(closes) < min_bars_needed:
        return MarketRegimeIndicator(
            regime_symbol=regime_symbol,
            latest_close=closes[-1] if closes else None,
            sma_short=None,
            sma_short_prior=None,
            above_sma=None,
            sma_rising=None,
            range_width_pct=None,
            chop_score=None,
            regime_label="insufficient_data",
            insufficient_data=True,
        )

    latest_close = closes[-1]
    sma_now = sum(closes[-sma_period:]) / sma_period
    sma_prior_window = closes[-(sma_period + trend_window):-trend_window]
    sma_prior = sum(sma_prior_window) / sma_period

    above_sma = latest_close >= sma_now
    sma_rising = sma_now >= sma_prior

    range_bars = closes[-range_window:] if len(closes) >= range_window else closes
    range_low, range_high = min(range_bars), max(range_bars)
    range_width_pct = ((range_high - range_low) / range_low * 100) if range_low > 0 else None

    # chop_score: simple illustrative composite, NOT backtested/optimized.
    # - Trend component: a "clean" bull trend (above SMA + SMA rising) or
    #   "clean" bear trend (below SMA + SMA falling) scores low chop (0-30).
    #   A mixed state (above SMA but SMA falling, or below SMA but SMA
    #   rising -- exactly the whipsaw pattern found 2026-08-15) scores high
    #   chop (70-100).
    # - Range component: wider trailing range = more chop, scaled against a
    #   illustrative 15% range width as a rough "wide" reference point
    #   (the 2026-08-15 correction window's SPY range was ~7.2% over its
    #   full ~4-month span; this is a coarse per-panel heuristic, not a
    #   calibrated threshold).
    trend_component = 0.0 if (above_sma == sma_rising) else 100.0
    range_component = min(100.0, (range_width_pct or 0.0) / 15.0 * 100.0)
    chop_score = round(0.6 * trend_component + 0.4 * range_component, 1)

    if chop_score >= 60:
        regime_label = "choppy (mixed trend + wide range)"
    elif chop_score >= 35:
        regime_label = "transitional"
    elif above_sma and sma_rising:
        regime_label = "trending_bullish"
    elif not above_sma and not sma_rising:
        regime_label = "trending_bearish"
    else:
        regime_label = "neutral"

    return MarketRegimeIndicator(
        regime_symbol=regime_symbol,
        latest_close=round(latest_close, 2),
        sma_short=round(sma_now, 2),
        sma_short_prior=round(sma_prior, 2),
        above_sma=above_sma,
        sma_rising=sma_rising,
        range_width_pct=round(range_width_pct, 2) if range_width_pct is not None else None,
        chop_score=chop_score,
        regime_label=regime_label,
        insufficient_data=False,
    )
