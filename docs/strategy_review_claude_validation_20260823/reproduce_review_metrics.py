#!/usr/bin/env python3
"""Reproduce the quantitative claims in the 2026-08-23 strategy review.

The default mode verifies the immutable, sanitized trade snapshot included in
this review packet.  ``--refresh`` deliberately reads the live tracker and
rebuilds the packet evidence; use it only when creating a new dated packet.

This script uses only the Python standard library.  It does not contact a
broker, submit orders, or mutate the trading system.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


PACKET_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKET_DIR.parents[1]
EVIDENCE_DIR = PACKET_DIR / "evidence"
SNAPSHOT_PATH = EVIDENCE_DIR / "closed_trades_sanitized.json"
METRICS_PATH = EVIDENCE_DIR / "review_metrics.json"
LIVE_STATE_PATH = REPO_ROOT / "data" / "tracking" / "pnl_state.json"
BOOTSTRAP_SEED = 20260823
BOOTSTRAP_SAMPLES = 20_000
ATTRIBUTABLE_SINCE = "2026-08-14"


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(float(value), digits)


def _profit_factor(rows: Iterable[dict[str, Any]]) -> float | None:
    pnls = [float(row.get("pnl") or 0.0) for row in rows]
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    if gross_loss == 0:
        return None
    return gross_profit / gross_loss


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pnls = [float(row.get("pnl") or 0.0) for row in rows]
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    count = len(pnls)
    return {
        "n": count,
        "wins": sum(p > 0 for p in pnls),
        "losses": sum(p < 0 for p in pnls),
        "win_rate": _round(sum(p > 0 for p in pnls) / count if count else None),
        "profit_factor": _round(gross_profit / gross_loss if gross_loss else None),
        "net_pnl": _round(sum(pnls), 2),
        "expectancy": _round(sum(pnls) / count if count else None, 2),
        "gross_profit": _round(gross_profit, 2),
        "gross_loss": _round(gross_loss, 2),
    }


def _quantile(values: list[float], q: float) -> float:
    values = sorted(values)
    if not values:
        raise ValueError("quantile requires at least one value")
    position = (len(values) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def bootstrap(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """IID trade bootstrap used in the original review.

    Important limitation: this assumes trades are exchangeable and independent.
    The packet therefore pairs it with leave-one-symbol-out sensitivity and asks
    the independent reviewer to challenge the IID assumption.
    """
    rng = random.Random(BOOTSTRAP_SEED)
    n = len(rows)
    pf_values: list[float] = []
    expectancy_values: list[float] = []
    positive = 0
    for _ in range(BOOTSTRAP_SAMPLES):
        sample = [rows[rng.randrange(n)] for _ in range(n)]
        pf = _profit_factor(sample)
        expectancy = sum(float(row.get("pnl") or 0.0) for row in sample) / n
        if pf is not None and math.isfinite(pf):
            pf_values.append(pf)
        expectancy_values.append(expectancy)
        if pf is not None and pf > 1.0 and expectancy > 0:
            positive += 1
    return {
        "method": "IID resampling of closed attributable trades with replacement",
        "seed": BOOTSTRAP_SEED,
        "samples": BOOTSTRAP_SAMPLES,
        "limitations": [
            "does not preserve serial dependence",
            "does not preserve overlapping-position dependence",
            "symbol concentration is assessed separately with leave-one-symbol-out",
        ],
        "pf_p05": _round(_quantile(pf_values, 0.05), 3),
        "pf_median": _round(_quantile(pf_values, 0.50), 3),
        "pf_p95": _round(_quantile(pf_values, 0.95), 3),
        "expectancy_p05": _round(_quantile(expectancy_values, 0.05), 2),
        "expectancy_median": _round(_quantile(expectancy_values, 0.50), 2),
        "expectancy_p95": _round(_quantile(expectancy_values, 0.95), 2),
        "fraction_pf_gt_1_and_expectancy_gt_0": _round(positive / BOOTSTRAP_SAMPLES, 4),
    }


def _sanitized_trade(trade: dict[str, Any]) -> dict[str, Any]:
    attributable = bool(
        trade.get("decision_id")
        and trade.get("run_id")
        and trade.get("experiment_id")
    )
    return {
        "symbol": trade.get("symbol"),
        "pnl": _round(float(trade.get("pnl") or 0.0), 2),
        "return_pct": trade.get("return_pct"),
        "entry_time": trade.get("entry_time"),
        "exit_time": trade.get("exit_time"),
        "holding_days": trade.get("holding_days"),
        "exit_reason": trade.get("exit_reason"),
        "asset_class": trade.get("asset_class"),
        "entry_signal_strength": trade.get("entry_signal_strength"),
        "original_strategy_id": trade.get("original_strategy_id"),
        "strategy_version_id": trade.get("strategy_version_id"),
        "has_decision_id": bool(trade.get("decision_id")),
        "has_run_id": bool(trade.get("run_id")),
        "has_experiment_id": bool(trade.get("experiment_id")),
        "attributable": attributable,
    }


def _by_group(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "unknown")].append(row)
    return {name: summarize(group) for name, group in sorted(grouped.items())}


def calculate_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    attributable = [row for row in rows if row.get("attributable")]
    latest = [
        row for row in attributable
        if str(row.get("exit_time") or "")[:10] >= ATTRIBUTABLE_SINCE
    ]

    leave_one_symbol_out: dict[str, Any] = {}
    for symbol in sorted({str(row.get("symbol")) for row in attributable}):
        remaining = [row for row in attributable if row.get("symbol") != symbol]
        leave_one_symbol_out[symbol] = summarize(remaining)

    score_buckets = {
        "low_lt_0_65": [
            row for row in attributable
            if row.get("entry_signal_strength") is not None
            and float(row["entry_signal_strength"]) < 0.65
        ],
        "standard_0_65_to_lt_0_85": [
            row for row in attributable
            if row.get("entry_signal_strength") is not None
            and 0.65 <= float(row["entry_signal_strength"]) < 0.85
        ],
        "high_ge_0_85": [
            row for row in attributable
            if row.get("entry_signal_strength") is not None
            and float(row["entry_signal_strength"]) >= 0.85
        ],
    }

    return {
        "definitions": {
            "closed": "status == closed in the tracker before sanitization",
            "attributable": "decision_id, run_id, and experiment_id are all present",
            "latest_attributable": f"attributable and exit date >= {ATTRIBUTABLE_SINCE}",
            "profit_factor": "gross positive PnL / absolute gross negative PnL",
        },
        "cohorts": {
            "all_closed": summarize(rows),
            "attributable": summarize(attributable),
            "latest_attributable": summarize(latest),
            "stock": summarize([row for row in rows if row.get("asset_class") == "stock"]),
            "etf": summarize([row for row in rows if row.get("asset_class") == "etf"]),
        },
        "attributable_bootstrap": bootstrap(attributable),
        "attributable_leave_one_symbol_out": leave_one_symbol_out,
        "attributable_score_buckets": {
            name: summarize(bucket) for name, bucket in score_buckets.items()
        },
        "exit_reason_all": _by_group(rows, "exit_reason"),
        "exit_reason_attributable": _by_group(attributable, "exit_reason"),
    }


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def refresh() -> None:
    state = _json(LIVE_STATE_PATH)
    rows = [
        _sanitized_trade(trade)
        for trade in state.get("trades", [])
        if trade.get("status") == "closed"
    ]
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "schema": "strategy-review-sanitized-trades-v1",
        "source": "data/tracking/pnl_state.json",
        "source_sha256": hashlib.sha256(LIVE_STATE_PATH.read_bytes()).hexdigest(),
        "git_head": _git_head(),
        "privacy": "account IDs, broker order IDs, trade IDs, fill IDs, and config hashes removed",
        "trades": rows,
    }
    SNAPSHOT_PATH.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    metrics = calculate_metrics(rows)
    METRICS_PATH.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"refreshed {SNAPSHOT_PATH.relative_to(REPO_ROOT)} ({len(rows)} trades)")
    print(f"wrote {METRICS_PATH.relative_to(REPO_ROOT)}")


def verify() -> int:
    snapshot = _json(SNAPSHOT_PATH)
    expected = _json(METRICS_PATH)
    actual = calculate_metrics(list(snapshot.get("trades") or []))
    if actual != expected:
        print("FAIL: recomputed metrics differ from evidence/review_metrics.json")
        return 1
    print("PASS: sanitized snapshot reproduces review_metrics.json exactly")
    print(json.dumps(actual["cohorts"], ensure_ascii=False, indent=2))
    print(json.dumps(actual["attributable_bootstrap"], ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="rebuild sanitized evidence from the current live pnl_state.json",
    )
    args = parser.parse_args()
    if args.refresh:
        refresh()
        return 0
    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
