# Cron Daily Check - 日次確認フロー

## 目的
cron ジョブの健全性を毎日確認し、問題を早期発見する

---

## 朝の確認（09:00〜09:30）

### 1. daily_report_morning の確認
```bash
cd ~/stock_swing
python3 scripts/check_cron_health.py --only daily_report_morning
```

**確認ポイント**:
- ✅ status: ok
- ✅ deliveryStatus: delivered
- ✅ duration: 30秒以内
- ✅ Telegram で受信確認

**異常時の対応**:
```bash
# エラー詳細確認
openclaw cron runs --id 494e46d9-9214-492f-b83c-18a5e59bd5f7 --limit 3

# 必要なら手動実行
cd ~/stock_swing && source venv/bin/activate
python -m stock_swing.cli.daily_report --telegram --save
```

---

### 2. reconciliation の確認
```bash
python3 scripts/check_cron_health.py --only reconciliation
```

**確認ポイント**:
- ✅ status: ok
- ✅ duration: 30-50秒
- ✅ consecutive_failures: 0

**異常時の対応**:
```bash
# 手動実行
python -m stock_swing.cli.reconcile_orders
```

---

### 3. paper_demo（前夜〜早朝分）の確認
```bash
./scripts/check_paper_demo_status.sh
```

**確認ポイント**:
- premarket (23:25): status=ok, duration < 30秒
- market_open (23:35): status=ok, duration < 30秒
- midday (02:00): status=ok, duration < 30秒
- market_close (05:55): status=ok, duration < 30秒

**異常時の対応**:
```bash
# 詳細確認
openclaw cron runs --id d4fb64ec-6b22-4985-8945-552f986eec2b --limit 3

# ログ確認
tail -100 logs/paper_demo_cron_$(date +%Y%m%d)*.log
```

---

## 夕方の確認（17:00〜18:00）

### 1. news_collection の確認
```bash
python3 scripts/check_cron_health.py --only news_collection
```

**確認ポイント**:
- ✅ 最新実行: 2時間以内
- ✅ status: ok

---

### 2. 全体の健全性確認
```bash
python3 scripts/check_cron_health.py
```

**確認ポイント**:
- overall: ✅ ok または ⚠️ warn まで
- 🚨 critical がないこと

---

### 3. Daily Summary API 確認
```bash
curl -s http://localhost:3335/api/summary/daily | python3 -m json.tool | less
```

**確認ポイント**:
- alerts: 重大なアラートがないか
- unresolved_mismatches: 0件
- strategy_health: conversion_rate が許容範囲

---

## 週次確認（月曜朝）

### 1. 週次サマリー確認
```bash
curl -s "http://localhost:3335/api/summary/weekly?weeks=1" | python3 -m json.tool
```

### 2. cron 成功率の確認
```bash
# 各ジョブの過去7日間の成功率
for job in reconciliation daily_report_morning news_collection; do
  echo "=== $job ==="
  python3 scripts/check_cron_health.py --only $job --limit 50
done
```

### 3. paper_demo の実行時間トレンド
```bash
# 過去1週間の実行時間を確認
openclaw cron runs --id d4fb64ec-6b22-4985-8945-552f986eec2b --limit 30 | \
python3 -c "
import json, sys
from datetime import datetime

data = json.load(sys.stdin)
print('Date       Time     Status   Duration')
print('=' * 50)
for e in data['entries']:
    dt = datetime.fromtimestamp(e['ts']/1000).strftime('%Y-%m-%d %H:%M')
    status = e.get('status', 'unknown')
    dur = f\"{e.get('durationMs', 0)/1000:.1f}s\"
    print(f'{dt}  {status:8s}  {dur}')
"
```

---

## アラート基準

### Critical（即座に対応）
- paper_demo: 3回連続 timeout
- reconciliation: 3回連続失敗
- daily_report: 2日連続失敗

### Warning（当日中に対応）
- paper_demo: 1回 timeout
- reconciliation: 2回連続失敗
- news_collection: 6時間未実行

### Info（様子見）
- duration が通常より長い
- 1回だけの失敗

---

## エスカレーション

### Level 1: 自己復旧
- watchdog による自動再起動
- 次回 cron で自動復帰

### Level 2: 手動介入
- 手動実行
- ログ確認
- 設定調整

### Level 3: 根本対策
- コード修正
- infrastructure 変更
- 戦略調整

---

## 関連ドキュメント
- `docs/t17_cron_health_analysis.md` - 監視観点の詳細
- `scripts/check_cron_health.py` - ヘルスチェックスクリプト
- `scripts/check_paper_demo_status.sh` - paper_demo 専用チェック
- `ops/watchdog/README.md` - watchdog の使い方
