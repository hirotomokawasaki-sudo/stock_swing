from __future__ import annotations

from abc import ABC, abstractmethod

from stock_swing.core.types import CanonicalRecord, RawEnvelope


class Normalizer(ABC):
    @abstractmethod
    def normalize(self, envelope: RawEnvelope) -> list[CanonicalRecord]:
        raise NotImplementedError
