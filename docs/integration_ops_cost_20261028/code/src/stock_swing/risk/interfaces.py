from __future__ import annotations

from abc import ABC, abstractmethod


class RiskEngine(ABC):
    @abstractmethod
    def evaluate(self, signal: dict, mode: str) -> dict:
        raise NotImplementedError
