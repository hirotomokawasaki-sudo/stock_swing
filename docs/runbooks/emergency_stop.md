# 緊急停止ランブック（Emergency Stop Runbook）

**対象**: stock_swing ペーパー / リアルトレード  
**最終更新**: 2026-07-01  
**重要度**: 🔴 CRITICAL — リアルトレード中に損失が急拡大した際の対処手順

---

## 判断基準 — いつ緊急停止するか

| 状況 | 対応 |
|---|---|
| Guardrail が自動 halt → Telegram 通知が来た | 手順 A |
| 1日の損失が equity の -3% を超えた | 手順 A |
| システムが誤動作・意図しない注文が出ている | 手順 B（即時） |
| Broker / Tracker の不整合が解消しない | 手順 B → 手順 A |
| ネットワーク障害・サーバー停止 | 手順 C |

---

## 手順 A: Guardrail 手動 halt（ソフト停止）

新規 buy を止める。既存ポジションはそのまま保持。

```bash
# circuit breaker を手動 halt 状態に書き込む
cd /Users/hirotomookawasaki/stock_swing

python3 - << 'EOF'
import sys, json
sys.path.insert(0, 'src')
from stock_swing.guardrails.circuit_breaker import CircuitBreakerStore, CircuitBreakerState
from pathlib import Path
from datetime import datetime, timezone

store = CircuitBreakerStore(Path('data/guardrails/circuit_breaker.json'))
state = CircuitBreakerState(
    status='halted',
    action='halt',
    triggered_at=datetime.now(timezone.utc).isoformat(),
    reason='Manual halt — operator decision',
    triggered_rules=[{'name': 'manual_halt', 'reason': 'operator_triggered'}],
)
store.save(state)
print("✅ Circuit breaker set to HALTED")
print("   次回 paper_demo 起動時から新規 buy が全てブロックされます")
EOF
```

**確認**:
```bash
python3 -c "
import sys; sys.path.insert(0,'src')
from stock_swing.guardrails.circuit_breaker import CircuitBreakerStore
from pathlib import Path
s = CircuitBreakerStore(Path('data/guardrails/circuit_breaker.json')).load()
print(f'status={s.status}  is_halted={s.is_halted}  reason={s.reason}')
"
```

**解除方法**（状況が改善したら）:
```bash
python3 -c "
import sys; sys.path.insert(0,'src')
from stock_swing.guardrails.circuit_breaker import CircuitBreakerStore, CircuitBreakerState
from pathlib import Path
from datetime import datetime, timezone
store = CircuitBreakerStore(Path('data/guardrails/circuit_breaker.json'))
store.save(CircuitBreakerState(status='ok', action='allow', cleared_at=datetime.now(timezone.utc).isoformat(), cleared_by='manual', clear_note='Situation resolved'))
print('✅ Circuit breaker cleared')
"
```

---

## 手順 B: 全 cron ジョブ即時無効化（全自動化停止）

システムが誤動作している場合。paper_demo が起動しないようにする。

```bash
# OpenClaw cron jobs を全て disable
# ブラウザまたは Telegram で以下を実行:
# /cron disable stock_swing_paper_demo_premarket
# /cron disable stock_swing_paper_demo_market_open
# /cron disable stock_swing_paper_demo_midday
# /cron disable stock_swing_paper_demo_market_close

# または CLI から:
openclaw cron list  # job ID を確認
openclaw cron disable <job_id>
```

**確認**: 次の paper_demo スケジュール時刻にログが出ないことを確認。

---

## 手順 C: Broker API 直接操作（全ポジション即時清算）

システムを介さず直接 Broker に指示する。

```bash
# Alpaca Paper Trading ダッシュボード
# https://app.alpaca.markets/paper-trading

# または API から:
cd /Users/hirotomookawasaki/stock_swing
python3 - << 'EOF'
import sys, os
sys.path.insert(0, 'src')
with open('.env') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ[k] = v

from stock_swing.sources.broker_client import BrokerClient
broker = BrokerClient(
    api_key=***'BROKER_API_KEY'],
    api_secret=os.environ['BROKER_API_SECRET'],
    paper_mode=True,
    base_url=os.environ.get('BROKER_BASE_URL', '')
)
# ポジション確認
positions = broker.fetch_positions().payload
print(f"Current positions: {len(positions)}")
for p in positions:
    print(f"  {p['symbol']}: {p['qty']} @ ${p['avg_entry_price']} unrealized=${p.get('unrealized_pl', '?')}")
EOF
```

**⚠️ リアルトレードで全清算する場合は Alpaca ダッシュボードから手動実施を推奨**  
（API による一括清算は `DELETE /v2/positions` で可能だが、スリッページに注意）

---

## 停止後のチェックリスト

```
[ ] circuit_breaker.json の status が "halted" になっていることを確認
[ ] cron jobs が disabled になっていることを確認
[ ] Broker ポジションと tracker が一致していることを確認
[ ] 損失原因を特定・記録
[ ] docs/daily_logs/YYYY-MM-DD.md に経緯を記録
[ ] 再開前に guardrail 閾値とルールをレビュー
[ ] Go/No-Go チェックリスト（docs/runbooks/live_mode_switch.md）を再確認
```

---

## 連絡先 / 監視

- **Telegram bot**: @et_swing_bot
- **Guardrail アラート**: paper_demo 実行時に自動送信
- **ログ確認**: `tail -f logs/paper_demo_cron_*.log`
- **コンソール確認**: `cat reports/console/latest_console_summary.json | python3 -m json.tool`
