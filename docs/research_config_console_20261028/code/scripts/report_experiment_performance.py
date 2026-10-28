#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from typing import Any


def _float(row: dict[str, str], key: str) -> float:
    try:
        return float(row.get(key, "") or 0)
    except ValueError:
        return 0.0


def summarize(rows: list[dict[str, str]], group_keys: list[str]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[tuple(row.get(key, "") for key in group_keys)].append(row)

    summary = []
    for group, group_rows in sorted(groups.items()):
        pnls = [_float(row, "realized_pnl") for row in group_rows]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        gross_win = sum(wins)
        gross_loss = abs(sum(losses))
        summary.append(
            {
                **dict(zip(group_keys, group)),
                "trades": len(group_rows),
                "win_rate": len(wins) / len(group_rows) if group_rows else 0,
                "gross_win": gross_win,
                "gross_loss": gross_loss,
                "profit_factor": gross_win / gross_loss if gross_loss else None,
                "realized_pnl": sum(pnls),
                "avg_pnl": sum(pnls) / len(pnls) if pnls else 0,
            }
        )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--closed-trades", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--group-by",
        default="experiment_id,experiment_bucket,strategy_version,prompt_version",
    )
    args = parser.parse_args()

    rows = list(csv.DictReader(Path(args.closed_trades).open("r", encoding="utf-8-sig", newline="")))
    group_keys = [key.strip() for key in args.group_by.split(",") if key.strip()]
    summary = summarize(rows, group_keys)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if summary:
        with out_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(summary[0].keys()))
            writer.writeheader()
            writer.writerows(summary)
    else:
        out_path.write_text(",".join(group_keys + ["trades", "win_rate", "realized_pnl"]) + "\n", encoding="utf-8")

    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
