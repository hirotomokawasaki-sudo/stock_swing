"""Sector momentum feature (R13-D Phase 2, ETF sector rotation).

New module (2026-08-23). Computes trailing-return momentum per sector for
a fixed universe of tagged sector ETFs, following the exact same
methodology already validated in R13-D Phase 1
(scripts/r13d_etf_sector_rotation_phase1.py's build_sector_daily_returns()
+ trailing_return()): each sector's daily return is the equal-weighted
mean of its member ETFs' daily returns (NOT capitalization-weighted --
documented simplification, same as Phase 1), and a sector's momentum score
is its cumulative trailing return over `lookback_days` trading days.

Rationale for building this as a BaseFeature (rather than only having the
Phase 1 research script): matches this project's existing feature-engine
architecture pattern (PriceMomentumFeature, MacroRegimeFeature,
UsOvernightBenchmarkFeature all compute FeatureResult objects consumed by
strategies via CandidateSignal metadata) -- same rationale documented in
us_overnight_benchmark_feature.py for the JP spillover roadmap item. Once
wired (Phase 3, requires the rebalance-cadence state design discussed in
docs/console_improvement_tasks.md's R13-D Phase 2 section), the same
computation path serves both live signal generation and diagnostics.

Sector membership is loaded from config/reference/symbol_registry.yaml's
`sector` field (already present for all `asset_class: etf` entries, added
alongside the R13-D Phase 1 feasibility check) -- no new config schema.

NOT wired into paper_demo.py or any production strategy yet. This module
is safe to import and use standalone (e.g. from a research script) without
any effect on existing strategies -- matching the explicit Phase 2 scope
boundary documented in docs/console_improvement_tasks.md R13-D ("Phase 2
は設計のみ、本番未配線").
"""

from __future__ import annotations

from datetime import datetime, timezone

from stock_swing.core.types import CanonicalRecord
from stock_swing.feature_engine.base_feature import BaseFeature, FeatureResult

DEFAULT_LOOKBACK_DAYS = 63  # ~3 trading months, same round-number default as Phase 1


def _daily_returns_from_bars(records: list[CanonicalRecord]) -> dict[str, float]:
    """Build a {date_iso: daily_return} series for one symbol's sorted bars."""
    price_records = [
        r for r in records
        if r.source_type == "price" and "bar_" in r.event_type
    ]
    if len(price_records) < 2:
        return {}
    sorted_records = sorted(price_records, key=lambda r: r.event_time)
    returns: dict[str, float] = {}
    prev_close: float | None = None
    for rec in sorted_records:
        close = (rec.payload or {}).get("close")
        date_key = rec.event_time.date().isoformat()
        if close is None:
            continue
        close = float(close)
        if prev_close is not None and prev_close > 0:
            returns[date_key] = (close - prev_close) / prev_close
        prev_close = close
    return returns


class SectorMomentumFeature(BaseFeature):
    """Computes trailing-return momentum per sector, for use as the ranking
    signal by any sector-rotation strategy (see
    stock_swing.strategy_engine.sector_rotation_strategy.SectorRotationStrategy).

    This is a GLOBAL feature (symbol=None), analogous to MacroRegimeFeature
    and UsOvernightBenchmarkFeature: the sector ranking is the same
    regardless of which specific ETF a downstream strategy will ultimately
    trade. Per-sector member ETF selection is applied downstream by the
    strategy, not here -- this feature only reports the ranking.
    """

    def __init__(
        self,
        sector_map: dict[str, str],
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        min_coverage_ratio: float = 0.8,
    ):
        """Args:
        sector_map: {symbol: sector} for all ETFs to consider (typically
            loaded from symbol_registry.yaml's `sector` field for
            asset_class=="etf" entries -- see
            src/stock_swing/utils/symbol_registry.py's
            read_symbol_registry()).
        lookback_days: Trailing trading-day window for the momentum score.
        min_coverage_ratio: A sector's trailing score is only reported
            (not None) if at least this fraction of lookback_days had
            return data for at least one member -- guards against a
            thinly-covered sector producing a misleadingly confident
            ranking from a handful of stale/gappy bars.
        """
        self.sector_map = sector_map
        self.lookback_days = lookback_days
        self.min_coverage_ratio = min_coverage_ratio

    def compute(self, records: list[CanonicalRecord]) -> list[FeatureResult]:
        """Compute per-sector trailing momentum scores from ETF price bars.

        Args:
            records: CanonicalRecord bars for the tracked sector ETFs (any
                source providing "bar_*" event types with symbol in
                self.sector_map). IMPORTANT calling convention (found
                during R13-D Phase 2's feature/strategy consistency check,
                2026-08-23, see scripts/r13d_sector_rotation_feature_
                strategy_validation.py): since this feature computes daily
                returns INTERNALLY from the close prices supplied, callers
                must provide at least `lookback_days + 1` days of price
                history per symbol to get a full `lookback_days`-length
                return window -- the return for the FIRST day in the
                window cannot be computed without also knowing the close
                from the day before it. Supplying exactly `lookback_days`
                bars will silently compute only `lookback_days - 1` days
                of actual coverage (still functionally correct, just off
                by one day narrower than the label implies -- verify with
                the coverage-derived quality_flags if this distinction
                matters for your use case).

        Returns:
            Single-element list with one FeatureResult
            (feature_name="sector_momentum", symbol=None), whose `values`
            dict has one {sector_name}_score entry per sector with
            sufficient coverage, plus a "ranked_sectors" list (best-to-worst)
            and "sector_members" metadata for downstream strategy use.
        """
        now = datetime.now(timezone.utc)
        by_symbol: dict[str, list[CanonicalRecord]] = {}
        for r in records:
            if r.symbol in self.sector_map:
                by_symbol.setdefault(r.symbol, []).append(r)

        symbol_returns = {sym: _daily_returns_from_bars(recs) for sym, recs in by_symbol.items()}

        sector_members: dict[str, list[str]] = {}
        for sym, sector in self.sector_map.items():
            if symbol_returns.get(sym):
                sector_members.setdefault(sector, []).append(sym)

        all_dates = sorted(set().union(*[set(r.keys()) for r in symbol_returns.values()])) if symbol_returns else []

        sector_scores: dict[str, float | None] = {}
        quality_flags: list[str] = []
        window_dates = all_dates[-self.lookback_days:] if all_dates else []

        for sector, members in sector_members.items():
            cum = 1.0
            n_found = 0
            for d in window_dates:
                day_member_returns = [symbol_returns[m][d] for m in members if d in symbol_returns[m]]
                if day_member_returns:
                    day_avg = sum(day_member_returns) / len(day_member_returns)
                    cum *= (1 + day_avg)
                    n_found += 1
            # AUDIT-STYLE FIX (2026-08-23, caught by own test suite before
            # ship): coverage must be measured against the REQUESTED
            # lookback_days, not len(window_dates) -- window_dates silently
            # shrinks to whatever history actually exists (via the
            # all_dates[-self.lookback_days:] slice above), so comparing
            # against its own length made the coverage guard a no-op
            # whenever less than lookback_days of history was available
            # (e.g. 2 available days / 2-day window == 100% "coverage" even
            # though the user asked for a 60-day lookback).
            coverage = (n_found / self.lookback_days) if self.lookback_days else 0.0
            if coverage >= self.min_coverage_ratio:
                sector_scores[sector] = round(cum - 1.0, 6)
            else:
                sector_scores[sector] = None
                quality_flags.append(f"insufficient_coverage:{sector}")

        ranked = sorted(
            [(s, v) for s, v in sector_scores.items() if v is not None],
            key=lambda x: -x[1],
        )
        ranked_sectors = [s for s, _ in ranked]

        values: dict[str, object] = {f"{sector}_score": score for sector, score in sector_scores.items()}
        values["ranked_sectors"] = ranked_sectors

        return [
            FeatureResult(
                feature_name="sector_momentum",
                symbol=None,
                computed_at=now,
                values=values,
                metadata={
                    "lookback_days": self.lookback_days,
                    "sector_members": sector_members,
                    "window_start": window_dates[0] if window_dates else None,
                    "window_end": window_dates[-1] if window_dates else None,
                },
                quality_flags=quality_flags,
            )
        ]
