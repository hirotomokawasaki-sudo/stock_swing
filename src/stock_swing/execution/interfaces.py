from __future__ import annotations

from abc import ABC, abstractmethod

from stock_swing.core.types import DecisionRecord


class Executor(ABC):
    @abstractmethod
    def submit(self, decision: DecisionRecord) -> dict:
        raise NotImplementedError
