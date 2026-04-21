#!/usr/bin/env python3
"""Data analysis CLI for stock_swing.

Analyzes collected data through the full pipeline:
1. Normalize raw data → canonical records
2. Extract features (MacroRegime, EarningsEvent, PriceMomentum)
3. Generate signals (EventSwing, BreakoutMomentum strategies)
4. Create decisions (DecisionEngine + RiskValidator)
5. Generate reports

Usage:
    python -m stock_swing.cli.analyze_data [--symbols SYMBOL1,SYMBOL2]
"""

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from stock_swing.core import read_runtime_mode, RuntimeMode
from stock_swing.core.path_manager import PathManager
from stock_swing.core.types import RawEnvelope, CanonicalRecord
from stock_swing.decision_engine.decision_engine import DecisionEngine
from stock_swing.feature_engine import MacroRegimeFeature, EarningsEventFeature, PriceMomentumFeature
from stock_swing.normalization import BrokerNormalizer, FinnhubNormalizer, FredNormalizer, SecNormalizer
from stock_swing.storage.stage_store import StageStore
from stock_swing.strategy_engine import BreakoutMomentumStrategy


def main():
    parser = argparse.ArgumentParser(description="Analyze collected data")
    parser.add_argument(
        "--symbols",
        type=str,
        default="NVDA,MSFT,GOOGL,AMZN,META,TSLA,AVGO,AMD,TSM,ASML,INTC,MU,ARM,AMAT,LRCX,KLAC,QCOM,MRVL,PLTR,ADBE,CRM,ORCL,NOW,SNOW,MDB,DDOG,PATH,FICO,SMCI,PANW,CRWD,FTNT,ANET,CSCO,IBM,HPE,DELL,HPQ,SNPS,CDNS,V,MA,INTU,NBIS,CRDO,RBRK,CIEN,SHOC,SOXQ,SOXX,SMH,FTXL,PTF,SMHX,FRWD,TTEQ,GTOP,CHPX,CHPS,PSCT,QTEC,TDIV,SKYY,QTUM",
        help="Comma-separated list of symbols",
    )
    parser.add_argument("--skip-normalization", action="store_true")
    parser.add_argument("--skip-features", action="store_true")
    parser.add_argument("--skip-signals", action="store_true")
    parser.add_argument("--skip-decisions", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("📊 stock_swing Data Analysis")
    print(f"📅 Started at: {datetime.now().isoformat()}")
    print("=" * 60)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    print(f"📈 Symbols: {', '.join(symbols)}")
    print(f"🧪 Dry run: {args.dry_run}")
    print()

    try:
        runtime_mode = read_runtime_mode()
        if isinstance(runtime_mode, str):
            runtime_mode = RuntimeMode(runtime_mode)
        print(f"🔧 Runtime mode: {runtime_mode}")
    except Exception as e:
        runtime_mode = RuntimeMode.PAPER
        print(f"⚠️  Could not read runtime mode: {e}")
        print("   Falling back to paper")

    if args.dry_run:
        print("🧪 DRY RUN MODE")
        return 0

    path_manager = PathManager(project_root)
    store = StageStore(path_manager)

    normalized_records = []
    feature_results = []
    signals = []
    decisions = []

    if not args.skip_normalization:
        print("📝 Step 1: Normalizing raw data...")
        normalized_records = normalize_data(symbols, path_manager, store)
        print(f"  ✅ Normalization complete ({len(normalized_records)} records)")
        print()

    if not args.skip_features:
        print("🔍 Step 2: Extracting features...")
        feature_results = extract_features(normalized_records, store)
        print(f"  ✅ Feature extraction complete ({len(feature_results)} features)")
        print()

    if not args.skip_signals:
        print("📡 Step 3: Generating signals...")
        signals = generate_signals(feature_results, store)
        print(f"  ✅ Signal generation complete ({len(signals)} signals)")
        print()

    if not args.skip_decisions:
        print("🎯 Step 4: Creating decisions...")
        decisions = create_decisions(signals, runtime_mode, store)
        print(f"  ✅ Decision creation complete ({len(decisions)} decisions)")
        print()

    print("📊 Step 5: Generating reports...")
    report = generate_reports(symbols, normalized_records, feature_results, signals, decisions)
    print(f"  ✅ Report generation complete: {report}")
    print()
    print("=" * 60)
    print(f"📅 Completed at: {datetime.now().isoformat()}")
    return 0


def normalize_data(symbols, path_manager, store):
    raw_root = path_manager.data_stage("raw")
    normalizers = {
        "finnhub": FinnhubNormalizer(),
        "fred": FredNormalizer(),
        "sec": SecNormalizer(),
        "broker": BrokerNormalizer(),
    }
    results = []
    for source_dir in sorted(raw_root.iterdir() if raw_root.exists() else []):
        if not source_dir.is_dir() or source_dir.name not in normalizers:
            continue
        normalizer = normalizers[source_dir.name]
        for path in sorted(source_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                raw = RawEnvelope(
                    source=payload["source"],
                    endpoint=payload["endpoint"],
                    fetched_at=datetime.fromisoformat(payload["fetched_at"]),
                    request_params=payload.get("request_params", {}),
                    payload=payload.get("payload", {}),
                )
                records = normalizer.normalize(raw)
                if not records and source_dir.name == "broker" and payload.get("payload", {}).get("bars"):
                    records = normalize_broker_bars_fallback(raw)
                for rec in records:
                    if rec.symbol and rec.symbol.upper() not in symbols:
                        continue
                    filename = f"normalized_{rec.source}_{(rec.symbol or 'macro').lower()}_{rec.record_id[:8]}.json"
                    store.write_normalized(filename, asdict(rec))
                    results.append(rec)
            except Exception:
                continue
    return results


def normalize_broker_bars_fallback(raw: RawEnvelope):
    records = []
    bars = raw.payload.get("bars", [])
    symbol = raw.request_params.get("symbol", "UNKNOWN")
    for idx, bar in enumerate(bars):
        t = bar.get("t")
        event_time = datetime.fromtimestamp(t) if isinstance(t, (int, float)) else datetime.now()
        records.append(CanonicalRecord(
            record_id=f"fallback-{symbol}-{idx}-{t}",
            schema_version="v1",
            source=raw.source,
            source_type="price",
            symbol=symbol,
            event_type="bar_1day",
            event_time=event_time,
            as_of=event_time.date().isoformat(),
            ingested_at=raw.fetched_at,
            timezone="UTC",
            payload_version=None,
            quality_flags=["fallback_normalized"],
            payload={
                "timeframe": "1Day",
                "open": bar.get("o"),
                "high": bar.get("h"),
                "low": bar.get("l"),
                "close": bar.get("c"),
                "volume": bar.get("v"),
            },
        ))
    return records


def extract_features(records, store):
    features = []
    engines = [MacroRegimeFeature(), EarningsEventFeature(), PriceMomentumFeature()]
    for engine in engines:
        try:
            computed = engine.compute(records)
        except Exception:
            computed = []
        for feat in computed:
            filename = f"feature_{feat.feature_name}_{(feat.symbol or 'macro').lower()}_{feat.computed_at.strftime('%Y%m%d%H%M%S')}.json"
            store.write_features(filename, asdict(feat))
        features.extend(computed)
    return features


def generate_signals(features, store):
    strategy = BreakoutMomentumStrategy()
    signals = strategy.generate(features)
    for sig in signals:
        filename = f"signal_{sig.strategy_id}_{sig.symbol.lower()}_{sig.generated_at.strftime('%Y%m%d%H%M%S')}.json"
        store.write_signals(filename, asdict(sig))
    return signals


def create_decisions(signals, runtime_mode, store):
    engine = DecisionEngine(runtime_mode=runtime_mode)
    decisions = []
    current_positions = {}
    for sig in signals:
        decision = engine.process(sig, current_positions=current_positions)
        filename = f"decision_{decision.symbol}_{decision.generated_at.strftime('%Y%m%d_%H%M%S')}.json"
        store.write_decisions(filename, asdict(decision))
        decisions.append(decision)
    return decisions


def generate_reports(symbols, records, features, signals, decisions):
    report_path = project_root / "data" / "audits" / f"analysis_report_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "stock_swing analysis report",
        f"generated_at={datetime.now().isoformat()}",
        f"symbols={len(symbols)}",
        f"normalized_records={len(records)}",
        f"features={len(features)}",
        f"signals={len(signals)}",
        f"decisions={len(decisions)}",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return str(report_path)


if __name__ == "__main__":
    sys.exit(main())
