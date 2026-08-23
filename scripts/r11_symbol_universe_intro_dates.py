"""R13-C (2026-08-23): Derive point-in-time universe introduction dates.

For each symbol currently in config/reference/symbol_registry.yaml (or
historically present in paper_demo.py's DEFAULT_SYMBOLS), find the earliest
git commit date at which that symbol appears in either file's history. This
approximates "the date this symbol became part of the live trading
universe" and is used by r11_backtest_engine_v2.py to gate symbol
eligibility per simulated day (point-in-time universe, fixing the
survivorship bias identified in the R13-C roadmap item: the original
r11_backtest_engine.py applied the CURRENT full registry to the entire
2-year historical window, which lets symbols added in 2026-07/08 based on
hindsight performance "trade" as far back as 2024-08).

IMPORTANT LIMITATION (documented honestly, not hidden): this is a proxy,
not a ground truth. "Date first appears in our git history" measures when
*this system* started tracking the symbol, not necessarily the date an
unbiased contemporary observer in 2024 would have picked it. It cannot
correct for symbol-selection bias itself (e.g., NVDA/AMD were chosen partly
*because* they later performed well) -- only for the more mechanical bias
of literally running trades on a symbol before this system's config ever
listed it. Treat results derived from this gating as "did the CURRENT
strategy config have edge on symbols during their pre-live warm-up window",
not as a full unbiased-universe historical simulation.

Usage:
    python scripts/r11_symbol_universe_intro_dates.py [--save]
    (regenerates data/r11_price_cache/_symbol_universe_intro_dates.json)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "data" / "r11_price_cache" / "_symbol_universe_intro_dates.json"


def _git_log_commits(path: str) -> list[tuple[str, str]]:
    out = subprocess.run(
        ["git", "log", "--format=%H|%ad", "--date=short", "--follow", "--", path],
        capture_output=True, text=True, cwd=ROOT,
    ).stdout
    commits = []
    for line in out.strip().split("\n"):
        if not line:
            continue
        h, d = line.split("|")
        commits.append((h, d))
    return list(reversed(commits))  # oldest first


def _extract_default_symbols_list(content: str) -> list[str] | None:
    m = re.search(r"DEFAULT_SYMBOLS\s*=\s*\[(.*?)\]", content, re.DOTALL)
    if not m:
        return None
    return re.findall(r'"([A-Z0-9.]+)"', m.group(1))


def _extract_registry_symbols(content: str) -> list[str] | None:
    try:
        import yaml
        data = yaml.safe_load(content)
        if isinstance(data, dict) and "symbols" in data:
            return sorted(data["symbols"].keys())
    except Exception:
        pass
    return None


def derive_intro_dates() -> dict[str, str]:
    symbol_first_seen: dict[str, str] = {}

    for h, d in _git_log_commits("src/stock_swing/cli/paper_demo.py"):
        result = subprocess.run(
            ["git", "show", f"{h}:src/stock_swing/cli/paper_demo.py"],
            capture_output=True, text=True, cwd=ROOT,
        )
        if result.returncode != 0:
            continue
        syms = _extract_default_symbols_list(result.stdout)
        if syms is None:
            continue
        for sym in syms:
            symbol_first_seen.setdefault(sym, d)

    for h, d in _git_log_commits("config/reference/symbol_registry.yaml"):
        result = subprocess.run(
            ["git", "show", f"{h}:config/reference/symbol_registry.yaml"],
            capture_output=True, text=True, cwd=ROOT,
        )
        if result.returncode != 0:
            continue
        syms = _extract_registry_symbols(result.stdout)
        if syms is None:
            continue
        for sym in syms:
            symbol_first_seen.setdefault(sym, d)

    return symbol_first_seen


if __name__ == "__main__":
    dates = derive_intro_dates()
    print(f"Derived introduction dates for {len(dates)} symbols.")
    for sym, d in sorted(dates.items(), key=lambda x: (x[1], x[0])):
        print(f"  {d}  {sym}")

    if "--save" in sys.argv:
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT_PATH, "w") as f:
            json.dump(dates, f, indent=2, sort_keys=True)
        print(f"\nSaved: {OUT_PATH}")
