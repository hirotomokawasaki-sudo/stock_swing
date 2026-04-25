# stock_swing Console Improvement Tasks

## Today First
- [x] T1. reconciliation を scheduler 実体に正式登録
- [x] T2. pending order を broker truth ベース表示へ変更
- [x] T3. sell/exit 回帰テスト追加
- [x] T4. unrealized pnl の実値化

---

## Week 1 — 信頼できる運用数値を固める

### T1. reconciliation を scheduler 実体に正式登録
**目的**: accepted→filled の後追い同期を自動化する

**作業**
- [x] scheduler 実体に `stock_swing_order_reconciliation` を登録
- [x] 15分ごと実行設定
- [x] 実行結果 announce/log を確認

**完了条件**
- [x] 自動で `reconcile_orders.py` が定期実行される
- [x] closed trades が後追い同期で更新される

**ログテンプレート**
- 実施日:
- 実施内容:
- 確認結果:
- 次アクション:

### T2. pending order を broker truth ベース表示へ変更
**目的**: UI表示と broker 実態を一致させる

**作業**
- [x] broker API から order status を直接取得
- [x] UIで `accepted / filled / canceled / rejected` 表示
- [x] audit 依存の暫定判定を縮小

**完了条件**
- [x] pending/mismatch 表示が broker truth と一致

**ログテンプレート**
- 実施日:
- 実施内容:
- 確認結果:
- 次アクション:

### T3. sell/exit 回帰テスト追加
**目的**: close反映まわりの再発防止

**作業**
- [x] sell sizing override テスト
- [x] reconciliation → record_exit テスト
- [x] no position to sell テスト
- [x] partial fill 予備テスト

**完了条件**
- [x] exit flow の主要ケースに自動テストあり

**ログテンプレート**
- 実施日:
- 実施内容:
- 確認結果:
- 次アクション:

### T4. unrealized pnl の実値化
**目的**: risk判断を実データベースにする

**作業**
- [x] current price 安全取得実装
- [x] position.current_price / market_value / unrealized_pnl 計算
- [x] overview / positions / symbol overview へ反映

**完了条件**
- [x] gross exposure / unrealized pnl が実値表示

**ログテンプレート**
- 実施日:
- 実施内容:
- 確認結果:
- 次アクション:

---

## Week 2 — execution と PnL の精度を上げる

### T5. partial fill 対応
- [ ] partial fill を tracker に反映
- [ ] 数量ベースで open / close を整合

### T6. mismatch reason を構造化
- [ ] accepted_not_filled
- [ ] filled_pending_sync
- [ ] status_mismatch
- [ ] qty_mismatch
- [ ] order_not_found

### T7. low conversion symbol / strategy の改善分析
- [ ] symbol別 conversion 分析
- [ ] strategy別 conversion 分析
- [ ] risk gate / size cap / sector cap の候補抽出

### T8. strategy overview 拡張
- [ ] submissions
- [ ] closes
- [ ] realized pnl
- [ ] open positions
- [ ] rejection rate

---

## Month 1 — 運用コンソールとして完成度を上げる

### T9. UI ソート・フィルタ・検索
- [ ] symbol overview
- [ ] pending/mismatch orders
- [ ] execution by symbol
- [ ] positions
- [ ] reconciliation by symbol

### T10. drilldown 実装
- [ ] symbol detail
- [ ] latest decisions
- [ ] submissions
- [ ] reconciliations
- [ ] open/closed trades
- [ ] reject reasons

### T11. 日次/週次サマリー自動生成
- [ ] top alerts
- [ ] pnl summary
- [ ] unresolved mismatches
- [ ] stale positions
- [ ] low conversion symbols
- [ ] strategy health

### T12. parameter tuning support
- [ ] max_position_size
- [ ] risk budget
- [ ] sector exposure cap
- [ ] signal threshold
- [ ] stop logic
