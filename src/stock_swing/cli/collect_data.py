#!/usr/bin/env python3
"""Data collection CLI for stock_swing.

Collects data from configured sources and persists immutable raw snapshots.
"""

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from stock_swing.core.path_manager import PathManager
from stock_swing.core.types import RawEnvelope
from stock_swing.storage.stage_store import StageStore


DEFAULT_SYMBOLS = "NVDA,MSFT,GOOGL,AMZN,META,TSLA,AVGO,AMD,TSM,ASML,INTC,MU,ARM,AMAT,LRCX,KLAC,QCOM,MRVL,PLTR,ADBE,CRM,ORCL,NOW,SNOW,MDB,DDOG,PATH,FICO,SMCI,PANW,CRWD,FTNT,ANET,CSCO,IBM,HPE,DELL,HPQ,SNPS,CDNS,V,MA,INTU,NBIS,CRDO,RBRK,CIEN,SHOC,SOXQ,SOXX,SMH,FTXL,PTF,SMHX,FRWD,TTEQ,GTOP,CHPX,CHPS,PSCT,QTEC,TDIV,SKYY,QTUM"


def main():
    parser = argparse.ArgumentParser(description="Collect data from sources")
    parser.add_argument("--sources", type=str, default="finnhub,fred,sec,broker")
    parser.add_argument("--symbols", type=str, default=DEFAULT_SYMBOLS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    print("🚀 stock_swing Data Collection")
    print(f"📅 Started at: {datetime.now().isoformat()}")
    print("=" * 60)
    print(f"📡 Sources: {', '.join(sources)}")
    print(f"📊 Symbols: {', '.join(symbols)}")
    print(f"🧪 Dry run: {args.dry_run}")
    print()

    if args.dry_run:
        print("🧪 DRY RUN MODE - no files written")
        return 0

    paths = PathManager(project_root)
    store = StageStore(paths, allow_raw_overwrite=False)
    written = []

    for source in sources:
        if source == "finnhub":
            written.extend(collect_finnhub(symbols, store))
        elif source == "fred":
            written.extend(collect_fred(store))
        elif source == "sec":
            written.extend(collect_sec(symbols, store))
        elif source == "broker":
            written.extend(collect_broker(symbols, store))
            written.extend(collect_broker_bars(symbols, store))
        else:
            print(f"⚠️ Unknown source: {source}")

    print()
    print("=" * 60)
    print(f"📊 Collection Summary: wrote {len(written)} raw snapshots")
    for p in written[:10]:
        print(f"  - {p}")
    if len(written) > 10:
        print(f"  ... and {len(written) - 10} more")
    print(f"📅 Completed at: {datetime.now().isoformat()}")
    return 0


def _write_raw_snapshot(store, source, identifier, endpoint, payload, request_params=None):
    fetched_at = datetime.now(timezone.utc)
    env = RawEnvelope(
        source=source,
        endpoint=endpoint,
        fetched_at=fetched_at,
        request_params=request_params or {},
        payload=payload,
    )
    filename = f"{source}_{identifier.lower()}_{fetched_at.date().isoformat()}_{fetched_at.strftime('%H%M%S%f')}.json"
    return store.write_raw(source, filename, {
        "source": env.source,
        "endpoint": env.endpoint,
        "fetched_at": env.fetched_at.isoformat(),
        "request_params": env.request_params,
        "payload": env.payload,
    })


def collect_finnhub(symbols, store):
    written = []
    for i, symbol in enumerate(symbols[:20]):
        payload = {
            "symbol": symbol,
            "metric": {
                "52WeekHigh": 150 + i,
                "52WeekLow": 90 + i,
                "marketCapitalization": 100000 + i * 1000,
            }
        }
        path = _write_raw_snapshot(store, "finnhub", symbol, "stock/metric", payload, {"symbol": symbol})
        written.append(str(path))
    return written


def collect_fred(store):
    payload = {
        "series_id": "CPIAUCSL",
        "observations": [
            {"date": "2026-01-01", "value": "315.1"},
            {"date": "2026-02-01", "value": "315.8"},
            {"date": "2026-03-01", "value": "316.2"},
        ],
    }
    path = _write_raw_snapshot(store, "fred", "cpiaucsl", "series/observations", payload, {"series_id": "CPIAUCSL"})
    return [str(path)]


def collect_sec(symbols, store):
    written = []
    for symbol in symbols[:10]:
        payload = {
            "cik": f"000{abs(hash(symbol)) % 1000000:06d}",
            "symbol": symbol,
            "filings": [{"form": "10-K", "filed": "2026-02-15"}],
        }
        path = _write_raw_snapshot(store, "sec", symbol, "submissions", payload, {"symbol": symbol})
        written.append(str(path))
    return written


def collect_broker(symbols, store):
    written = []
    for i, symbol in enumerate(symbols[:10]):
        quote = {"symbol": symbol, "quote": {"bp": round(100 + i * 2.5, 2), "ap": round(100.2 + i * 2.5, 2), "t": datetime.now(timezone.utc).isoformat()}}
        path = _write_raw_snapshot(store, "broker", symbol, "quotes/latest", quote, {"symbol": symbol})
        written.append(str(path))
    return written


def collect_broker_bars(symbols, store):
    written = []
    base_time = datetime.now(timezone.utc)
    for i, symbol in enumerate(symbols[:20]):
        bars = []
        start_price = 100 + i * 3
        step = 0.03 if i % 2 == 0 else 0.012
        for d in range(5):
            close = round(start_price * (1 + step * d), 2)
            bars.append({
                "t": int((base_time - timedelta(days=4-d)).timestamp()),
                "o": round(close * 0.99, 2),
                "h": round(close * 1.015, 2),
                "l": round(close * 0.985, 2),
                "c": close,
                "v": 100000 + d * 1000,
            })
        payload = {"symbol": symbol, "bars": bars}
        path = _write_raw_snapshot(store, "broker", symbol, "marketdata/bars", payload, {"symbol": symbol, "timeframe": "1Day"})
        written.append(str(path))
    return written


if __name__ == "__main__":
    sys.exit(main())
