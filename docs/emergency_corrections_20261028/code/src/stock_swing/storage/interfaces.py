from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from stock_swing.core.types import CanonicalRecord, DecisionRecord, RawEnvelope


class RawStore(ABC):
    @abstractmethod
    def write(self, envelope: RawEnvelope, destination: Path) -> Path:
        raise NotImplementedError


class NormalizedStore(ABC):
    @abstractmethod
    def write(self, record: CanonicalRecord, destination: Path) -> Path:
        raise NotImplementedError


class DecisionStore(ABC):
    @abstractmethod
    def write(self, decision: DecisionRecord, destination: Path) -> Path:
        raise NotImplementedError
