# ライブ切替手順書（Paper → Live Switch Procedure）

**作成日**: 2026-07-01  
**移行予定日**: 2026-08-01  
**実施者**: システム管理者（オペレーター確認必須）

---

## Go / No-Go チェックリスト

**切替前に全項目を確認。1つでも ❌ があれば切替禁止。**

```
[ ] Guardrail: hard-halt モード有効（paper_warning_only: false）← 2026-07-01 確認済み ✅
[ ] Guardrail: 直近7日間で false positive（誤 halt）ゼロ
[ ] ETF/Stock 別メトリクス: コンソールに表示されている ← R2-B 2026-07-01 ✅
[ ] entry フィルター: 稼働中（volume/ADR/rolling PF gate）← R2-D 2026-07-01 ✅
[ ] 反実仮想検証: R3 完了・exit 戦略の合理性を確認 ← R3-A 完了, R3-B TBD
[ ] attribution completeness (post-R1-B): ≥ 95% ← 100% 確認済み ✅
[ ] Broker/Tracker mismatch: 0 件
[ ] circuit_breaker.json: status=ok（halted でない）
[ ] 緊急停止ランブック: 確認・手順を把握 ← docs/runbooks/emergency_stop.md ✅
[ ] signal strength 飽和: 原因把握済み ← R4-A 2026-07-01 ✅
[ ] Overall PF ≥ 1.20（直近スナップショット）
[ ] Post-R1-B closed trades ≥ 20 件（統計的信頼性）
[ ] リモート監視（R6-F）または代替の監視手段が整っている
[ ] 初期フェーズのサイズ設定を確認（推奨: 08-01〜08-14 は 50% サイズ）
```

---

## 切替手順（当日 08-01）

### Step 1: 前日夜の確認（07-31）

```bash
cd /Users/hirotomookawasaki/stock_swing

# 1. Broker/Tracker 整合確認
python3 scripts/audit_trades_with_market_data.py 2>/dev/null | tail -5

# 2. Circuit breaker 状態確認
python3 -c "
import sys; sys.path.insert(0,'src')
from stock_swing.guardrails.circuit_breaker import CircuitBreakerStore
from pathlib import Path
s = CircuitBreakerStore(Path('data/guardrails/circuit_breaker.json')).load()
print(f'status={s.status}  ← must be ok')
"

# 3. 最新 console summary 確認
python3 -m json.tool reports/console/latest_console_summary.json | grep -A3 '"run"'
```

### Step 2: 切替実施（08-01 朝、市場開場前）

**⚠️ この操作は不可逆ではありません。問題があればすぐ paper に戻せます。**

```bash
# runtime モードを live に変更
cd /Users/hirotomookawasaki/stock_swing
cp config/runtime/current_mode.yaml config/runtime/current_mode.yaml.bak_$(date +%Y%m%d)
```

```yaml
# config/runtime/current_mode.yaml を編集:
# mode: paper  ← この行を変更
mode: live
```

```bash
# 変更確認
cat config/runtime/current_mode.yaml
```

### Step 3: 初期フェーズ設定（08-01〜08-14）

最初の2週間はポジションサイズを 50% に抑える。

```bash
# .env または cron 環境変数に追加:
STOCK_POSITION_SIZE_MULTIPLIER=0.25   # 通常 0.5 × 50% = 0.25
ETF_POSITION_SIZE_MULTIPLIER=0.35     # 通常 0.7 × 50% = 0.35

# 08-15 以降、通常サイズに戻す:
STOCK_POSITION_SIZE_MULTIPLIER=0.5
ETF_POSITION_SIZE_MULTIPLIER=0.7
```

### Step 4: 最初の live run を監視

```bash
# premarket run（ET 04:00 = JST 17:00）のログをリアルタイム監視
tail -f logs/paper_demo_cron_$(date +%Y%m%d)_*.log

# 確認ポイント:
# - "mode: live" が表示されているか
# - Guardrail status=ok か
# - 意図しない注文が出ていないか
# - Broker から実際の約定確認メールが届くか
```

### Step 5: 切替後チェック（初日夜）

```bash
# 当日の約定を確認
python3 scripts/audit_trades_with_market_data.py 2>/dev/null

# Broker ポジションと tracker の一致確認
python3 -c "
import sys, os; sys.path.insert(0,'src')
with open('.env') as f:
    for l in f:
        l=l.strip()
        if l and not l.startswith('#') and '=' in l:
            k,v=l.split('=',1); os.environ[k]=v
from stock_swing.sources.broker_client import BrokerClient
broker = BrokerClient(api_key=***'BROKER_API_KEY'], api_secret=os.environ['BROKER_API_SECRET'], paper_mode=False, base_url=os.environ.get('LIVE_BROKER_BASE_URL',''))
positions = broker.fetch_positions().payload
print(f'Live positions: {len(positions)}')
for p in positions[:5]:
    print(f'  {p[\"symbol\"]}: {p[\"qty\"]} shares  market_value=\${float(p.get(\"market_value\",0)):,.0f}')
"
```

---

## ロールバック手順（live → paper に戻す）

問題が発生したら即座に実行。

```bash
cd /Users/hirotomookawasaki/stock_swing

# 1. runtime を paper に戻す
sed -i 's/^mode: live/mode: paper/' config/runtime/current_mode.yaml
echo "mode: paper" > config/runtime/current_mode.yaml

# 2. circuit breaker を halt に（念のため）
python3 - << 'EOF'
import sys; sys.path.insert(0,'src')
from stock_swing.guardrails.circuit_breaker import CircuitBreakerStore, CircuitBreakerState
from pathlib import Path
from datetime import datetime, timezone
store = CircuitBreakerStore(Path('data/guardrails/circuit_breaker.json'))
store.save(CircuitBreakerState(
    status='halted', action='halt',
    triggered_at=datetime.now(timezone.utc).isoformat(),
    reason='Rollback to paper mode',
))
print("✅ Rolled back to paper mode + halted")
EOF

# 3. ロールバック理由を daily log に記録
echo "## ROLLBACK $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> docs/daily_logs/$(date +%Y-%m-%d).md
echo "- Reason: (記入してください)" >> docs/daily_logs/$(date +%Y-%m-%d).md
```

---

## 重要な注意事項

1. **`paper_mode=True` を `False` に変えることを忘れずに**
   - `broker_client.py` の `paper_mode` パラメータが `True` のままだと、
     `current_mode.yaml` が `live` でも Alpaca paper account に接続し続ける
   - `.env` の `BROKER_BASE_URL` が live エンドポイントを指しているか確認

2. **切替は市場開場前（ET 09:30 より前）に実施すること**
   - 開場中の切替はシステムの動作を不安定にする可能性がある

3. **初日は Telegram 通知を必ずチェック**
   - 意図しない行動があればすぐロールバック

4. **Broker API レート制限**
   - Live 環境は Paper 環境より strict な場合がある
   - 最初の数日はイントラデイ fetch エラーが増える可能性
