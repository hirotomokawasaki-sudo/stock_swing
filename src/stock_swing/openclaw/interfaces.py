from __future__ import annotations

from abc import ABC, abstractmethod


class OpenClawAdapter(ABC):
    @abstractmethod
    def build_prompt_input(self, context: dict) -> dict:
        raise NotImplementedError
