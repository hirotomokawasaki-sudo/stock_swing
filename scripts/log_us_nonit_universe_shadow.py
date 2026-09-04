#!/usr/bin/env python3
"""R19: Daily shadow-signal logger for the US non-IT sector universe
-- SHADOW MODE, no orders, no broker connection, no production state.

Background
----------
2026-09-05 user decision (⑥): 現ユニバースはIT/半導体偏重であり、米国内
非ITセクターへの拡張は「取引は行わずshadowで検証環境の構築を進めたい」。
このスクリプトは、現行モメンタムシグナルエンジン（breakout_momentum系）を
非ITユニバースに適用した場合のシグナルを日次で記録するだけの shadow logger。

既存 shadow パターンの踏襲: log_jp_overnight_spillover_shadow.py /
log_sector_rotation_shadow.py と同型のスタンドアロン日次スクリプト
（yfinance利用、ブローカー接続不要）で、**本番の実クラスをそのまま**
end-to-end で通す:

  1. 非ITセクターETFユニバース（下記 UNIVERSE）の日足OHLCVをyfinanceで取得し
     CanonicalRecord 化（log_sector_rotation_shadow.py と同じ構築方法。
     ATR計算のため open/high/low も payload に含める）。
  2. 本番と同一の REAL クラスで判定:
     - PriceMomentumFeature(period_days=20)
       ※ paper_demo.py:886 `PriceMomentumFeature(period_days=args.bar_limit)`、
       --bar-limit デフォルト 20（本番cronはデフォルトのまま）を転記。
       momentum = (最新close − 窓内最古close) / 最古close（同クラス実装）。
     - BreakoutMomentumStrategy(min_momentum=0.05, min_signal_strength=0.60)
       ※ 本番cron payload は `--min-momentum 0.05` を明示、
       min_signal_strength は paper_demo.py:496 デフォルト 0.60
       （2026-07-29に0.40→0.60へ引き上げ）を転記。
       エントリー条件（同クラス generate() 実装）:
         momentum >= 0.05 AND trend == "bullish"（momentum > 0.02）
         AND signal_strength >= 0.60
         where signal_strength = min(momentum / 0.20, 1.0) × macro係数。
  3. 各シンボルの would_signal / signal_strength / 主要特徴量を
     data/us_nonit_universe_shadow_log.jsonl に日次1行で追記。

本番との既知の差分（意図的、ログにも明記）:
- macro_regime: 本番はFREDスナップショット由来のMacroRegimeFeatureで
  expansion×1.1等の係数がかかるが、shadowでは None（係数なし=1.0）とする。
  FRED配線を持ち込まないための簡素化で、strength は保守側（小さめ）に出る。
- entry filter層（PF gate / cluster cap / sector cap 等）は通さない。
  ここで記録するのは「戦略シグナル層でエントリー条件を満たしたか」のみ。

UNIVERSE（第1弾はETFのみ: 流動性高・決算なし・禁止リスト非該当）:
  XLF(金融) XLE(エネルギー) XLV(ヘルスケア) XLI(資本財) XLP(生活必需品)
  XLU(公益) XLB(素材) XLRE(不動産) XLC(通信) + SPY(比較用ベンチマーク)
個別株への拡張は将来タスク（console_improvement_tasks.md R19参照）。

Never submits an order. Never touches the broker or any production state.
Safe to run daily via cron.

Usage:
    python scripts/log_us_nonit_universe_shadow.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance is required. pip install yfinance", file=sys.stderr)
    sys.exit(1)

from stock_swing.core.types import CanonicalRecord  # noqa: E402
from stock_swing.feature_engine.price_momentum_feature import PriceMomentumFeature  # noqa: E402
from stock_swing.strategy_engine.breakout_momentum_strategy import (  # noqa: E402
    BreakoutMomentumStrategy,
)

logger = logging.getLogger(__name__)

SHADOW_LOG_RELATIVE = Path("data/us_nonit_universe_shadow_log.jsonl")

# 第1弾ユニバース: 非ITセクターETF 9本 + 比較用SPY（module docstring参照）
UNIVERSE: tuple[str, ...] = (
    "XLF", "XLE", "XLV", "XLI", "XLP", "XLU", "XLB", "XLRE", "XLC", "SPY",
)

# 本番パラメータの転記元（正確な出所は module docstring 参照）:
#   BAR_LIMIT:            paper_demo.py --bar-limit default 20
#   MIN_MOMENTUM:         本番cron payload --min-momentum 0.05
#   MIN_SIGNAL_STRENGTH:  paper_demo.py --min-signal-strength default 0.60
BAR_LIMIT = 20
MIN_MOMENTUM = 0.05
MIN_SIGNAL_STRENGTH = 0.60
FETCH_LOOKBACK_DAYS_BUFFER = 20  # calendar-day buffer over BAR_LIMIT trading days


def fetch_bars_as_canonical(symbols: list[str], bar_limit: int) -> list[CanonicalRecord]:
    """Fetch recent daily OHLCV via yfinance and wrap as CanonicalRecord.

    Same construction as log_sector_rotation_shadow.fetch_bars_as_canonical,
    extended with open/high/low/volume in the payload so
    PriceMomentumFeature can compute its ATR approximation. Keeps only the
    most recent `bar_limit` bars per symbol to mirror paper_demo's
    fetch_bars(limit=args.bar_limit).
    """
    period_days = bar_limit + FETCH_LOOKBACK_DAYS_BUFFER
    data = yf.download(
        symbols, period=f"{period_days}d", group_by="ticker",
        progress=False, auto_adjust=False, threads=True,
    )
    records: list[CanonicalRecord] = []
    now = datetime.now(timezone.utc)
    for sym in symbols:
        try:
            df = data[sym] if len(symbols) > 1 else data
            df = df.dropna(how="all")
        except (KeyError, TypeError):
            logger.warning("us_nonit_shadow: no data for %s, skipping", sym)
            continue
        df = df.tail(bar_limit)
        for idx, row in df.iterrows():
            try:
                payload = {
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": float(row["Volume"]),
                }
            except (TypeError, ValueError, KeyError):
                continue
            event_time = (
                idx.to_pydatetime().replace(hour=21, tzinfo=timezone.utc)
                if hasattr(idx, "to_pydatetime") else now
            )
            records.append(
                CanonicalRecord(
                    record_id=f"us_nonit_shadow_{sym}_{idx.date().isoformat()}",
                    schema_version="v1",
                    source="yfinance",
                    source_type="price",
                    symbol=sym,
                    event_type="bar_daily",
                    event_time=event_time,
                    as_of=event_time.isoformat(),
                    ingested_at=now,
                    timezone="UTC",
                    payload_version="v1",
                    payload=payload,
                    quality_flags=[],
                )
            )
    return records


def evaluate_universe(
    records: list[CanonicalRecord],
    universe: tuple[str, ...] = UNIVERSE,
    min_momentum: float = MIN_MOMENTUM,
    min_signal_strength: float = MIN_SIGNAL_STRENGTH,
    bar_limit: int = BAR_LIMIT,
) -> dict[str, dict[str, Any]]:
    """Run the REAL production feature+strategy classes over `records` and
    return one observation dict per symbol.

    would_signal is True iff BreakoutMomentumStrategy.generate() (the real
    production class, production thresholds) emits a buy signal for the
    symbol. reference_strength is min(momentum/0.20, 1.0) with no macro
    multiplier (shadow runs have no FRED wiring; see module docstring) and
    is logged for every symbol, signal or not, so near-misses are visible.
    """
    feature = PriceMomentumFeature(period_days=bar_limit)
    feature_results = feature.compute(records)

    strategy = BreakoutMomentumStrategy(
        min_momentum=min_momentum,
        min_signal_strength=min_signal_strength,
        etf_symbols=set(universe),  # all-ETF universe -> breakout_momentum_v1_etf ids
    )
    signals = {s.symbol: s for s in strategy.generate(feature_results)}

    observations: dict[str, dict[str, Any]] = {}
    for fr in feature_results:
        if fr.symbol not in universe:
            continue
        momentum = fr.values.get("momentum", 0.0)
        sig = signals.get(fr.symbol)
        observations[fr.symbol] = {
            "would_signal": sig is not None,
            "signal_strength": sig.signal_strength if sig else None,
            "strategy_id": sig.strategy_id if sig else None,
            # 全銘柄で参照strength（macro係数なし）を記録し、閾値未達の惜しさも見える化
            "reference_strength": round(min(momentum / 0.20, 1.0), 4),
            "momentum": round(momentum, 6),
            "trend": fr.values.get("trend"),
            "bars_used": fr.values.get("bars_used"),
            "latest_close": fr.values.get("latest_close"),
            "atr": fr.values.get("atr"),
            "data_age_days": fr.values.get("data_age_days"),
            "quality_flags": list(fr.quality_flags or []),
        }
    return observations


def log_shadow(record: dict[str, Any], shadow_log_path: Path | str | None = None) -> None:
    """Append a shadow observation record (same pattern as
    log_sector_rotation_shadow.log_shadow)."""
    n_signals = sum(1 for o in (record.get("observations") or {}).values() if o.get("would_signal"))
    logger.info("us_nonit SHADOW date=%s would_signal=%d/%d",
                record.get("date"), n_signals, len(record.get("observations") or {}))
    if shadow_log_path is None:
        return
    log_path = Path(shadow_log_path)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
    except OSError as exc:
        logger.warning("us_nonit_shadow: failed to write log to %s: %s", log_path, exc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print without writing shadow log")
    args = parser.parse_args()

    print("=== US non-IT Universe Shadow Signal Logger (R19) ===")
    print(f"Universe: {', '.join(UNIVERSE)}")
    print(f"Params (transcribed from production, see module docstring): "
          f"bar_limit={BAR_LIMIT} min_momentum={MIN_MOMENTUM} "
          f"min_signal_strength={MIN_SIGNAL_STRENGTH}\n")

    records = fetch_bars_as_canonical(list(UNIVERSE), BAR_LIMIT)
    if not records:
        print("ERROR: no price data fetched, aborting.", file=sys.stderr)
        return 1

    observations = evaluate_universe(records)
    if not observations:
        print("ERROR: feature computation produced no observations.", file=sys.stderr)
        return 1

    for sym in UNIVERSE:
        obs = observations.get(sym)
        if not obs:
            print(f"  {sym:<5} (no data)")
            continue
        mark = "SIGNAL" if obs["would_signal"] else "  -   "
        print(f"  {sym:<5} [{mark}] momentum={obs['momentum']:+.4f} trend={obs['trend']:<8} "
              f"ref_strength={obs['reference_strength']:.2f} close={obs['latest_close']}")

    n_signals = sum(1 for o in observations.values() if o["would_signal"])
    print(f"\nwould_signal: {n_signals}/{len(observations)} symbols")

    record = {
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "date": date.today().isoformat(),
        "universe": list(UNIVERSE),
        "params": {
            "bar_limit": BAR_LIMIT,
            "min_momentum": MIN_MOMENTUM,
            "min_signal_strength": MIN_SIGNAL_STRENGTH,
            "macro_regime": None,  # shadow: no FRED wiring, multiplier = 1.0
        },
        "observations": observations,
        "n_would_signal": n_signals,
        "mode": "shadow",
    }

    if args.dry_run:
        print("\n(--dry-run: nothing written to shadow log)")
        return 0

    log_shadow(record, shadow_log_path=PROJECT_ROOT / SHADOW_LOG_RELATIVE)
    print(f"\nAppended shadow record to {PROJECT_ROOT / SHADOW_LOG_RELATIVE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
