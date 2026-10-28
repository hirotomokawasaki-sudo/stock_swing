from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PromptSpec:
    prompt_version: str
    path: str
    sha256: str
    text: str


class PromptRegistry:
    def __init__(self, prompt_root: Path) -> None:
        self.prompt_root = Path(prompt_root)

    def load(self, relative_path: str, prompt_version: str | None = None) -> PromptSpec:
        path = self.prompt_root / relative_path
        text = path.read_text(encoding="utf-8")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return PromptSpec(
            prompt_version=prompt_version or path.stem,
            path=str(path),
            sha256=digest,
            text=text,
        )
