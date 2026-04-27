# stock_swing 完了済み機能の運用確認チェックリスト

## 目的
完了済みの console / tracker / cron 改善項目について、実装完了だけでなく実運用上も正常に機能しているかを確認する。

---

## 1. reconciliation / broker truth

### 1-1. reconciliation 定期実行
- [ ] `stock_swing_order_reconciliation` が 15分ごとに実行されている
- [ ] 最新 run が `status=ok` である
- [ ] 連続 timeout / error が発生していない

### 1-2. closed trades 後追い同期
- [ ] sell 注文後に `reconcile_orders.py` によって closed trades が更新される
- [ ] PnL tracker の open → closed 反映が整合している
- [ ] filled exit の二重計上が起きていない

### 1-3. pending order / mismatch 表示
- [ ] pending order が broker truth ベースで表示される
- [ ] `accepted / filled / canceled / rejected` の表示が broker 実態と一致する
- [ ] unresolved mismatch 件数が summary / dashboard と整合する

---

## 2. PnL / positions / risk 表示

### 2-1. unrealized PnL
- [ ] `current_price` が取得できる銘柄で unrealized PnL が計算される
- [ ] overview / positions / symbol overview の値が整合する
- [ ] gross exposure が保有ポジション合計と一致する

### 2-2. holding days / stale positions
- [ ] open positions に `holding_days` が表示される
- [ ] stale positions が daily summary に反映される
- [ ] 長期保有ポジションが alert に反映される

### 2-3. strategy / symbol 指標
- [ ] strategy overview に submissions / closes / realized pnl / open positions / rejection rate が表示される
- [ ] symbol detail で latest decisions / submissions / reconciliations / trades が確認できる

---

## 3. daily / weekly summary

### 3-1. daily summary API
- [x] `GET /api/summary/daily` が成功する
- [x] `pnl_summary` が返る
- [x] `alerts` が返る
- [x] `unresolved_mismatches` が返る
- [x] `stale_positions` が返る
- [x] `low_conversion_symbols` が返る
- [x] `strategy_health` が返る

### 3-2. weekly summary API
- [ ] `GET /api/summary/weekly` が成功する
- [ ] weekly PnL / win rate / strategy breakdown / top symbols が返る

### 3-3. top alerts 妥当性
- [x] top alerts が severity 順で上位件数に整理されている
- [x] `large_daily_loss` / `unresolved_mismatches` / `stale_positions` / `strategy_health_attention` などが条件時に出る
- [ ] 実態に対して誤警報が多すぎない

---

## 4. daily report / Telegram

### 4-1. daily_report_morning
- [ ] `daily_report_morning` が定期実行される
- [ ] `status=ok` / `deliveryStatus=delivered` を維持している
- [ ] Telegram に日次レポートが配信される

### 4-2. daily report 本文
- [ ] Equity / P&L / 取引数 / 勝率 / 最大DD が正しく出る
- [ ] `data/audits/daily_report_YYYY-MM-DD.txt` に保存される
- [ ] 直近取引 / 保有ポジション / サイズ根拠の表示が破綻していない

---

## 5. paper_demo / cron

### 5-1. paper_demo 定期実行
- [ ] `stock_swing_paper_demo_*` の次回 run が起動する
- [ ] timeout 延長後に `durationMs` が許容内に収まる
- [ ] `status=ok` で完走する run が確認できる

### 5-2. paper_demo 出力整合
- [ ] 指定した symbol universe が実行ログに反映される
- [ ] Data Collection → Feature → Signals → Decisions → Submission/Reconciliation の流れが破綻していない
- [ ] ログに必要な summary が残る

### 5-3. paper_demo 運用負荷
- [ ] `--min-momentum 0.05` 調整後に過剰な signal 数になっていない
- [ ] cron 実行が Telegram / delivery を含めても安定している

---

## 6. parameter tuning support

### 6-1. parameter API
- [ ] parameter 一覧取得ができる
- [ ] validation API が正常応答する
- [ ] apply API が confirmation 付きで動く
- [ ] rollback が可能
- [ ] change log が残る

---

## 7. 最終確認
- [ ] UI 表示と API 応答が概ね整合する
- [ ] broker truth / tracker / summary / cron の数値矛盾がない
- [ ] 運用上の重複ジョブや古い失敗ジョブが残っていない
- [ ] 次に追加するタスクが「新規改善」なのか「運用安定化」なのか区別できている
