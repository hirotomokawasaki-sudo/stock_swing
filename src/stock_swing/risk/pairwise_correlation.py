"""R5-v2 (2026-08-14): pairwise correlation between held symbols.

Context (docs/console_improvement_tasks.md R5-v2, REOPENED):
    "market beta / sector/factor exposure / pairwise correlation / top-5
    concentration 未実装". Cluster cap (correlation_cluster.py, fixed
    hand-authored groupings), top-5 concentration, portfolio beta, and
    clean-cohort PF were each addressed separately (see promotion_gate.py).
    This module fills the one remaining gap: an *actual* correlation
    coefficient between symbol return series, rather than a fixed cluster
    label.

Data source
-----------
There is no dedicated historical daily-bar store for arbitrary symbols in
this codebase (data/backtest_price_cache/ is a stale one-off snapshot from
a prior backtest run in 2026-05; data/benchmarks/ only covers the 5 sector
ETFs). What *does* exist continuously is data/raw/broker/broker_{symbol}_
*_marketdata_bars-endpoint snapshots -- collect_data.collect_broker_bars()
has been fetching a short rolling window of daily bars per symbol on every
collection cron run since 2026-08-01. Individual snapshot files only hold
~5 days each, but scanning *all* accumulated snapshot files for a symbol
and de-duplicating by bar date reconstructs a longer daily-close history
for free, with no new API calls or new data collection required.

Design notes
------------
- Pure function core (compute_pairwise_correlation) operates on plain
  {symbol: {date: close}} dicts so it is trivially unit-testable without
  any filesystem access. The filesystem-scanning helper
  (build_daily_closes_from_raw_bars) is a separate, thin I/O layer.
- Fail-closed: pairs with too few overlapping trading days
  (< min_overlap_days) are reported as "insufficient_data" rather than a
  potentially misleading correlation coefficient computed from a handful
  of points.
- Read-only / observability: this module does not block anything by
  itself; it feeds promotion_gate.py's combined readiness verdict, which
  in turn is explicitly documented (and tested) as supplementary,
  non-blocking information in scripts/check_go_no_go.py.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any


def build_daily_closes_from_raw_bars(
    symbol: str,
    raw_broker_dir: Path,
) -> dict[str, float]:
    """Reconstruct a {date: close} series for symbol from accumulated
    data/raw/broker/broker_{symbol}_*.json snapshots (marketdata/bars
    endpoint only). Returns {} on any I/O or parse error for an individual
    file (skips that file, does not raise) and {} if the directory or no
    matching files exist.

    Args:
        symbol: Ticker symbol (case-insensitive; matched against the
            lowercase filename convention used by collect_data.py).
        raw_broker_dir: Path to data/raw/broker/.
    """
    closes: dict[str, float] = {}
    if not raw_broker_dir.exists():
        return closes

    pattern = f"broker_{symbol.lower()}_*.json"
    for path in raw_broker_dir.glob(pattern):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("endpoint") != "marketdata/bars":
            continue
        bars = (data.get("payload") or {}).get("bars") or []
        for bar in bars:
            date = str(bar.get("t") or "")[:10]
            close = bar.get("c")
            if date and close is not None:
                closes[date] = float(close)

    return closes


def _daily_returns(closes: dict[str, float]) -> dict[str, float]:
    """Convert a {date: close} series (sorted by date) to {date: return}."""
    dates = sorted(closes.keys())
    returns: dict[str, float] = {}
    prev_close = None
    for date in dates:
        close = closes[date]
        if prev_close is not None and prev_close != 0:
            returns[date] = (close - prev_close) / prev_close
        prev_close = close
    return returns


def compute_pair_correlation(
    closes_a: dict[str, float],
    closes_b: dict[str, float],
    min_overlap_days: int = 10,
) -> dict[str, Any]:
    """Pearson correlation of daily returns between two {date: close} series.

    Args:
        closes_a, closes_b: {date: close} series for two symbols.
        min_overlap_days: minimum number of overlapping return dates
            required to compute a correlation; below this, returns
            available=False rather than a noisy/misleading coefficient.

    Returns:
        {"available": bool, "correlation": float|None, "overlap_days": int,
         "reason": str|None}
    """
    returns_a = _daily_returns(closes_a)
    returns_b = _daily_returns(closes_b)
    common_dates = sorted(set(returns_a) & set(returns_b))
    n = len(common_dates)

    if n < min_overlap_days:
        return {
            "available": False,
            "correlation": None,
            "overlap_days": n,
            "reason": f"insufficient_overlap (n={n} < min={min_overlap_days})",
        }

    series_a = [returns_a[d] for d in common_dates]
    series_b = [returns_b[d] for d in common_dates]

    try:
        # NOTE: population variance/covariance (denominator n), not sample
        # variance (n-1) -- statistics.pvariance() must match the /n used
        # for covariance below, or the resulting ratio is systematically
        # off by a factor of (n-1)/n (e.g. n=14 -> ratio 13/14 = 0.9286,
        # which silently looked like "a plausible but wrong" correlation
        # instead of an obvious bug -- caught by
        # test_perfectly_correlated_series expecting exactly 1.0).
        var_a = statistics.pvariance(series_a)
        var_b = statistics.pvariance(series_b)
    except statistics.StatisticsError:
        return {
            "available": False,
            "correlation": None,
            "overlap_days": n,
            "reason": "degenerate_series",
        }

    if var_a == 0 or var_b == 0:
        return {
            "available": False,
            "correlation": None,
            "overlap_days": n,
            "reason": "zero_variance",
        }

    mean_a = statistics.mean(series_a)
    mean_b = statistics.mean(series_b)
    covariance = sum(
        (a - mean_a) * (b - mean_b) for a, b in zip(series_a, series_b)
    ) / n
    correlation = covariance / ((var_a ** 0.5) * (var_b ** 0.5))
    # Clamp for float precision (correlation must be in [-1, 1]).
    correlation = max(-1.0, min(1.0, correlation))

    return {
        "available": True,
        "correlation": round(correlation, 4),
        "overlap_days": n,
        "reason": None,
    }


def compute_pairwise_correlation(
    closes_by_symbol: dict[str, dict[str, float]],
    min_overlap_days: int = 10,
) -> list[dict[str, Any]]:
    """Compute pairwise correlation for every symbol pair in
    closes_by_symbol.

    Args:
        closes_by_symbol: {symbol: {date: close}}.
        min_overlap_days: see compute_pair_correlation.

    Returns:
        List of {"symbol_a", "symbol_b", "available", "correlation",
        "overlap_days", "reason"} dicts, one per unique unordered pair
        (symbols sorted alphabetically within each pair, pairs sorted by
        symbol_a then symbol_b for deterministic output).
    """
    symbols = sorted(closes_by_symbol.keys())
    results: list[dict[str, Any]] = []
    for i, sym_a in enumerate(symbols):
        for sym_b in symbols[i + 1:]:
            pair_result = compute_pair_correlation(
                closes_by_symbol[sym_a], closes_by_symbol[sym_b],
                min_overlap_days=min_overlap_days,
            )
            results.append({
                "symbol_a": sym_a,
                "symbol_b": sym_b,
                **pair_result,
            })
    return results


def summarize_high_correlation_pairs(
    pairwise_results: list[dict[str, Any]],
    high_correlation_threshold: float = 0.80,
) -> dict[str, Any]:
    """Summarize pairwise correlation results into a promotion-gate-ready
    verdict: are any *currently evaluated* symbol pairs highly correlated
    (>= high_correlation_threshold), among pairs where a correlation was
    actually computable.

    Fail-closed semantics: if there is no data at all (empty input) OR
    every pair was "insufficient_data", this is reported as
    available=False (unproven, not "assumed fine") rather than silently
    passing an unverified portfolio.
    """
    available_pairs = [r for r in pairwise_results if r.get("available")]
    if not pairwise_results or not available_pairs:
        return {
            "available": False,
            "high_correlation_pairs": [],
            "checked_pairs": len(pairwise_results),
            "available_pairs": 0,
            "reason": "no_computable_pairs",
        }

    high_pairs = [
        r for r in available_pairs
        if abs(r["correlation"]) >= high_correlation_threshold
    ]
    return {
        "available": True,
        "high_correlation_pairs": [
            {"symbol_a": r["symbol_a"], "symbol_b": r["symbol_b"], "correlation": r["correlation"]}
            for r in high_pairs
        ],
        "checked_pairs": len(pairwise_results),
        "available_pairs": len(available_pairs),
        "reason": None,
    }
