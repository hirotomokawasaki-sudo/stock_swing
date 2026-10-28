from __future__ import annotations

from abc import ABC, abstractmethod

from stock_swing.core.types import DecisionRecord


class DecisionEngine(ABC):
    @abstractmethod
    def decide(self, signal: dict, risk_result: dict, mode: str) -> DecisionRecord:
        raise NotImplementedError
