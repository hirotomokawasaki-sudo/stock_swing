"""Sector rotation strategy (R13-D Phase 2, ETF sector rotation).

New module (2026-08-23). Independent strategy per
docs/console_improvement_tasks.md R13-D Phase 2 design decision: a NEW
strategy_id ("sector_rotation_v1"), not an extension of
BreakoutMomentumStrategy, for the same architectural reason documented in
docs/jp_semiconductor_ai_expansion_phase2_design.md section 1-A for the
JP overnight-spillover strategy: the signal here has a fundamentally
different structure (relative cross-sectional ranking over a ~3-month
lookback, monthly rebalance cadence) from breakout_momentum's per-symbol
daily momentum threshold. Mixing them under one strategy_id would corrupt
existing PF/WR attribution analysis (same concern raised for
overnight_spillover_v1).

Strategy logic (validated in R13-D Phase 1,
scripts/r13d_etf_sector_rotation_phase1.py, Sharpe=1.370 vs. 1.255
equal-weight-all-sectors baseline and 0.967 SPY buy-and-hold baseline over
2024-08 to 2026-08 real price data -- see
docs/r13d_etf_sector_rotation_phase1_20260823/ for full evidence):
  1. Rank sectors by trailing lookback_days cumulative return (via
     SectorMomentumFeature).
  2. Select the top_n sectors.
  3. Generate a buy CandidateSignal for every member ETF of each selected
     sector, equal-weighted within the strategy's allocation (sizing
     itself remains PositionSizingPolicy's responsibility downstream, same
     as every other strategy in this codebase -- this class only decides
     WHICH symbols to signal, not position size).

IMPORTANT — rebalance-cadence state is NOT implemented here (documented
limitation, tracked as an open Phase 3 design item): this class is
STATELESS per call -- it always emits signals for whatever the CURRENT
top-N sectors are, with no memory of when the last rebalance happened. In
Phase 1's monthly-hold backtest, holdings were only re-evaluated every
hold_days trading days; wiring this into paper_demo.py's daily/multiple-
per-day cron cadence would need an explicit persistent "last rebalance
date" + "current holdings" state file (analogous to how PaperExecutor
tracks open positions), so the strategy does not needlessly reshuffle a
position purely because a later cron run recomputes a fresh top-N.
Building that state machine is explicitly deferred to Phase 3 (post
this Phase 2 design/backtest-validation step) -- wiring it into
production is NOT in scope for this change.

NOT wired into paper_demo.py or config yet. This module is safe to
import and use standalone (e.g. from a research/backtest script) without
any effect on existing strategies.
"""

from __future__ import annotations

from datetime import datetime, timezone

from stock_swing.feature_engine.base_feature import FeatureResult
from stock_swing.strategy_engine.base_strategy import BaseStrategy, CandidateSignal


class SectorRotationStrategy(BaseStrategy):
    """ETF sector-rotation strategy (relative momentum, monthly rebalance
    cadence in its validated Phase 1 backtest form).

    Approved for research/paper-A/B evaluation only (R13-D Phase 2); NOT an
    approved production strategy yet -- see STRATEGY_SCOPE.md conventions
    used by breakout_momentum_v1 / event_swing_v1 for the promotion process
    this strategy would need to go through before live/paper wiring.
    """

    strategy_id = "sector_rotation_v1"

    def __init__(self, top_n: int = 2):
        """Args:
        top_n: Number of top-ranked sectors to hold, matching Phase 1's
            validated default (see docs/r13d_etf_sector_rotation_phase1_
            20260823/robustness_checks.md's parameter-sensitivity table --
            top_n in {1,2,3} all beat both baselines; 2 was Phase 1's
            headline config).
        """
        self.top_n = top_n

    def generate(
        self,
        features: list[FeatureResult],
    ) -> list[CandidateSignal]:
        """Generate candidate buy signals for the current top-N sectors'
        member ETFs.

        Args:
            features: List of computed features; must include a
                "sector_momentum" FeatureResult (see
                stock_swing.feature_engine.sector_momentum_feature.
                SectorMomentumFeature).

        Returns:
            One CandidateSignal per member ETF of each of the top_n
            sectors, or [] if no sector_momentum feature is present or no
            sector has sufficient data.
        """
        sector_features = [f for f in features if f.feature_name == "sector_momentum"]
        if not sector_features:
            return []
        sector_feature = sector_features[0]

        ranked_sectors: list[str] = sector_feature.values.get("ranked_sectors") or []
        sector_members: dict[str, list[str]] = sector_feature.metadata.get("sector_members") or {}
        if not ranked_sectors:
            return []

        top_sectors = ranked_sectors[: self.top_n]
        now = datetime.now(timezone.utc)
        signals: list[CandidateSignal] = []

        for rank, sector in enumerate(top_sectors):
            sector_score = sector_feature.values.get(f"{sector}_score")
            if sector_score is None:
                continue
            # Signal strength: rank-based, scaled to [0.5, 1.0] so the
            # strongest sector gets 1.0 and the weakest selected sector
            # (at rank top_n - 1) gets 0.5 -- deliberately simple, not
            # separately calibrated (matches this codebase's existing
            # "raw momentum -> linear scaling" pattern in
            # BreakoutMomentumStrategy/EventSwingStrategy).
            if self.top_n > 1:
                signal_strength = 1.0 - (rank / (self.top_n - 1)) * 0.5
            else:
                signal_strength = 1.0

            for symbol in sector_members.get(sector, []):
                signals.append(
                    CandidateSignal(
                        strategy_id=self.strategy_id,
                        symbol=symbol,
                        action="buy",
                        signal_strength=round(signal_strength, 4),
                        generated_at=now,
                        time_horizon="21d",  # matches Phase 1's validated hold_days default
                        confidence=round(signal_strength * 0.85, 4),
                        reasoning=(
                            f"Sector '{sector}' ranked #{rank + 1} of {len(ranked_sectors)} "
                            f"by {sector_feature.metadata.get('lookback_days')}d trailing return "
                            f"({sector_score:.2%})"
                        ),
                        feature_refs=[sector_feature.feature_name],
                        metadata={
                            "sector": sector,
                            "sector_rank": rank,
                            "sector_score": sector_score,
                            "lookback_days": sector_feature.metadata.get("lookback_days"),
                            "hold_days_default": 21,
                        },
                    )
                )

        return signals
