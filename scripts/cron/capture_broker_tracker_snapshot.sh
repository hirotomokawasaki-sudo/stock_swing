#!/usr/bin/env bash
# RGT-011: 同時刻 broker/tracker snapshot 取得スクリプト
# 市場時間中（ET 09:30-16:00）に実行することで、
# broker/tracker の同時刻差分をエクスポートする。
# 用途: RGT-011 (ACCEPTANCE_GATES_20260730.csv) の証跡取得
#
# cron 例（ET 10:00 = JST 23:00 平日）:
#   0 23 * * 1-5 /path/to/capture_broker_tracker_snapshot.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV="$PROJECT_ROOT/venv/bin/python"

if [ ! -x "$VENV" ]; then
    echo "ERROR: venv not found at $VENV"
    exit 1
fi

TIMESTAMP=$(date -u +"%Y%m%d_%H%M%S")
OUT_DIR="$PROJECT_ROOT/data/audits/broker_tracker_snapshots"
mkdir -p "$OUT_DIR"
OUT_FILE="$OUT_DIR/snapshot_${TIMESTAMP}.json"

"$VENV" - << PYEOF
import json, sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, '$PROJECT_ROOT/src')
project_root = Path('$PROJECT_ROOT')

try:
    from stock_swing.brokers.broker_factory import create_broker_client
    from stock_swing.tracking.pnl_tracker import PnLTracker

    broker = create_broker_client(project_root)
    tracker = PnLTracker(project_root)

    pos_env = broker.fetch_positions()
    broker_positions = pos_env.payload if hasattr(pos_env, 'payload') else []

    tracker_trades = tracker.state.trades
    tracker_open = {t['symbol']: t for t in tracker_trades if t.get('status') == 'open'}

    broker_syms = {p.get('symbol') for p in (broker_positions if isinstance(broker_positions, list) else [])}
    tracker_syms = set(tracker_open.keys())

    only_broker = sorted(broker_syms - tracker_syms)
    only_tracker = sorted(tracker_syms - broker_syms)
    mismatch_count = len(only_broker) + len(only_tracker)

    snapshot = {
        'as_of_utc': datetime.now(timezone.utc).isoformat(),
        'mismatch_count': mismatch_count,
        'only_in_broker': only_broker,
        'only_in_tracker': only_tracker,
        'broker_position_count': len(broker_syms),
        'tracker_open_count': len(tracker_syms),
        'common_symbols': sorted(broker_syms & tracker_syms),
        'rgt_011_pass': mismatch_count == 0,
    }

    out_path = Path('$OUT_FILE')
    out_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))
    print(json.dumps({'job': 'broker_tracker_snapshot', 'status': 'ok', 'mismatch_count': mismatch_count, 'output': str(out_path)}))

except Exception as exc:
    print(json.dumps({'job': 'broker_tracker_snapshot', 'status': 'error', 'error': str(exc)}))
    sys.exit(1)
PYEOF
