# T17: Cron ヘルス監視整備 - 現状分析

## 目的
cron 障害を早く見つけ、運用の安定性を高める

---

## 現状の主要Cronジョブ

### 1. stock_swing_order_reconciliation
- **スケジュール**: `*/15 * * * *` (15分ごと)
- **ターゲット**: `session:agent:main:main`
- **最新ステータス**: `ok`
- **最新実行**: 8分前
- **次回実行**: in 3m

#### 過去10回の実績（2026-04-27確認）
- **成功率**: 100% (10/10)
- **実行時間**: 35.5〜43.9秒（安定）
- **評価**: ✅ 完璧

#### 監視観点
- ✅ 成功率: 100%
- ✅ 実行時間: 安定
- ✅ 配信: not-delivered（想定通り）

---

### 2. daily_report_morning
- **スケジュール**: `0 9 * * 2-6` (平日09:00)
- **ターゲット**: `isolated`
- **最新ステータス**: `ok`
- **最新実行**: 5時間前（2026-04-27 09:00）
- **次回実行**: in 17h（2026-04-28 09:00）

#### 過去17回の実績
- **成功**: 1回（最新の2026-04-27）
- **エラー**: 13回（Telegram `@heartbeat` 解決失敗）
- **タイムアウト**: 2回（984秒、791秒）
- **修正日**: 2026-04-27（chat ID数値化）

#### 監視観点
- ✅ 最新実行: 成功
- ⚠️ 過去実績: 不安定（修正前）
- 🔍 継続監視: 数日間の連続成功確認必要

---

### 3. stock_swing_news_collection
- **スケジュール**: `0 */2 * * *` (2時間ごと)
- **ターゲット**: `session:agent:main:main`
- **最新ステータス**: `ok`
- **最新実行**: 8分前
- **次回実行**: in 2h

#### 監視観点
- ✅ 最新実行: 成功
- 📊 実行頻度: 2時間ごと（適切）

---

### 4. stock_swing_paper_demo_* (4本)

#### 4-1. premarket
- **スケジュール**: `25 23 * * 1-5` (平日23:25)
- **ターゲット**: `isolated`
- **最新ステータス**: `error`
- **最新実行**: 3日前
- **次回実行**: in 7h（本日23:25）

#### 4-2. market_open
- **スケジュール**: `35 23 * * 1-5` (平日23:35)
- **ターゲット**: `isolated`
- **最新ステータス**: `error`
- **最新実行**: 3日前
- **次回実行**: in 7h（本日23:35）

#### 4-3. midday
- **スケジュール**: `0 2 * * 2-6` (平日02:00)
- **ターゲット**: `isolated`
- **最新ステータス**: `error`
- **最新実行**: 3日前
- **次回実行**: in 10h（明日02:00）

#### 4-4. market_close
- **スケジュール**: `55 5 * * 2-6` (平日05:55)
- **ターゲット**: `isolated`
- **最新ステータス**: `error`
- **最新実行**: 2日前
- **次回実行**: in 14h（明日05:55）

#### 過去5回の実績（各ジョブ）
- **成功**: 0/5（すべてタイムアウト）
- **タイムアウト時間**: 1264〜2100秒
- **対策**: 2400秒に延長済み、`--min-momentum 0.05` 追加

#### 監視観点
- ⚠️ **重大**: 5回連続タイムアウト
- 🔧 **対策済み**: タイムアウト延長、負荷軽減
- 🔍 **今夜確認**: 次回実行（23:25〜）で効果確認

---

## 監視観点の定義

### 1. 成功/エラー/タイムアウト
| ジョブ | 成功基準 | 警告基準 | 緊急基準 |
|--------|---------|---------|---------|
| reconciliation | status=ok | 2回連続失敗 | 3回連続失敗 |
| daily_report | status=ok, delivered | 配信失敗 | 2日連続失敗 |
| news_collection | status=ok | 2回連続失敗 | 半日未実行 |
| paper_demo | status=ok | タイムアウト | 3回連続失敗 |

### 2. 実行時間
| ジョブ | 正常範囲 | 警告範囲 | 緊急範囲 |
|--------|---------|---------|---------|
| reconciliation | 30〜50秒 | 50〜90秒 | >90秒 |
| daily_report | 15〜30秒 | 30〜60秒 | >60秒 |
| news_collection | - | - | >300秒 |
| paper_demo | <1800秒 | 1800〜2200秒 | >2400秒|

### 3. 遅延・未実行検知
| ジョブ | 期待実行間隔 | 警告基準 | 緊急基準 |
|--------|------------|---------|---------|
| reconciliation | 15分 | 30分未実行 | 1時間未実行 |
| daily_report | 平日09:00 | 10:00未実行 | 12:00未実行 |
| news_collection | 2時間 | 3時間未実行 | 6時間未実行 |
| paper_demo | 市場時間 | 1日スキップ | 2日連続スキップ |

---

## 日次確認フロー

### 朝の確認（09:00〜09:30）
1. **daily_report_morningの確認**
   - Telegram受信確認
   - status=ok & deliveryStatus=delivered確認
   - レポート内容の妥当性確認

2. **reconciliationの確認**
   - 過去24時間の成功率確認
   - 実行時間の異常値確認
   - mismatches件数確認

3. **paper_demoの確認**
   - 前夜〜早朝の4ジョブ実行結果確認
   - status/durationMs/deliveryStatus確認
   - timeout発生時は詳細ログ確認

### 夕方の確認（17:00〜18:00）
1. **news_collectionの確認**
   - 最新実行確認（2時間以内）
   - データ収集状況確認

2. **全体の健全性確認**
   - `/api/summary/daily` で全体状況確認
   - alerts確認
   - unresolved_mismatches確認

### 確認コマンド例

#### 1. Cron全体のステータス確認
```bash
openclaw cron list
```

#### 2. 個別ジョブの実行履歴確認
```bash
# reconciliation (過去10回)
openclaw cron runs --id 73410e77-5a22-40f5-9b90-d2c6d286434e --limit 10 | python3 -c "
import json, sys
from datetime import datetime

data = json.load(sys.stdin)
print('\nRECONCILIATION - Last 10 Runs')
print('='*60)
success_count = 0
for e in data['entries'][:10]:
    dt = datetime.fromtimestamp(e['ts']/1000).strftime('%Y-%m-%d %H:%M')
    dur = e.get('durationMs', 0) / 1000
    status = e['status']
    if status == 'ok':
        success_count += 1
    print(f'{dt} | {status:8s} | {dur:6.1f}s')
print(f'\nSuccess rate: {success_count}/10 = {success_count*10}%')
"
```

#### 3. Daily Summary確認
```bash
curl -s http://localhost:3333/api/summary/daily | python3 -m json.tool | less
```

#### 4. Paper Demo専用確認スクリプト
```bash
# scripts/check_paper_demo_status.sh
#!/bin/bash

echo "=== PAPER DEMO STATUS CHECK ==="
echo

for job_id in \
  "d4fb64ec-6b22-4985-8945-552f986eec2b" \
  "6eda856d-915a-4605-9428-8d5d13553176" \
  "a2986600-6e6a-4712-afa1-0ac8062e90fd" \
  "fc5f2185-2117-4413-9684-da79ac428869"
do
  openclaw cron runs --id "$job_id" --limit 1 2>&1 | \
  python3 -c "
import json, sys
from datetime import datetime

data = json.load(sys.stdin)
e = data['entries'][0] if data.get('entries') else {}
dt = datetime.fromtimestamp(e.get('ts',0)/1000).strftime('%Y-%m-%d %H:%M')
status = e.get('status', 'unknown')
dur = e.get('durationMs', 0) / 1000
error = e.get('error', 'none')[:50]

print(f'{dt} | {status:8s} | {dur:6.1f}s | {error}')
"
done
```

---

## 次のステップ（T17実装）

### Phase 1: 監視スクリプト作成
1. `scripts/check_cron_health.py` - 全cronの健全性チェック
2. `scripts/check_paper_demo_status.sh` - paper_demo専用チェック
3. 日次確認の自動化

### Phase 2: アラート基準の実装
1. 警告/緊急の閾値設定
2. Slack/Telegram通知の検討
3. 自動リカバリの検討

### Phase 3: ドキュメント整備
1. 日次確認フローの文書化
2. トラブルシューティングガイド
3. エスカレーション基準

---

## 参考情報

### Cron Job IDs
- reconciliation: `73410e77-5a22-40f5-9b90-d2c6d286434e`
- daily_report: `494e46d9-9214-492f-b83c-18a5e59bd5f7`
- news_collection: `0a5ae126-cc03-44af-b4a8-b12b9821bd6f`
- paper_demo_premarket: `d4fb64ec-6b22-4985-8945-552f986eec2b`
- paper_demo_market_open: `6eda856d-915a-4605-9428-8d5d13553176`
- paper_demo_midday: `a2986600-6e6a-4712-afa1-0ac8062e90fd`
- paper_demo_market_close: `fc5f2185-2117-4413-9684-da79ac428869`

### API Endpoints
- Dashboard: `http://localhost:3333/api/dashboard`
- Daily Summary: `http://localhost:3333/api/summary/daily`
- Strategy Analysis: `http://localhost:3333/api/strategy_analysis`
- Exit Reasons: `http://localhost:3333/api/exit_reasons`

---

**作成日**: 2026-04-27  
**次回更新**: T17実装時
