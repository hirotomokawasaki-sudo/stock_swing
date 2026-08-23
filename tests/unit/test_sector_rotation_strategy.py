"""Tests for SectorRotationStrategy (2026-08-23, R13-D Phase 2 — ETF
sector rotation strategy design).
"""

from __future__ import annotations

from datetime import datetime, timezone

from stock_swing.feature_engine.base_feature import FeatureResult
from stock_swing.strategy_engine.sector_rotation_strategy import SectorRotationStrategy


def _sector_momentum_feature(
    ranked_sectors: list[str],
    scores: dict[str, float | None],
    sector_members: dict[str, list[str]],
    lookback_days: int = 63,
) -> FeatureResult:
    values = {f"{s}_score": v for s, v in scores.items()}
    values["ranked_sectors"] = ranked_sectors
    return FeatureResult(
        feature_name="sector_momentum",
        symbol=None,
        computed_at=datetime.now(timezone.utc),
        values=values,
        metadata={"lookback_days": lookback_days, "sector_members": sector_members},
        quality_flags=[],
    )


class TestSectorRotationStrategyBasics:
    def test_returns_empty_when_no_sector_momentum_feature_present(self) -> None:
        strategy = SectorRotationStrategy(top_n=2)
        signals = strategy.generate(features=[])
        assert signals == []

    def test_returns_empty_when_ranked_sectors_is_empty(self) -> None:
        feature = _sector_momentum_feature(ranked_sectors=[], scores={}, sector_members={})
        strategy = SectorRotationStrategy(top_n=2)
        assert strategy.generate(features=[feature]) == []

    def test_generates_signal_per_member_of_top_n_sectors(self) -> None:
        feature = _sector_momentum_feature(
            ranked_sectors=["semiconductor", "software", "robotics_ai"],
            scores={"semiconductor": 0.30, "software": 0.15, "robotics_ai": -0.05},
            sector_members={
                "semiconductor": ["SOXX", "SMH"],
                "software": ["QTEC"],
                "robotics_ai": ["BOTZ", "ROBO"],
            },
        )
        strategy = SectorRotationStrategy(top_n=2)
        signals = strategy.generate(features=[feature])

        symbols = {s.symbol for s in signals}
        # top_n=2 -> semiconductor + software members only, robotics_ai excluded.
        assert symbols == {"SOXX", "SMH", "QTEC"}
        assert all(s.action == "buy" for s in signals)
        assert all(s.strategy_id == "sector_rotation_v1" for s in signals)

    def test_only_emits_for_sectors_with_non_none_score(self) -> None:
        feature = _sector_momentum_feature(
            ranked_sectors=["semiconductor"],  # 'software' excluded upstream due to None score
            scores={"semiconductor": 0.10, "software": None},
            sector_members={"semiconductor": ["SOXX"], "software": ["QTEC"]},
        )
        strategy = SectorRotationStrategy(top_n=5)  # top_n larger than available ranked list
        signals = strategy.generate(features=[feature])
        assert {s.symbol for s in signals} == {"SOXX"}

    def test_signal_strength_decreases_with_rank(self) -> None:
        feature = _sector_momentum_feature(
            ranked_sectors=["semiconductor", "software", "robotics_ai"],
            scores={"semiconductor": 0.30, "software": 0.15, "robotics_ai": 0.05},
            sector_members={
                "semiconductor": ["SOXX"],
                "software": ["QTEC"],
                "robotics_ai": ["BOTZ"],
            },
        )
        strategy = SectorRotationStrategy(top_n=3)
        signals = strategy.generate(features=[feature])
        strength_by_symbol = {s.symbol: s.signal_strength for s in signals}
        assert strength_by_symbol["SOXX"] > strength_by_symbol["QTEC"] > strength_by_symbol["BOTZ"]
        # Best sector (rank 0) always gets exactly 1.0.
        assert strength_by_symbol["SOXX"] == 1.0

    def test_top_n_one_gives_full_strength(self) -> None:
        feature = _sector_momentum_feature(
            ranked_sectors=["semiconductor", "software"],
            scores={"semiconductor": 0.30, "software": 0.10},
            sector_members={"semiconductor": ["SOXX"], "software": ["QTEC"]},
        )
        strategy = SectorRotationStrategy(top_n=1)
        signals = strategy.generate(features=[feature])
        assert {s.symbol for s in signals} == {"SOXX"}
        assert signals[0].signal_strength == 1.0

    def test_metadata_includes_sector_and_rank(self) -> None:
        feature = _sector_momentum_feature(
            ranked_sectors=["semiconductor", "software"],
            scores={"semiconductor": 0.30, "software": 0.10},
            sector_members={"semiconductor": ["SOXX"], "software": ["QTEC"]},
        )
        strategy = SectorRotationStrategy(top_n=2)
        signals = strategy.generate(features=[feature])
        soxx_signal = next(s for s in signals if s.symbol == "SOXX")
        assert soxx_signal.metadata["sector"] == "semiconductor"
        assert soxx_signal.metadata["sector_rank"] == 0
        qtec_signal = next(s for s in signals if s.symbol == "QTEC")
        assert qtec_signal.metadata["sector_rank"] == 1

    def test_time_horizon_matches_phase1_hold_days(self) -> None:
        feature = _sector_momentum_feature(
            ranked_sectors=["semiconductor"],
            scores={"semiconductor": 0.30},
            sector_members={"semiconductor": ["SOXX"]},
        )
        strategy = SectorRotationStrategy(top_n=1)
        signals = strategy.generate(features=[feature])
        assert signals[0].time_horizon == "21d"

    def test_confidence_is_signal_strength_times_085(self) -> None:
        feature = _sector_momentum_feature(
            ranked_sectors=["semiconductor"],
            scores={"semiconductor": 0.30},
            sector_members={"semiconductor": ["SOXX"]},
        )
        strategy = SectorRotationStrategy(top_n=1)
        signals = strategy.generate(features=[feature])
        assert abs(signals[0].confidence - 0.85) < 1e-6
