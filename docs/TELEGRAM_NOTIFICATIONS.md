# Telegram通知システム

stock_swingのTelegram自動通知機能に関するドキュメントです。

## 📱 概要

システムは以下のタイミングで自動的にTelegramに通知を送信します：

### 1. 定期レポート（正常時）
- **夜 22:30（月〜金）**: Paper Demo実行結果
- **朝 9:00（火〜土）**: Daily Performance Report

### 2. エラー発生時（即座に通知）
- Paper Demo実行失敗
- Daily Report生成失敗
- タイムアウト
- API接続エラー
- キルスイッチ発動

---

## 🌙 夜の通知（22:30）

### 正常時
```
📊 ペーパー取引 - Stock Swing
🗓 2026-04-06 22:30 JST

📈 分析結果
銘柄数        : 10
判断数        : 3
  実行可能    : 2
  拒否        : 1
  保留        : 0

📝 注文
送信済み      : 2/2
  買い   15株 NVDA
  買い   10株 CRM

💰 口座
資産総額      : $102,450.00

⚠️ 1件のシグナルを拒否
```

### エラー時
```
🚨 Paper Demo エラー
🗓 2026-04-06 22:30 JST

エラー種別:
ブローカーAPI エラー

エラー内容:
Failed to connect to broker API: Connection timeout

対応:
• ログを確認してください
• 必要に応じて手動で実行
• システム管理者に連絡
```

---

## 🌅 朝の通知（9:00）

### 正常時
```
📈 stock_swing 日次レポート
🗓 2026-04-06  |  モード: paper

💰 口座情報 (ペーパー)
ステータス    : ACTIVE
資産総額      : $102,450.00
買付余力      : $198,320.00
累積損益      : $+2,450.00

📊 パフォーマンス (運用開始以降)
決済取引数    : 5
勝 / 負       : 3 / 2
勝率          : 60.0% 🔥
平均リターン  : +2.3%
平均損益/取引 : $+490.00
最大DD        : 1.2%
取引日数      : 7

📂 保有ポジション (2件)
  NVDA   15株  取得=$875.20
  現在=$892.50  含損益=+2.0% ($+259)

🔄 最近の決済取引 (直近3件)
  ✅ AAPL   買い  損益: $+850.00 (+4.5%)
  ✅ MSFT   買い  損益: $+320.00 (+1.8%)
  ❌ TSLA   買い  損益: $-180.00 (-2.1%)

次回実行: 日本時間 22:30
```

### エラー時
```
🚨 Daily Report エラー
🗓 2026-04-06 09:00 JST

エラー内容:
KeyError: 'BROKER_API_KEY'

トレースバック:
File "daily_report.py", line 65
  api_key=os.environ["BROKER_API_KEY"]
...

対応:
• ログを確認
• ブローカーAPI接続を確認
• 手動で再実行
```

---

## ⏱️ タイムアウト通知

実行が15分（900秒）を超えた場合：

```
⏱️ Paper Demo タイムアウト
🗓 2026-04-06 22:30 JST

実行時間:
900秒で停止

考えられる原因:
• API応答の遅延
• ネットワーク問題
• データ取得の失敗

対応:
• 手動で再実行を試みる
• API接続を確認
• ログファイルを確認
```

---

## 🔧 エラーの種類と対応

### 1. ブローカーAPI エラー
**原因:**
- Alpaca APIのダウン
- 認証情報の問題
- レート制限

**対応:**
1. Alpacaのステータスページを確認
2. `.env`のAPI_KEYとAPI_SECRETを確認
3. 手動で再実行: `python -m stock_swing.cli.paper_demo_wrapper`

### 2. キルスイッチ発動
**原因:**
- 手動でキルスイッチが無効化された
- 緊急停止が作動

**対応:**
1. キルスイッチの状態を確認: `cat data/audits/kill_switch.txt`
2. 安全であれば再有効化
3. 手動実行

### 3. タイムアウト
**原因:**
- データ取得の遅延
- APIレスポンスの遅延
- ネットワーク問題

**対応:**
1. インターネット接続を確認
2. 時間をおいて再実行
3. `--symbols`オプションで銘柄数を減らして実行

### 4. マーケット関連エラー
**原因:**
- 市場休場日
- 取引時間外

**対応:**
- 通常は自動的に処理されるため対応不要
- `--allow-outside-hours`オプションで強制実行可能

---

## 🛠️ 手動実行方法

### Paper Demo（エラー時の再実行）
```bash
cd ~/stock_swing
source venv/bin/activate
python -m stock_swing.cli.paper_demo_wrapper
```

### Daily Report（エラー時の再実行）
```bash
cd ~/stock_swing
source venv/bin/activate
python -m stock_swing.cli.daily_report --telegram
```

### テスト実行（通知なし）
```bash
# Dry-run（注文送信なし）
python -m stock_swing.cli.paper_demo --dry-run

# Daily Report（Telegram送信なし）
python -m stock_swing.cli.daily_report
```

---

## 📊 通知の種類まとめ

| 通知種類 | タイミング | 絵文字 | 優先度 |
|---------|-----------|-------|--------|
| Paper Demo成功 | 22:30（月〜金） | 📊 | 通常 |
| Daily Report | 9:00（火〜土） | 📈 | 通常 |
| エラー | 即座 | 🚨 | 高 |
| タイムアウト | 即座 | ⏱️ | 高 |
| 警告（高DD/低勝率） | 9:00 | ⚠️ | 中 |

---

## 🔐 セキュリティ

### Telegram設定ファイル
`.env`ファイルには以下が含まれます：
```bash
TELEGRAM_BOT_TOKEN=<YOUR_BOT_TOKEN>
TELEGRAM_CHAT_ID=<YOUR_CHAT_ID>
```

**注意:**
- このファイルは`.gitignore`に含まれています
- 絶対に公開リポジトリにコミットしないでください
- トークンが漏洩した場合は即座にBotFatherで再生成してください

---

## 📝 ログとトラブルシューティング

### ログの確認
```bash
# 最新のPaper Demoログ
ls -lt ~/stock_swing/logs/paper_demo_*.log | head -1

# ログ内容の表示
tail -100 ~/stock_swing/logs/paper_demo_*.log
```

### よくある問題

#### Q: 通知が届かない
**A:** 
1. Telegram設定を確認: `.env`にTOKENとCHAT_IDがあるか
2. 手動テスト: `python -c "from stock_swing.utils.telegram_notifier import send_notification; send_notification('test')"`
3. Botがブロックされていないか確認

#### Q: エラー通知が多すぎる
**A:**
1. 根本原因を解決（API接続、設定ミス等）
2. 一時的に無効化: Cronジョブを`enabled: false`に設定

#### Q: 通知の内容を変更したい
**A:**
- Paper Demo: `src/stock_swing/cli/paper_demo.py`の`_send_telegram_summary()`
- Daily Report: `src/stock_swing/cli/daily_report.py`の`_build_report()`
- エラー通知: `src/stock_swing/cli/paper_demo_wrapper.py`

---

## 📅 スケジュール詳細

### Cronジョブ設定

#### Paper Demo（夜）
- **ID**: `b75acb2d-5e94-483a-912e-67f78b00e9e9`
- **スケジュール**: `30 22 * * 1-5` (月〜金 22:30 JST)
- **タイムアウト**: 900秒（15分）
- **実行コマンド**: `python -m stock_swing.cli.paper_demo_wrapper`

#### Daily Report（朝）
- **ID**: `494e46d9-9214-492f-b83c-18a5e59bd5f7`
- **スケジュール**: `0 9 * * 2-6` (火〜土 9:00 JST)
- **タイムアウト**: 300秒（5分）
- **実行コマンド**: `python -m stock_swing.cli.daily_report --telegram`

---

## 🔄 更新履歴

- **2026-04-06**: 初版作成
  - Telegram通知機能実装
  - エラー通知自動化
  - 日本語化完了
  - 朝のレポート時刻を9:00に変更

---

**最終更新**: 2026-04-06
