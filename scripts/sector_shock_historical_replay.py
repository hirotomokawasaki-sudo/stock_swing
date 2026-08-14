"""
Sector Shock A/B: Historical Replay Data Accumulation
========================================================

R3-v2 の Activation criteria for A/B の一つ:
  "historical shock replay >= 100 events"

これに向けたデータ蓄積の第一歩として、過去の loss-mitigation exit トレード
（stop_loss + breakeven_stop、計111件、2026-05-14〜2026-07-30）の exit 日に
ついて、その時点の実際のセクターベンチマークリターン（SMH/SOXX/QQQ/SPY/SOXQ、
data/benchmarks/benchmark_returns.csv）を使い、SectorShockAnalyzer.classify()
で「もし当時 sector_shock_hold ロジックが有効だったら、どう分類されていたか」
を再現・記録する。

stop_loss + breakeven_stop を対象にしたのは、本番実装（paper_demo.py）が
SectorShockAnalyzer.classify() を全 exit_signals に適用しているため（exit_reason
でのフィルタなし）で、実際の運用と一致させるため。trailing_stop/time_based/
corporate_action は利確・期限切れ系の exit であり、sector-shock hold の判断が
同じ意味を持たないため対象外とする。

これは shadow ログ（data/sector_shock_shadow_log.jsonl、2026-07-23以降のみ）を
補完するもの。過去のトレードは shadow ロジック導入前に発生しているため記録が
存在せず、A/B開始条件の「historical shock replay >= 100 events」を満たすには
過去データの遡及的な再構築が必須。

注意:
- 本スクリプトは exit 判断を変更しない（read-only、過去データの再分類のみ）。
- symbol_1d_return_pct は当該シンボルの exit 当日の日次リターンを yfinance から
  取得する（get_symbol_sector_returns と同じ per-symbol benchmark 選択ロジックを
  再利用）。
- 出力は data/sector_shock_historical_replay_log.jsonl に追記（shadow log とは
  別ファイルで、混同を避ける）。
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

import yaml
import yfinance as yf

from stock_swing.strategy_engine.sector_shock_hold import (
    SectorShockAnalyzer,
    SectorShockHoldConfig,
    get_symbol_sector_returns,
)

REPLAY_LOG_PATH = ROOT / "data" / "sector_shock_historical_replay_log.jsonl"


def load_symbol_registry() -> dict:
    reg_path = ROOT / "config" / "reference" / "symbol_registry.yaml"
    with open(reg_path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("symbols", {})


def load_benchmark_returns_by_date() -> dict[str, dict[str, float]]:
    """date -> {benchmark_symbol: daily_return}"""
    csv_path = ROOT / "data" / "benchmarks" / "benchmark_returns.csv"
    by_date: dict[str, dict[str, float]] = defaultdict(dict)
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            date = row.get("date", "")
            sym = row.get("symbol", "")
            ret_str = row.get("daily_return", "")
            if date and sym and ret_str:
                try:
                    by_date[date][sym] = float(ret_str)
                except (TypeError, ValueError):
                    pass
    return dict(by_date)


def load_benchmark_rolling_returns_by_date(column: str = "return_3d") -> dict[str, dict[str, float]]:
    """R7-v2 / R3-v2 (2026-08-14, roadmap gap #5): date -> {benchmark_symbol:
    rolling N-day return}, read from benchmark_returns.csv's precomputed
    return_3d column (same column consumed by paper_demo.py's live
    sector_shock_hold rolling check added 2026-08-14 -- see sector_shock_
    hold.py's sector_shock_rolling_threshold_pct docstring). Used to re-run
    this historical replay with the rolling-window fix applied, to check
    whether the R3-v2 activation criteria's "forward valid stop-trigger
    shadow >= 10" threshold is still an appropriate bar now that rolling
    detection catches shocks the single-day check missed.
    """
    csv_path = ROOT / "data" / "benchmarks" / "benchmark_returns.csv"
    by_date: dict[str, dict[str, float]] = defaultdict(dict)
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            date = row.get("date", "")
            sym = row.get("symbol", "")
            ret_str = row.get(column, "")
            if date and sym and ret_str:
                try:
                    by_date[date][sym] = float(ret_str)
                except (TypeError, ValueError):
                    pass
    return dict(by_date)


# In production (paper_demo.py), SectorShockAnalyzer.classify() is applied to
# ALL exit_signals regardless of exit_reason, not just stop_loss. To match
# that behavior and accumulate more historical replay events toward the R3-v2
# activation criteria (>=100 events), we replay both loss-mitigation exit
# types where a sector-shock-aware hold decision would be meaningful:
# stop_loss and breakeven_stop. trailing_stop/time_based/corporate_action are
# excluded because those are profit-taking/administrative exits where a
# sector-shock hold override would not apply the same way.
REPLAY_EXIT_REASONS = ("stop_loss", "breakeven_stop")


def load_stop_loss_trades() -> list[dict]:
    state_path = ROOT / "data" / "tracking" / "pnl_state.json"
    with open(state_path) as f:
        state = json.load(f)
    trades = state.get("trades", [])
    return [
        t for t in trades
        if t.get("status") == "closed" and t.get("exit_reason") in REPLAY_EXIT_REASONS
    ]


# Cache keyed by symbol only, but populated with the FULL date range spanning
# all trades up front (see _prefetch_all_symbol_prices), so a symbol appearing
# at multiple different exit dates is never re-fetched with a narrow window
# that silently misses later dates (bug found 2026-08-05: original per-call
# +-10/+2 day window meant the 2nd+ occurrence of a repeated symbol used the
# 1st occurrence's stale narrow window and returned None for dates outside it).
_price_cache: dict[str, dict[str, float]] = {}


def _prefetch_all_symbol_prices(symbol_exit_dates: dict[str, list[str]]) -> None:
    """Fetch one wide-range daily price history per symbol covering all its exit dates."""
    for symbol, exit_dates in symbol_exit_dates.items():
        min_date = min(datetime.fromisoformat(d).date() for d in exit_dates)
        max_date = max(datetime.fromisoformat(d).date() for d in exit_dates)
        start = min_date - timedelta(days=10)
        end = max_date + timedelta(days=5)
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(start=start.isoformat(), end=end.isoformat(), interval="1d")
            prices = {}
            for idx, row in hist.iterrows():
                d = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
                prices[d] = float(row["Close"])
            _price_cache[symbol] = prices
        except Exception as e:
            print(f"    [WARN] {symbol}: {e}", file=sys.stderr)
            _price_cache[symbol] = {}


def fetch_symbol_return_1d(symbol: str, exit_date_str: str) -> float | None:
    """Look up the symbol's own 1-day return on exit_date (close-to-close)
    from the prefetched wide-range cache populated by _prefetch_all_symbol_prices.
    """
    prices = _price_cache.get(symbol, {})
    sorted_dates = sorted(prices.keys())
    if exit_date_str not in prices:
        return None
    idx = sorted_dates.index(exit_date_str)
    if idx == 0:
        return None
    prev_date = sorted_dates[idx - 1]
    prev_close = prices[prev_date]
    close = prices[exit_date_str]
    if prev_close == 0:
        return None
    return (close - prev_close) / prev_close


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Sector shock historical replay")
    parser.add_argument(
        "--rolling", action="store_true",
        help=(
            "R7-v2/R3-v2 (2026-08-14, roadmap gap #5): also pass rolling "
            "3-day sector returns to classify() (the same rolling check "
            "added to the live paper_demo.py path on 2026-08-14). Writes "
            "to a separate log file (sector_shock_historical_replay_log_"
            "rolling.jsonl) so it does not mix with the original single-"
            "day-only replay log."
        ),
    )
    args = parser.parse_args()

    symbol_registry = load_symbol_registry()
    benchmark_by_date = load_benchmark_returns_by_date()
    benchmark_rolling_by_date = load_benchmark_rolling_returns_by_date() if args.rolling else {}
    trades = load_stop_loss_trades()

    config = SectorShockHoldConfig.from_env()
    analyzer = SectorShockAnalyzer(config)

    replay_log_path = REPLAY_LOG_PATH
    if args.rolling:
        replay_log_path = ROOT / "data" / "sector_shock_historical_replay_log_rolling.jsonl"

    print(f"Historical stop_loss trades: {len(trades)}")
    print(f"Benchmark return dates available: {len(benchmark_by_date)}")
    if args.rolling:
        print(f"Rolling (3d) benchmark return dates available: {len(benchmark_rolling_by_date)}")

    symbol_exit_dates: dict[str, list[str]] = defaultdict(list)
    for t in trades:
        symbol = t.get("symbol", "?")
        exit_date = (t.get("exit_time") or "")[:10]
        if exit_date:
            symbol_exit_dates[symbol].append(exit_date)

    print(f"Prefetching wide-range price history for {len(symbol_exit_dates)} unique symbols...\n")
    _prefetch_all_symbol_prices(symbol_exit_dates)

    n_replayed = 0
    n_no_benchmark_data = 0
    n_no_symbol_data = 0
    classification_counts: dict[str, int] = defaultdict(int)

    for t in trades:
        symbol = t.get("symbol", "?")
        exit_time = t.get("exit_time") or ""
        return_pct = t.get("return_pct") or 0
        holding_days = t.get("holding_days") or 0
        exit_date = exit_time[:10]

        if not exit_date or exit_date not in benchmark_by_date:
            n_no_benchmark_data += 1
            continue

        all_benchmark_1d = benchmark_by_date[exit_date]
        symbol_1d_return = fetch_symbol_return_1d(symbol, exit_date)
        if symbol_1d_return is None:
            n_no_symbol_data += 1
            continue

        sector_1d_returns = get_symbol_sector_returns(
            symbol=symbol,
            all_benchmark_returns=all_benchmark_1d,
            symbol_registry=symbol_registry,
            fallback_benchmarks=config.benchmark_symbols,
        )

        sector_rolling_returns = None
        if args.rolling:
            all_benchmark_rolling = benchmark_rolling_by_date.get(exit_date, {})
            sector_rolling_returns = get_symbol_sector_returns(
                symbol=symbol,
                all_benchmark_returns=all_benchmark_rolling,
                symbol_registry=symbol_registry,
                fallback_benchmarks=config.benchmark_symbols,
            )

        result = analyzer.classify(
            symbol=symbol,
            current_return_pct=return_pct,
            symbol_1d_return_pct=symbol_1d_return,
            sector_1d_return_pcts=sector_1d_returns,
            sector_rolling_return_pcts=sector_rolling_returns,
            days_held=int(holding_days),
        )

        classification_counts[result.classification] += 1
        n_replayed += 1

        record = {
            "logged_at": datetime.now().isoformat(),
            "replay_source": "historical_exit_trade",
            "trade_id": t.get("trade_id"),
            "symbol": symbol,
            "exit_date": exit_date,
            "original_exit_reason": t.get("exit_reason"),
            "classification": result.classification,
            "recommended_action": result.recommended_action,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
            **result.shadow_log,
        }
        replay_log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(replay_log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    print("=" * 70)
    print("Historical Replay Summary")
    print("=" * 70)
    print(f"Total stop_loss trades:       {len(trades)}")
    print(f"Replayed (classified):       {n_replayed}")
    print(f"  No benchmark data for date: {n_no_benchmark_data}")
    print(f"  No symbol price data:       {n_no_symbol_data}")
    print()
    print("Classification breakdown:")
    for cls, count in sorted(classification_counts.items(), key=lambda x: -x[1]):
        print(f"  {cls:30s} {count:3d}")
    print()
    valid_shock_events = classification_counts.get("sector_shock_hold", 0) + \
        classification_counts.get("relative_weakness_exit", 0)
    print(f"Valid sector-shock-context events (sector_shock_hold + relative_weakness_exit): {valid_shock_events}")
    print(f"R3-v2 activation target: historical shock replay >= 100 events")
    print(f"Current progress: {n_replayed} historical trades replayed "
          f"({valid_shock_events} occurred during a detected sector shock)")
    print()
    print(f"Log written to: {replay_log_path}")


if __name__ == "__main__":
    main()
