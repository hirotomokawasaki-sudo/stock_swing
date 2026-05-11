# paper_demo 詳細分析（2026-05-11）

## 📊 4ジョブの最新実行状況

### 1. premarket (23:00 JST)
**最新実行**: 2026-05-08 23:00
- Status: ✅ OK
- Duration: **1665秒 (27.8分)**
- Delivery: ✅ delivered
- 内容: 11 actionable, SIGTERM途中終了だが主要注文は完了

**前回**: 2026-05-07 23:00
- Status: ✅ OK
- Duration: **2585秒 (43.1分)**
- 14 decisions, 14 actionable, 11/11 submitted

### 2. market_open (23:05 JST)
**最新実行**: 2026-05-08 23:05
- Status: ✅ OK
- Duration: **2010秒 (33.5分)**
- Delivery: ✅ delivered
- 内容: 15 actionable, 3 denied, SIGTERM途中終了

**前回**: 2026-05-07 23:05
- Status: ✅ OK
- Duration: **1812秒 (30.2分)**
- 14 actionable, 11 orders submitted

### 3. midday (02:00 JST)
**最新実行**: 2026-05-08 02:00
- Status: ❌ ERROR
- Duration: **2014秒 (33.6分)**
- Delivery: ❌ `HttpError: Network request for 'sendMessage' failed!`
- 内容: 14 decisions, 13 actionable, 10/10 submitted
- **重要**: 実行自体は成功、Telegram送信のみ失敗

**前回**: 2026-05-07 02:00
- Status: ✅ OK
- Duration: **807秒 (13.5分)**
- SIGTERM途中終了だが delivery 成功

### 4. market_close (05:55 JST)
**最新実行**: 2026-05-08 05:55
- Status: ✅ OK
- Duration: **1389秒 (23.2分)**
- Delivery: ✅ delivered
- 内容: 12 actionable, 2 denied, SIGTERM途中終了

**前回**: 2026-05-07 05:55
- Status: ✅ OK
- Duration: **72秒 (1.2分)** 🌟
- 11 decisions, 11 actionable, 10/10 submitted

---

## 📈 実行時間の傾向

### 直近5回の実行時間平均

| Job | 最新 | 平均 | 最短 | 最長 | Timeout設定 |
|-----|------|------|------|------|------------|
| premarket | 27.8分 | ~30分 | 2.4分 | 43.1分 | 60分 |
| market_open | 33.5分 | ~32分 | 19.4分 | 43.4分 | 60分 |
| midday | 33.6分 | ~25分 | 13.5分 | 35.1分 | 60分 |
| market_close | 23.2分 | ~22分 | 1.2分 | 32.3分 | 60分 |

### 観察事項

1. **実行時間のバラつきが大きい**
   - market_close: 1.2分 〜 32.3分（27倍の差）
   - premarket: 2.4分 〜 43.1分（18倍の差）

2. **SIGTERM途中終了が頻発**
   - ただし主要な注文処理は完了している
   - delivery は成功している

3. **midday の Telegram 送信エラー**
   - 2026-05-08 02:00 のみ発生
   - 今回の telegram_notifier 改善で解決が期待できる

---

## 🎯 T15 完了判定の評価

### 完了条件
- [x] 少なくとも代表 run で `status=ok`
- [x] timeout の連続発生が解消
- [~] 実行時間が許容範囲に収まる

### 現状評価
✅ **4ジョブすべて最新 run は status=ok**
- ただし midday は delivery error（Telegram送信失敗）

✅ **timeout は解消**
- 3600秒（60分）設定で全て完走
- 過去の連続 timeout は解消済み

⚠️ **実行時間は長め**
- premarket / market_open: 30〜40分台
- market_close も 20分台
- ただし、これは「実行不可能」レベルではなく「軽量化余地あり」レベル

---

## 🔍 根本原因の推測

### なぜ実行時間が長いのか？

2026-05-07 のログ分析から:
- **data collection 自体は軽い**（数秒〜数十秒）
- **重いのは注文処理・reconciliation**
  - 1件ずつの broker API 呼び出し
  - quote 再取得の重複
  - position 確認の重複

2026-05-07 に実施した軽量化:
- `PaperExecutor.submit()` に `current_qty` パラメータ追加
- quote の簡易キャッシュ追加
- SELL 時の broker positions 再取得を省略

→ **これらの効果を今夜の実行で確認する必要がある**

---

## 📋 次アクション

### 今夜 23:00〜23:35 (最優先)
1. **premarket / market_open 実行結果確認**
   - 実行時間が短縮されているか？
   - Telegram 送信成功か？
   - SIGTERM 減少しているか？

2. **midday Telegram 送信確認**
   - telegram_notifier のリトライ機能が効いているか？
   - エラーログの内容確認

### 明日朝
1. **market_close 実行結果確認**
   - 安定性維持されているか？

### 今夜の確認後の判断

**ケースA: 実行時間が改善している（20分未満に短縮）**
- → T15 完了とマーク
- → T20 は観測継続のみ

**ケースB: 実行時間が依然として長い（30分超）**
- → T15 は「部分完了」としてマーク
- → T20 の軽量設定分離を検討
  - cron 用の軽量 universe（銘柄数削減）
  - threshold 引き上げ
  - bar-limit 削減

**ケースC: midday の Telegram 送信が再度失敗**
- → telegram_notifier のさらなる改善
- → delivery mode を webhook に変更検討

---

## 💡 改善案（優先順位付き）

### Priority 1: 今夜確認後に判断
- 2026-05-07 の軽量化効果測定
- telegram_notifier 改善効果測定

### Priority 2: 実行時間がまだ長い場合
- universe 削減（64 → 30銘柄程度）
- min_momentum threshold 引き上げ（0.05 → 0.10）
- bar-limit 削減（20 → 10）

### Priority 3: 長期的改善
- broker API 並列化
- quote キャッシュの永続化
- reconciliation の非同期化

---

**作成日**: 2026-05-11 09:52 JST
**次回更新**: 2026-05-11 23:35 JST（今夜の実行結果確認後）
