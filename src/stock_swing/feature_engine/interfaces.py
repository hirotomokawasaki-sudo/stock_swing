from __future__ import annotations

from abc import ABC, abstractmethod

from stock_swing.core.types import CanonicalRecord


class FeatureBuilder(ABC):
    @abstractmethod
    def build(self, records: list[CanonicalRecord]) -> dict:
        raise NotImplementedError
