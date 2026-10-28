"""Helpers for extracting strict JSON payloads from noisy command output."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

_ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


@dataclass(frozen=True)
class JsonParseResult:
    ok: bool
    data: Any = None
    error: str | None = None
    sanitized_text: str | None = None
    extracted_fragment: str | None = None


def sanitize_structured_output(text: str) -> str:
    """Remove ANSI escapes and unsafe control chars without repairing JSON."""
    cleaned = _ANSI_ESCAPE_RE.sub("", text or "")
    kept: list[str] = []
    for ch in cleaned:
        if ch in "\n\r\t" or ord(ch) >= 32:
            kept.append(ch)
    return "".join(kept).strip()


def extract_json_fragment(text: str) -> str | None:
    """Extract the first balanced top-level JSON object/array from text."""
    if not text:
        return None

    start = None
    opening = None
    for idx, ch in enumerate(text):
        if ch in "{[":
            start = idx
            opening = ch
            break
    if start is None or opening is None:
        return None

    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escape = False

    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == opening:
            depth += 1
        elif ch == closing:
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]

    return None


def parse_json_from_output(text: str) -> JsonParseResult:
    """Parse structured JSON from command output without accepting malformed fragments."""
    sanitized = sanitize_structured_output(text)
    fragment = extract_json_fragment(sanitized)
    if fragment is None:
        return JsonParseResult(
            ok=False,
            error="no balanced JSON object or array found in command output",
            sanitized_text=sanitized,
        )
    try:
        return JsonParseResult(
            ok=True,
            data=json.loads(fragment),
            sanitized_text=sanitized,
            extracted_fragment=fragment,
        )
    except json.JSONDecodeError as exc:
        return JsonParseResult(
            ok=False,
            error=f"{exc.msg} at line {exc.lineno} column {exc.colno} (pos {exc.pos})",
            sanitized_text=sanitized,
            extracted_fragment=fragment,
        )
