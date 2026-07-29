#!/usr/bin/env python3
"""Data collection CLI for stock_swing.

Collects data from configured sources and persists immutable raw snapshots.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from stock_swing.core.path_manager import PathManager
from stock_swing.core.types import RawEnvelope
from stock_swing.cli.cron_summary import emit_cron_summary
from stock_swing.utils.market_guard import should_skip_non_market_day
from stock_swing.storage.stage_store import StageStore
from stock_swing.sources.finnhub_client import FinnhubClient
from stock_swing.sources.massive_client import MassiveClient
from stock_swing.sources.retry import RetryConfig


DEFAULT_SYMBOLS = "NVDA,MSFT,GOOGL,AMZN,META,TSLA,AVGO,AMD,TSM,ASML,INTC,MU,ARM,AMAT,LRCX,KLAC,QCOM,MRVL,PLTR,ADBE,CRM,ORCL,NOW,SNOW,MDB,DDOG,PATH,FICO,SMCI,PANW,CRWD,FTNT,ANET,CSCO,IBM,HPE,DELL,HPQ,SNPS,CDNS,V,MA,INTU,NBIS,CRDO,RBRK,CIEN,SHOC,SOXQ,SOXX,SMH,FTXL,PTF,SMHX,FRWD,TTEQ,GTOP,CHPX,CHPS,PSCT,QTEC,TDIV,SKYY,QTUM"


def main():
    parser = argparse.ArgumentParser(description="Collect data from sources")
    parser.add_argument("--sources", type=str, default="finnhub,fred,sec,broker,massive")
    parser.add_argument("--symbols", type=str, default=DEFAULT_SYMBOLS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--days", type=int, default=30, help="Days of historical data to collect (for massive)")
    parser.add_argument("--timeframe", type=str, default="daily", help="Timeframe for bars: daily, 5min, 15min, 1min (for massive)")
    parser.add_argument(
        "--max-runtime-seconds",
        type=int,
        default=int(os.environ.get("COLLECT_DATA_MAX_RUNTIME_SECONDS", "0") or 0),
        help="Best-effort runtime ceiling for finnhub collection (0 disables)",
    )
    parser.add_argument(
        "--fixture-mode",
        action="store_true",
        help="Reserved for non-production fixtures; production path rejects this flag.",
    )
    parser.add_argument("--cron-summary-json", action="store_true", help="Emit one compact CRON_SUMMARY_JSON line at the end")
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
        if args.cron_summary_json:
            emit_cron_summary({
                "job": "collect_data",
                "status": "ok",
                "dry_run": True,
                "sources": sources,
                "symbols_requested": len(symbols),
                "snapshot_count": 0,
            })
        return 0

    if args.fixture_mode:
        print("ERROR: --fixture-mode is not allowed on the production collect_data path", file=sys.stderr)
        return 1

    # R7-v2 / H8: skip on non-market days (weekends / US holidays)
    # Override: export STOCK_SWING_FORCE_MARKET_DAY=true
    _skip, _skip_reason = should_skip_non_market_day()
    if _skip:
        print(f"⏭  {_skip_reason} – skipping collect_data run")
        if args.cron_summary_json:
            emit_cron_summary({"job": "collect_data", "status": "skipped", "reason": _skip_reason})
        return 0

    paths = PathManager(project_root)
    store = StageStore(paths, allow_raw_overwrite=False)
    written = []
    timed_out = False

    # FIX-SOURCE-4: load source classification from config
    _source_configs: dict = {}
    try:
        import yaml as _yaml
        _sources_dir = project_root / "config" / "sources"
        for _sname in ["finnhub", "fred", "sec", "broker", "massive"]:
            _spath = _sources_dir / f"{_sname}.yaml"
            if _spath.exists():
                _source_configs[_sname] = _yaml.safe_load(_spath.read_text()) or {}
    except Exception:
        pass

    def _is_required(src: str) -> bool:
        return bool(_source_configs.get(src, {}).get("required", False))

    def _is_not_implemented(src: str) -> bool:
        return bool(_source_configs.get(src, {}).get("not_implemented", False))

    required_failures: list[str] = []
    degraded_sources: list[str] = []

    for source in sources:
        if source == "finnhub":
            source_written, source_timed_out = collect_finnhub(
                symbols,
                store,
                max_runtime_seconds=args.max_runtime_seconds,
            )
            written.extend(source_written)
            timed_out = timed_out or source_timed_out
            # Finnhub is required; zero snapshots = failure
            if _is_required(source) and not source_written:
                required_failures.append(f"{source}: 0 snapshots written (possible API failure)")
        elif source == "fred":
            if _is_not_implemented(source):
                degraded_sources.append("fred:not_implemented")
            else:
                written.extend(collect_fred(store))
        elif source == "sec":
            if _is_not_implemented(source):
                degraded_sources.append("sec:not_implemented")
            else:
                written.extend(collect_sec(symbols, store))
        elif source == "broker":
            if _is_not_implemented(source):
                degraded_sources.append("broker:not_implemented")
            else:
                written.extend(collect_broker(symbols, store))
                written.extend(collect_broker_bars(symbols, store))
        elif source == "massive":
            written.extend(collect_massive(symbols, store, days=args.days, timeframe=args.timeframe))
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
    if degraded_sources:
        print(f"⚠️  Degraded sources: {degraded_sources}", file=sys.stderr)
    if required_failures:
        for _rf in required_failures:
            print(f"❌ REQUIRED SOURCE FAILURE: {_rf}", file=sys.stderr)

    _overall_status = "ok" if not required_failures else "failed"
    if args.cron_summary_json:
        emit_cron_summary({
            "job": "collect_data",
            "status": _overall_status,
            "dry_run": False,
            "sources": sources,
            "symbols_requested": len(symbols),
            "snapshot_count": len(written),
            "timeframe": args.timeframe,
            "days": args.days,
            "timed_out": timed_out,
            "required_failures": required_failures,
            "degraded_sources": degraded_sources,
        })
    if required_failures:
        return 1  # FIX-SOURCE-4: non-0 exit for required source failures
    return 0


def _write_raw_snapshot(
    store,
    source,
    identifier,
    endpoint,
    payload,
    request_params=None,
    *,
    quality_status="ok",
    is_synthetic=False,
    event_time=None,
    available_at=None,
    revision_id=None,
):
    fetched_at = datetime.now(timezone.utc)
    event_dt = event_time or fetched_at
    available_dt = available_at or fetched_at
    env = RawEnvelope(
        source=source,
        endpoint=endpoint,
        fetched_at=fetched_at,
        request_params=request_params or {},
        payload=payload,
        event_time=event_dt,
        available_at=available_dt,
        ingested_at=fetched_at,
        source_id=hashlib.sha256(f"{source}:{identifier}:{endpoint}".encode("utf-8")).hexdigest()[:16],
        revision_id=revision_id,
        quality_status=quality_status,
        is_synthetic=is_synthetic,
    )
    filename = f"{source}_{identifier.lower()}_{fetched_at.date().isoformat()}_{fetched_at.strftime('%H%M%S%f')}.json"
    return store.write_raw(source, filename, {
        "source": env.source,
        "endpoint": env.endpoint,
        "fetched_at": env.fetched_at.isoformat(),
        "event_time": env.event_time.isoformat() if env.event_time else env.fetched_at.isoformat(),
        "available_at": env.available_at.isoformat() if env.available_at else env.fetched_at.isoformat(),
        "ingested_at": env.ingested_at.isoformat() if env.ingested_at else env.fetched_at.isoformat(),
        "source_id": env.source_id,
        "revision_id": env.revision_id,
        "quality_status": env.quality_status,
        "is_synthetic": env.is_synthetic,
        "request_params": env.request_params,
        "payload": env.payload,
    })


def collect_finnhub(symbols, store, max_runtime_seconds=0):
    written = []
    try:
        from stock_swing.cli.paper_demo import _load_env, project_root as demo_project_root
        _load_env(demo_project_root / '.env')
    except Exception:
        pass
    api_key = os.environ.get('FINNHUB_API_KEY', '')
    client = None
    if api_key:
        try:
            client = FinnhubClient(
                api_key=api_key,
                retry_config=RetryConfig(
                    max_attempts=2,
                    initial_delay=1.0,
                    max_delay=3.0,
                    backoff_factor=2.0,
                    timeout=5.0,
                ),
            )
        except Exception:
            client = None
    today = datetime.now(timezone.utc).date().isoformat()
    from_date = (datetime.now(timezone.utc).date() - timedelta(days=3)).isoformat()
    coverage_status = []
    start_monotonic = time.monotonic()
    timed_out = False

    # Finnhub Basic plan: 60 req/min. With ~2 calls/symbol, 44 symbols = ~88 calls.
    # 0.8s delay keeps us safely under the limit.
    INTER_SYMBOL_DELAY = 0.8

    for i, symbol in enumerate(symbols):
        if max_runtime_seconds and (time.monotonic() - start_monotonic) >= max_runtime_seconds:
            print(
                f"⚠️ Reached max runtime ({max_runtime_seconds}s); stopping Finnhub collection early",
                file=sys.stderr,
            )
            timed_out = True
            break
        if i > 0:
            time.sleep(INTER_SYMBOL_DELAY)
        metric_payload = None
        metric_quality = "missing_client"
        if client:
            try:
                env = client.fetch_basic_financials(symbol=symbol)
                metric_payload = env.payload if env else None
                metric_quality = "ok" if metric_payload else "empty"
            except Exception:
                metric_quality = "failed"
                metric_payload = None
        if metric_payload:
            path = _write_raw_snapshot(
                store,
                "finnhub",
                symbol,
                "stock/metric",
                metric_payload,
                {"symbol": symbol},
                quality_status=metric_quality,
                is_synthetic=False,
            )
            written.append(str(path))

        news_payload = None
        reason = None
        if client:
            try:
                env = client.fetch_company_news(symbol=symbol, from_date=from_date, to_date=today)
                payload = env.payload
                if isinstance(payload, list):
                    news_payload = payload
                elif isinstance(payload, dict) and 'news' in payload:
                    news_payload = payload.get('news')
                else:
                    news_payload = None
                    reason = 'empty_response'
                if news_payload == []:
                    reason = 'no_company_news'
            except Exception as e:
                msg = str(e).lower()
                if '429' in msg or 'rate limit' in msg:
                    reason = 'rate_limit'
                elif '401' in msg or '403' in msg or 'unauthorized' in msg or 'forbidden' in msg:
                    reason = 'auth_error'
                elif 'timeout' in msg:
                    reason = 'timeout'
                else:
                    reason = 'api_error'
                news_payload = None
        else:
            reason = 'missing_client'
        if news_payload:
            news_path = _write_raw_snapshot(
                store,
                "finnhub",
                f"{symbol}_news",
                "company-news",
                {"symbol": symbol, "news": news_payload},
                {"symbol": symbol, "from": from_date, "to": today},
                quality_status="ok",
                is_synthetic=False,
            )
            written.append(str(news_path))
        coverage_status.append({
            'symbol': symbol,
            'news_count': len(news_payload or []),
            'used_fallback': False,
            'reason': reason or 'ok',
            'source': 'finnhub',
            'metric_quality': metric_quality,
            'quality_status': 'ok' if news_payload else (reason or 'no_data'),
            'from': from_date,
            'to': today,
        })

    status_path = project_root / 'data' / 'audits' / 'news_collection_status.json'
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps({
        'time': datetime.now(timezone.utc).isoformat(),
        'timed_out': timed_out,
        'symbols': coverage_status,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    return written, timed_out


def collect_fred(store):
    status_path = project_root / "data" / "audits" / "fred_collection_status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps({
        "time": datetime.now(timezone.utc).isoformat(),
        "status": "not_implemented",
        "note": "FIX-001: fixed FRED payload removed. Real API client required.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return []


def collect_sec(symbols, store):
    status_path = project_root / "data" / "audits" / "sec_collection_status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps({
        "time": datetime.now(timezone.utc).isoformat(),
        "status": "not_implemented",
        "note": "FIX-001: hash-generated CIK removed. Real SEC API required.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return []


def collect_broker(symbols, store):
    status_path = project_root / "data" / "audits" / "broker_quotes_status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps({
        "time": datetime.now(timezone.utc).isoformat(),
        "status": "not_implemented",
        "note": "FIX-001: fixed broker quote payload removed. Broker quotes via reconcile_orders instead.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return []


def collect_broker_bars(symbols, store):
    status_path = project_root / "data" / "audits" / "broker_bars_status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps({
        "time": datetime.now(timezone.utc).isoformat(),
        "status": "not_implemented",
        "note": "FIX-001: fixed broker_bars payload removed. Use massive/finnhub for price data.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return []


def collect_massive(symbols, store, days=30, timeframe="daily"):
    """Collect historical bars from Massive API.
    
    Args:
        symbols: List of stock symbols
        store: StageStore for persisting data
        days: Number of days of historical data
        timeframe: Bar timeframe (daily, 5min, 15min, 1min)
    
    Returns:
        List of written file paths
    """
    written = []
    
    # Load .env for MASSIVE_API_KEY
    try:
        from stock_swing.cli.paper_demo import _load_env, project_root as demo_project_root
        _load_env(demo_project_root / '.env')
    except Exception:
        pass
    
    api_key = os.environ.get('MASSIVE_API_KEY', '')
    if not api_key:
        print("⚠️ MASSIVE_API_KEY not found in environment, skipping massive source")
        return written
    
    try:
        client = MassiveClient(api_key=api_key)
    except Exception as e:
        print(f"⚠️ Failed to initialize MassiveClient: {e}")
        return written
    
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)
    from_str = start_date.strftime("%Y-%m-%d")
    to_str = end_date.strftime("%Y-%m-%d")
    
    print(f"📊 Collecting Massive bars: {from_str} to {to_str} ({timeframe})")
    
    for symbol in symbols:
        try:
            # Fetch bars based on timeframe
            if timeframe == "daily":
                bars = client.fetch_daily_bars(symbol, from_str, to_str)
                endpoint = "aggs/daily"
            elif timeframe in ["1min", "5min", "15min"]:
                multiplier = int(timeframe.replace("min", ""))
                bars = client.fetch_minute_bars(symbol, from_str, to_str, multiplier=multiplier)
                endpoint = f"aggs/{timeframe}"
            else:
                print(f"⚠️ Unknown timeframe {timeframe} for {symbol}, skipping")
                continue
            
            if not bars:
                print(f"⚠️ No bars returned for {symbol}")
                continue
            
            # Convert to standard format
            bars_payload = []
            for bar in bars:
                bars_payload.append({
                    "t": int(bar.timestamp.timestamp()),
                    "o": bar.open,
                    "h": bar.high,
                    "l": bar.low,
                    "c": bar.close,
                    "v": bar.volume,
                    "vw": bar.vwap if bar.vwap else None,
                    "n": bar.transactions if bar.transactions else None,
                })
            
            payload = {"symbol": symbol, "bars": bars_payload, "timeframe": timeframe}
            request_params = {"symbol": symbol, "from": from_str, "to": to_str, "timeframe": timeframe}
            
            path = _write_raw_snapshot(store, "massive", symbol, endpoint, payload, request_params)
            written.append(str(path))
            print(f"✅ {symbol}: {len(bars)} {timeframe} bars")
            
        except Exception as e:
            print(f"❌ Failed to fetch {symbol} from Massive: {e}")
            continue
    
    return written


if __name__ == "__main__":
    sys.exit(main())
