# Daily Monitoring Points - 2026-05-21

## 今夜の監視観点（優先順）

### 1. T15: paper_demo cron 完走性確認
- **目的**: 軽量化後の安定性を確認
- **対象ジョブ**: 4つすべて（premarket / market_open / midday / market_close）
- **見るもの**:
  - Status: ok を継続できているか
  - Duration: 10分以内に収まっているか（軽量化効果）
  - Decision / submission count が妥当か
- **前回結果**:
  - ✅ premarket: 221秒（3.7分）- 成功
  - ✅ market_open: 174秒（2.9分）- 成功
  - ✅ midday: 170秒（2.8分）- 成功
  - ✅ market_close: 244秒（4.1分）- 成功
- **期待**: 連続3営業日の成功を確認

### 2. T23: Massive API 運用監視
- **目的**: fresh data 取得の安定性を確認
- **見るもの**:
  - Rate limit 超過の有無
  - Broker fallback の発生有無
  - Price deviation（>5%）のシンボル数
- **前回結果**: `update_price_overrides` で deviation 0 symbols
- **期待**: 連続3営業日で fresh data 取得を確認

### 3. T20: sizing 改善の効き確認
- **目的**: 集中リスク・過大ポジションの抑制を確認
- **見るもの**:
  - ETF exposure が 45% 以下に収まっているか
  - Stock exposure が 55% 以下に収まっているか
  - Sector concentration が 55% 以下に収まっているか
- **期待**: 数営業日で自然なリバランスが進む

## 次回確認タイミング
- **今夜 23:00-23:30**: premarket / market_open の実行結果
- **明日朝 06:00**: daily_audit の実行結果
- **明日朝 09:00**: 4つすべての paper_demo 結果を総合評価

## 健全性確認（本日 11:40）
- ✅ Audit: anomaly 0, integrity issue 0
- ✅ Console health: OK
- ✅ WebSocket: running (pid 55978)
- ✅ Reconciliation: 両方成功（off_hours / market_hours）
- ✅ Paper demo: 4つすべて成功（軽量化後初回）

## 補足対応（優先度低）
- `stock_swing_update_price_overrides`: Telegram delivery 設定修正
- `daily_report_morning`: Agent response エラー調査
