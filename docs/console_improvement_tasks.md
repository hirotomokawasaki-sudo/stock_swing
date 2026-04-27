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
- [x] partial fill を tracker に反映
- [x] 数量ベースで open / close を整合

### T6. mismatch reason を構造化
- [x] accepted_not_filled
- [x] filled_pending_sync
- [x] status_mismatch
- [x] qty_mismatch
- [x] order_not_found

### T7. low conversion symbol / strategy の改善分析
- [x] symbol別 conversion 分析
- [x] strategy別 conversion 分析
- [x] risk gate / size cap / sector cap の候補抽出

### T8. strategy overview 拡張
- [x] submissions
- [x] closes
- [x] realized pnl
- [x] open positions
- [x] rejection rate

---

## Month 1 — 運用コンソールとして完成度を上げる

### T9. UI ソート・フィルタ・検索
- [x] API query parameters (sort, order, filter)
- [x] positions sorting (market_value, symbol, unrealized_pnl)
- [x] positions filtering (by symbol)
- [x] dashboard/symbol_overview sorting
- [x] dashboard/symbol_overview filtering

### T10. drilldown 実装
- [x] symbol detail API (/api/symbol/<symbol>)
- [x] latest decisions (up to 20)
- [x] submissions history
- [x] reconciliations (via audit logs)
- [x] open/closed trades (from PnL tracker)
- [x] current position details

### T11. 日次/週次サマリー自動生成
- [x] daily summary API (/api/summary/daily)
- [x] pnl summary (today + cumulative)
- [x] trade count (today + total)
- [x] top alerts
- [x] unresolved mismatches
- [x] stale positions
- [x] low conversion symbols
- [x] strategy health

### T12. parameter tuning support
- [x] max_position_size
- [x] min_signal_strength
- [x] min_confidence
- [x] symbol_position_limit_pct
- [x] validation API
- [x] apply API with confirmation
- [x] rollback capability
- [x] change logging

---

## Phase 2 — 運用確認と安定化

### Week 3 — 運用確認を固める

### T13. daily summary / alerts 運用品質確認
**目的**: summary API が実運用で使える品質か確認する

**作業**
- [ ] `/api/summary/daily` の返却内容を連日確認
- [ ] `pnl_summary` / `alerts` / `unresolved_mismatches` / `stale_positions` / `strategy_health` の妥当性確認
- [ ] 誤警報 / 欠落警報の記録

**完了条件**
- [ ] 主要 summary 項目が安定して返る
- [ ] top alerts の誤警報が許容範囲
- [ ] 運用上必要な alert が拾えている

### T14. daily_report_morning 継続安定確認
**目的**: 日次レポート配信を正規運用として安定化する

**作業**
- [ ] 連日 `status=ok` / `deliveryStatus=delivered` を確認
- [ ] 保存ファイル出力確認
- [ ] Telegram 本文の品質確認

**完了条件**
- [ ] 数日連続で日次レポート成功
- [ ] 配信 / 保存 / 要約内容に破綻なし

### T15. paper_demo cron 完走性確認
**目的**: paper_demo の cron が timeout せず完走できるようにする

**作業**
- [ ] 4本の `stock_swing_paper_demo_*` 実行結果監視
- [ ] `status` / `durationMs` / `deliveryStatus` 確認
- [ ] timeout 再発時は wrapper / universe / bar-limit を追加調整

**完了条件**
- [ ] 少なくとも代表 run で `status=ok`
- [ ] timeout の連続発生が解消
- [ ] 実行時間が許容範囲に収まる

### T16. reconciliation / broker truth 運用整合確認
**目的**: tracker・broker・UI の整合を運用ベースで確認する

**作業**
- [ ] pending / mismatch / filled の整合確認
- [ ] closed trade の後追い反映確認
- [ ] mismatch reason の実データ確認

**完了条件**
- [ ] broker truth と UI 表示が継続一致
- [ ] closed trade の同期漏れがない
- [ ] unresolved mismatch が説明可能

### Month 2 — 安定運用と観測性を高める

### T17. cron ヘルス監視整備
**目的**: cron 障害を早く見つける

**作業**
- [ ] 主要ジョブの success/error/timeout 監視観点を定義
- [ ] 遅延・連続失敗・未実行を検知する基準作成
- [ ] 日次確認フローを明文化

**完了条件**
- [ ] 主要 cron の健全性確認手順が定義済み
- [ ] timeout / 失敗の見逃しが減る

### T18. operational verification checklist の継続運用
**目的**: 完了済み機能の劣化を防ぐ

**作業**
- [ ] `operational_verification_checklist.md` を週次/随時更新
- [ ] 確認済み項目と未確認項目を管理
- [ ] 実害のあった項目を優先監視に昇格

**完了条件**
- [ ] checklist が形骸化せず使われている
- [ ] 確認結果が daily log に反映される

### T19. summary / alert の観測性改善
**目的**: summary が「返る」だけでなく「役立つ」状態にする

**作業**
- [ ] alert の妥当性見直し
- [ ] noisy alert / missing alert の改善
- [ ] 必要なら UI への表示追加

**完了条件**
- [ ] top alerts が運用判断に使える
- [ ] 誤警報が抑えられている
- [ ] summary の主要情報が見やすい

### T20. paper_demo 運用モード最適化
**目的**: paper_demo を継続運用可能な負荷へ調整する

**作業**
- [ ] 実行時間・signal 数・submission 数を観測
- [ ] cron 用の軽量設定を必要に応じて分離
- [ ] universe / threshold / bar-limit の再調整

**完了条件**
- [ ] paper_demo が安定して回る
- [ ] 負荷と出力品質のバランスが取れている

### T21. simple_exit_v1 / v2 改善
**目的**: Exit 戦略の可視化と改善を通じて、利確・損切り品質を高める

**作業**
- [ ] closed trade に `exit_reason` を保存
- [ ] コンソールで exit reason 別成績を表示
- [ ] `simple_exit_v1` の現行成績を継続監視
- [ ] `simple_exit_v2` の改善案を定義（可変 stop / take profit / max hold）
- [ ] trailing / partial exit の候補を検討

**完了条件**
- [ ] exit reason ごとの件数・勝率・損益が見える
- [ ] `simple_exit_v2` の改善案が文書化されている
- [ ] Exit 戦略の改善優先順位が明確になっている

### T22. breakout_momentum_v1 / v2 改善
**目的**: 主力エントリー戦略の可視化と最適化を進め、entry quality と conversion を高める

**作業**
- [ ] `breakout_momentum_v1` の deny / reject / review 理由を集計
- [ ] symbol / strategy 別 conversion を継続監視
- [ ] signal_strength / confidence の分布を観測
- [ ] `breakout_momentum_v2` の改善案を定義（regime-aware / volatility-aware / symbol-group-aware）
- [ ] Exit 戦略との組み合わせ分析観点を定義

**完了条件**
- [ ] deny / reject の主要理由が見える
- [ ] conversion の改善観点が明確になっている
- [ ] `breakout_momentum_v2` の改善案が文書化されている
- [ ] entry / exit 一体改善の優先順位が明確になっている
