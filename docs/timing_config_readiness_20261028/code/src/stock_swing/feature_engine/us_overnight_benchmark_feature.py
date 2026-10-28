"""US overnight benchmark return feature (JP semiconductor/AI expansion Phase 2).

New module (2026-08-19, Phase 2 design — see
docs/jp_semiconductor_ai_expansion_phase2_design.md section 2-A).

This feature computes, for each JP candidate symbol, the prior *completed*
US trading session's benchmark returns (SOXX/SMH/NVDA daily return). It is
the canonical feature-engine implementation of the same input signal that
`overnight_spillover_shadow.py` currently computes ad hoc from
`scripts/log_jp_overnight_spillover_shadow.py`'s direct yfinance calls.

Rationale for building this as a separate BaseFeature (rather than only
having the shadow logger's script-level fetch):
  - Matches this project's existing feature-engine architecture pattern
    (PriceMomentumFeature, MacroRegimeFeature, etc. compute FeatureResult
    objects consumed by strategies via CandidateSignal metadata).
  - Once wired into a strategy (Phase 3, post-IBKR), the same computation
    path can be reused for both live signal generation and diagnostics,
    rather than duplicating logic between a shadow script and a live
    strategy.

IMPORTANT — JPX/NYSE holiday-calendar asymmetry (per Phase 2 design section
2-A): "prior trading day" for a JP symbol is NOT simply "yesterday". This
feature receives already-fetched US benchmark CanonicalRecord bars (source
== "broker" or any source providing US benchmark price bars) and always
uses the MOST RECENT bar's date as "the reference US session", regardless
of calendar gaps. Callers are responsible for supplying up-to-date bars
(e.g. via HybridDataFetcher, same as every other feature in this engine);
this feature does not fetch data itself.

NOT wired into paper_demo.py or any strategy yet (Phase 2 design explicitly
scopes wiring to Phase 3, post-IBKR-connection). This module is safe to
import and use standalone (e.g. from a research script) without any effect
on existing strategies.
"""

from __future__ import annotations

from datetime import datetime, timezone

from stock_swing.core.types import CanonicalRecord
from stock_swing.feature_engine.base_feature import BaseFeature, FeatureResult

# Kept in sync with overnight_spillover_shadow.JP_CANDIDATE_TIERS' benchmark
# choice (SOXX is the primary reference; SMH/NVDA are supplementary context
# per Phase 1's correlation analysis, which found SOXX had the strongest
# spillover correlation of the benchmarks tested).
DEFAULT_BENCHMARK_SYMBOLS = ("SOXX", "SMH", "NVDA")

PRIMARY_BENCHMARK_SYMBOL = "SOXX"


def _latest_daily_return(records: list[CanonicalRecord]) -> tuple[float | None, str | None]:
    """Compute the most recent daily close-to-close return from a symbol's
    sorted price bar records.

    Returns:
        Tuple of (return_pct, reference_date_iso). Returns (None, None) if
        fewer than 2 bars are available.
    """
    price_records = [
        r for r in records
        if r.source_type == "price" and "bar_" in r.event_type
    ]
    if len(price_records) < 2:
        return None, None

    sorted_records = sorted(price_records, key=lambda r: r.event_time)
    latest = sorted_records[-1]
    prior = sorted_records[-2]

    latest_close = (latest.payload or {}).get("close")
    prior_close = (prior.payload or {}).get("close")
    if latest_close is None or prior_close is None or not prior_close:
        return None, None

    try:
        return_pct = (float(latest_close) / float(prior_close) - 1) * 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        return None, None

    return round(return_pct, 4), latest.event_time.isoformat()


class UsOvernightBenchmarkFeature(BaseFeature):
    """Computes the prior completed US session's benchmark return(s), for
    use as an input signal by any JP-symbol strategy that wants to react to
    overnight US market moves (see docs/jp_semiconductor_ai_expansion_plan.md
    Phase 1's spillover-correlation finding).

    This is a GLOBAL feature (symbol=None), analogous to MacroRegimeFeature:
    the US benchmark return is the same regardless of which JP symbol will
    ultimately consume it. Per-symbol tiering/weighting (Tier 1/2/3, per
    Phase 1's correlation ranking) is applied downstream by
    overnight_spillover_shadow.evaluate_overnight_spillover_signal(), not
    here — this feature only reports the raw benchmark move.
    """

    def __init__(self, benchmark_symbols: tuple[str, ...] = DEFAULT_BENCHMARK_SYMBOLS):
        self.benchmark_symbols = benchmark_symbols

    def compute(self, records: list[CanonicalRecord]) -> list[FeatureResult]:
        """Compute US benchmark overnight returns from price bar records.

        Args:
            records: CanonicalRecord bars for the benchmark symbols (any
                source providing "bar_*" event types with symbol set to one
                of self.benchmark_symbols).

        Returns:
            Single-element list with one FeatureResult
            (feature_name="us_overnight_benchmark_return", symbol=None),
            whose `values` dict has one entry per configured benchmark
            symbol that had sufficient data.
        """
        now = datetime.now(timezone.utc)
        by_symbol: dict[str, list[CanonicalRecord]] = {}
        for r in records:
            if r.symbol in self.benchmark_symbols:
                by_symbol.setdefault(r.symbol, []).append(r)

        values: dict[str, float | None] = {}
        reference_dates: dict[str, str | None] = {}
        quality_flags: list[str] = []

        for bm_symbol in self.benchmark_symbols:
            bm_records = by_symbol.get(bm_symbol, [])
            return_pct, ref_date = _latest_daily_return(bm_records)
            values[f"{bm_symbol.lower()}_return_pct"] = return_pct
            reference_dates[f"{bm_symbol.lower()}_reference_date"] = ref_date
            if return_pct is None:
                quality_flags.append(f"missing_data:{bm_symbol}")

        primary_key = f"{PRIMARY_BENCHMARK_SYMBOL.lower()}_return_pct"
        values["primary_benchmark_symbol"] = PRIMARY_BENCHMARK_SYMBOL
        values["primary_return_pct"] = values.get(primary_key)

        return [
            FeatureResult(
                feature_name="us_overnight_benchmark_return",
                symbol=None,  # Global feature, like macro_regime
                computed_at=now,
                values=values,
                metadata={
                    "benchmark_symbols": list(self.benchmark_symbols),
                    "reference_dates": reference_dates,
                },
                quality_flags=quality_flags,
            )
        ]
