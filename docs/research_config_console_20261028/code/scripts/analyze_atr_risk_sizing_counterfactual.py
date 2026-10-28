#!/usr/bin/env python3
"""R18-C: ATR fixed-risk sizing counterfactual (research only).

The pre-registered design is documented in
``docs/r18c_atr_risk_sizing_preregistration_20260908.md``.  This script
never submits orders and never edits strategy/runtime configuration.  It
rescales historical closed-trade PnL using a reduce-only ATR risk cap.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

STATE_PATH = PROJECT_ROOT / "data" / "tracking" / "pnl_state.json"
CACHE_DIR = PROJECT_ROOT / "data" / "r11_price_cache"
OUTPUT_DIR = PROJECT_ROOT / "docs" / "r18c_atr_risk_sizing_validation_20260908"
HOLDOUT_START = "2026-08-08"
ATR_WINDOW = 14
RISK_WIDTH_FLOOR_PCT = 0.05


@dataclass(frozen=True)
class Variant:
    variant_id: str
    risk_budget_pct: float
    atr_multiple: float
    primary: bool = False


VARIANTS = (
    Variant("P0", 0.003, 2.0, True),
    Variant("S1", 0.003, 1.5),
    Variant("S2", 0.005, 2.0),
    Variant("S3", 0.005, 1.5),
)


def load_state(path: Path = STATE_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        state = json.load(fh)
    equity = state.get("baseline_equity")
    if not isinstance(equity, (int, float)) or equity <= 0:
        raise ValueError("baseline_equity must be a positive number (fail-closed)")
    return state


def load_cached_bars(symbol: str, cache_dir: Path = CACHE_DIR) -> dict[str, dict[str, float]]:
    path = cache_dir / f"{symbol}.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def fetch_bars(symbol: str, start: str, end: str) -> dict[str, dict[str, float]]:
    """Fetch bars in memory only; the canonical cache is never overwritten."""
    import yfinance as yf

    hist = yf.Ticker(symbol).history(start=start, end=end, interval="1d", auto_adjust=False)
    bars: dict[str, dict[str, float]] = {}
    if hist.empty:
        return bars
    for idx, row in hist.iterrows():
        values = {name: row.get(name) for name in ("Open", "High", "Low", "Close")}
        if any(v is None or not math.isfinite(float(v)) for v in values.values()):
            continue
        bars[idx.strftime("%Y-%m-%d")] = {
            "open": float(values["Open"]),
            "high": float(values["High"]),
            "low": float(values["Low"]),
            "close": float(values["Close"]),
        }
    return bars


def ensure_bars_for_entry(
    symbol: str,
    entry_date: str,
    bars_by_symbol: dict[str, dict[str, dict[str, float]]],
) -> dict[str, dict[str, float]]:
    bars = bars_by_symbol.setdefault(symbol, load_cached_bars(symbol))
    latest = max(bars) if bars else ""
    if latest < entry_date:
        start = (date.fromisoformat(entry_date) - timedelta(days=ATR_WINDOW * 4)).isoformat()
        end = (date.fromisoformat(entry_date) + timedelta(days=1)).isoformat()
        try:
            bars.update(fetch_bars(symbol, start, end))
        except Exception as exc:  # external data failure is reported as coverage loss
            print(f"WARN: {symbol} price fetch failed: {exc}", file=sys.stderr)
    return bars


def compute_atr_pct_at_entry(
    bars: dict[str, dict[str, float]], entry_date: str, window: int = ATR_WINDOW,
) -> float | None:
    """Compute trailing ATR% using only completed bars before entry_date."""
    dates = sorted(d for d in bars if d < entry_date)
    if len(dates) < window + 1:
        return None
    dates = dates[-(window + 1):]
    true_ranges: list[float] = []
    for previous_date, current_date in zip(dates, dates[1:]):
        previous_close = float(bars[previous_date]["close"])
        current = bars[current_date]
        high = float(current["high"])
        low = float(current["low"])
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    reference_close = float(bars[dates[-1]]["close"])
    if reference_close <= 0 or not true_ranges:
        return None
    value = (sum(true_ranges) / len(true_ranges)) / reference_close
    return value if math.isfinite(value) and value > 0 else None


def valid_closed_trades(state: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for trade in state.get("trades", []):
        if trade.get("status") != "closed":
            continue
        values = (trade.get("qty"), trade.get("entry_price"), trade.get("pnl"))
        if not all(isinstance(v, (int, float)) and math.isfinite(float(v)) for v in values):
            continue
        if float(trade["qty"]) <= 0 or float(trade["entry_price"]) <= 0:
            continue
        if not (trade.get("entry_time") and trade.get("exit_time") and trade.get("symbol")):
            continue
        rows.append(trade)
    return rows


def rescale_trade(
    trade: dict[str, Any], atr_pct: float, baseline_equity: float, variant: Variant,
) -> dict[str, Any]:
    actual_qty = int(float(trade["qty"]))
    entry_price = float(trade["entry_price"])
    risk_width_pct = max(variant.atr_multiple * atr_pct, RISK_WIDTH_FLOOR_PCT)
    risk_per_share = entry_price * risk_width_pct
    target_qty = max(math.floor(baseline_equity * variant.risk_budget_pct / risk_per_share), 0)
    counterfactual_qty = min(actual_qty, target_qty)
    scale = counterfactual_qty / actual_qty
    actual_pnl = float(trade["pnl"])
    return {
        "symbol": trade["symbol"],
        "exit_time": trade["exit_time"],
        "actual_qty": actual_qty,
        "target_qty": target_qty,
        "counterfactual_qty": counterfactual_qty,
        "scale": scale,
        "atr_pct": atr_pct,
        "risk_width_pct": risk_width_pct,
        "actual_pnl": actual_pnl,
        "counterfactual_pnl": actual_pnl * scale,
        "pnl_diff": actual_pnl * scale - actual_pnl,
        "affected": counterfactual_qty < actual_qty,
        "gap_through": float(trade.get("return_pct") or 0.0) <= -0.09,
    }


def profit_factor(pnls: list[float]) -> float | str:
    gross_profit = sum(x for x in pnls if x > 0)
    gross_loss = abs(sum(x for x in pnls if x < 0))
    return round(gross_profit / gross_loss, 4) if gross_loss else "inf"


def max_drawdown(pnls: list[float]) -> float:
    cumulative = peak = 0.0
    worst = 0.0
    for pnl in pnls:
        cumulative += pnl
        peak = max(peak, cumulative)
        worst = min(worst, cumulative - peak)
    return round(worst, 2)


def loss_cvar_5(pnls: list[float]) -> float:
    losses = sorted(x for x in pnls if x < 0)
    if not losses:
        return 0.0
    n_tail = max(1, math.ceil(len(pnls) * 0.05))
    return round(sum(losses[:n_tail]) / min(n_tail, len(losses)), 2)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: row["exit_time"])
    actual = [row["actual_pnl"] for row in ordered]
    adjusted = [row["counterfactual_pnl"] for row in ordered]
    affected = [row for row in ordered if row["affected"]]
    gap = [row for row in ordered if row["gap_through"]]
    return {
        "n": len(rows),
        "affected_n": len(affected),
        "actual_net_pnl": round(sum(actual), 2),
        "counterfactual_net_pnl": round(sum(adjusted), 2),
        "net_pnl_diff": round(sum(adjusted) - sum(actual), 2),
        "actual_pf": profit_factor(actual),
        "counterfactual_pf": profit_factor(adjusted),
        "actual_expectancy": round(sum(actual) / len(actual), 2) if actual else None,
        "counterfactual_expectancy": round(sum(adjusted) / len(adjusted), 2) if adjusted else None,
        "actual_loss_cvar_5": loss_cvar_5(actual),
        "counterfactual_loss_cvar_5": loss_cvar_5(adjusted),
        "actual_max_drawdown_usd": max_drawdown(actual),
        "counterfactual_max_drawdown_usd": max_drawdown(adjusted),
        "gap_through_n": len(gap),
        "gap_through_actual_pnl": round(sum(row["actual_pnl"] for row in gap), 2),
        "gap_through_counterfactual_pnl": round(sum(row["counterfactual_pnl"] for row in gap), 2),
        "top_affected": sorted(
            affected, key=lambda row: row["pnl_diff"], reverse=True,
        )[:10],
    }


def evaluate(
    trades: list[dict[str, Any]], baseline_equity: float,
    bars_by_symbol: dict[str, dict[str, dict[str, float]]] | None = None,
) -> dict[str, Any]:
    bars_by_symbol = bars_by_symbol if bars_by_symbol is not None else {}
    prepared: list[tuple[dict[str, Any], float]] = []
    missing: list[dict[str, str]] = []
    for trade in trades:
        entry_date = str(trade["entry_time"])[:10]
        bars = ensure_bars_for_entry(str(trade["symbol"]), entry_date, bars_by_symbol)
        atr_pct = compute_atr_pct_at_entry(bars, entry_date)
        if atr_pct is None:
            missing.append({"symbol": str(trade["symbol"]), "entry_date": entry_date})
            continue
        prepared.append((trade, atr_pct))

    output: dict[str, Any] = {
        "method": {
            "holdout_start": HOLDOUT_START,
            "atr_window": ATR_WINDOW,
            "risk_width_floor_pct": RISK_WIDTH_FLOOR_PCT,
            "reduce_only": True,
            "baseline_equity": baseline_equity,
        },
        "coverage": {
            "eligible_trades": len(trades),
            "with_atr": len(prepared),
            "coverage_pct": round(100 * len(prepared) / len(trades), 2) if trades else 0.0,
            "missing": missing,
        },
        "variants": {},
    }
    for variant in VARIANTS:
        rows = [rescale_trade(trade, atr, baseline_equity, variant) for trade, atr in prepared]
        development = [row for row in rows if row["exit_time"][:10] < HOLDOUT_START]
        holdout = [row for row in rows if row["exit_time"][:10] >= HOLDOUT_START]
        output["variants"][variant.variant_id] = {
            "params": {
                "risk_budget_pct": variant.risk_budget_pct,
                "atr_multiple": variant.atr_multiple,
                "primary": variant.primary,
            },
            "development": summarize(development),
            "holdout": summarize(holdout),
            "full": summarize(rows),
        }
    return output


def print_report(results: dict[str, Any]) -> None:
    coverage = results["coverage"]
    print("R18-C ATR fixed-risk sizing counterfactual (reduce-only)")
    print(f"coverage={coverage['with_atr']}/{coverage['eligible_trades']} ({coverage['coverage_pct']}%)")
    for variant_id, payload in results["variants"].items():
        params = payload["params"]
        print(f"\n{variant_id}: risk={params['risk_budget_pct']:.2%}, ATR={params['atr_multiple']}x")
        for segment in ("development", "holdout", "full"):
            row = payload[segment]
            print(
                f"  {segment:11s} n={row['n']:3d} affected={row['affected_n']:3d} "
                f"diff=${row['net_pnl_diff']:+,.0f} PF={row['actual_pf']}->{row['counterfactual_pf']} "
                f"CVaR5=${row['actual_loss_cvar_5']:,.0f}->${row['counterfactual_loss_cvar_5']:,.0f} "
                f"maxDD=${row['actual_max_drawdown_usd']:,.0f}->${row['counterfactual_max_drawdown_usd']:,.0f}"
            )


def record_trials(results: dict[str, Any]) -> None:
    from stock_swing.research.trial_registry import TrialRecord, TrialRegistry

    registry = TrialRegistry()
    windows = {
        "development": {"start": "2026-05-12", "end": "2026-08-07"},
        "holdout": {"start": HOLDOUT_START, "end": "2026-09-08"},
        "full": {"start": "2026-05-12", "end": "2026-09-08"},
    }
    for variant_id, payload in results["variants"].items():
        for segment in ("development", "holdout", "full"):
            row = payload[segment]
            registry.record(TrialRecord(
                script="analyze_atr_risk_sizing_counterfactual.py",
                roadmap_item="R18-C",
                params={"variant_id": variant_id, **payload["params"]},
                data_window=windows[segment],
                segment=segment,
                n_trades=row["n"],
                profit_factor=row["counterfactual_pf"],
                net_pnl=row["counterfactual_net_pnl"],
                notes="pre-registered reduce-only ATR risk sizing counterfactual",
                extra={
                    "net_pnl_diff": row["net_pnl_diff"],
                    "affected_n": row["affected_n"],
                    "loss_cvar_5": row["counterfactual_loss_cvar_5"],
                },
            ))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--record-trials", action="store_true")
    args = parser.parse_args()

    state = load_state()
    trades = valid_closed_trades(state)
    results = evaluate(trades, float(state["baseline_equity"]))
    print_report(results)
    if args.save:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / "results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
    if args.record_trials:
        record_trials(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
