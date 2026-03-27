from __future__ import annotations

from stock_swing.core.types import CanonicalRecord
from stock_swing.feature_engine.interfaces import FeatureBuilder


class BasicFeatureBuilder(FeatureBuilder):
    def build(self, records: list[CanonicalRecord]) -> dict:
        return {
            "record_count": len(records),
            "symbols": sorted({r.symbol for r in records if r.symbol}),
            "sources": sorted({r.source for r in records}),
        }
