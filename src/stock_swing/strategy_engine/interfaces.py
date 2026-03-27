from __future__ import annotations

from abc import ABC, abstractmethod


class Strategy(ABC):
    strategy_id: str

    @abstractmethod
    def generate(self, features: dict) -> dict:
        raise NotImplementedError
