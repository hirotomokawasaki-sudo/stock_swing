from __future__ import annotations

from stock_swing.openclaw.interfaces import OpenClawAdapter


class BasicOpenClawAdapter(OpenClawAdapter):
    def build_prompt_input(self, context: dict) -> dict:
        return {"version": "v1", "context": context}
