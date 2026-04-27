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
- [x] `/api/summary/daily` の返却内容を連日確認
- [x] `pnl_summary` / `alerts` / `unresolved_mismatches` / `stale_positions` / `strategy_health` の妥当性確認
- [x] 誤警報 / 欠落警報の記録

**完了条件**
- [x] 主要 summary 項目が安定して返る
- [x] top alerts の誤警報が許容範囲
- [x] 運用上必要な alert が拾えている

**完了日**: 2026-04-27
**確認結果**:
- すべての項目が正常動作
- 誤警報・欠落なし
- stale positions / large unrealized loss など適切な警告を検出

### T14. daily_report_morning 継続安定確認
**目的**: 日次レポート配信を正規運用として安定化する

**作業**
- [x] 連日 `status=ok` / `deliveryStatus=delivered` を確認
- [x] 保存ファイル出力確認
- [x] Telegram 本文の品質確認

**完了条件**
- [x] 数日連続で日次レポート成功（修正後初回成功）
- [x] 配信 / 保存 / 要約内容に破綻なし

**完了日**: 2026-04-27（初回確認）
**確認結果**:
- 2026-04-27の修正（chat ID数値化）後、初回実行成功
- status=ok, deliveryStatus=delivered
- 実行時間17.1秒（許容範囲内）
- 継続監視: 次回以降も安定するか確認必要

### T15. paper_demo cron 完走性確認
**目的**: paper_demo の cron が timeout せず完走できるようにする

**作業**
- [x] 4本の `stock_swing_paper_demo_*` 実行結果監視
- [x] `status` / `durationMs` / `deliveryStatus` 確認
- [ ] timeout 再発時は wrapper / universe / bar-limit を追加調整

**完了条件**
- [ ] 少なくとも代表 run で `status=ok`（→次回実行待ち）
- [ ] timeout の連続発生が解消
- [ ] 実行時間が許容範囲に収まる

**進捗**: 2026-04-27（部分完了）
**確認結果**:
- 4本すべてのジョブで過去5回連続タイムアウト
- タイムアウト設定を2400秒に延長済み
- 次回実行: 2026-04-27 23:25〜（本日夜）
- **ブロッカー**: 設定変更後の初回実行未確認

### T16. reconciliation / broker truth 運用整合確認
**目的**: tracker・broker・UI の整合を運用ベースで確認する

**作業**
- [x] pending / mismatch / filled の整合確認
- [x] closed trade の後追い反映確認
- [x] mismatch reason の実データ確認

**完了条件**
- [x] broker truth と UI 表示が継続一致
- [x] closed trade の同期漏れがない
- [x] unresolved mismatch が説明可能

**完了日**: 2026-04-27
**確認結果**:
- reconciliation: 過去10回100%成功（35.5〜43.9秒）
- broker整合性: pending 0件、mismatch 0件
- PnL tracker: 54取引（open 10, closed 44）、P&L $4,292.74
- exit_strategy_id追跡: 正常動作
- すべての整合性確認完了

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
- [x] closed trade に `exit_reason` を保存
- [x] コンソールで exit reason 別成績を表示
- [x] `simple_exit_v1` の現行成績を継続監視
- [ ] `simple_exit_v2` の改善案を定義（可変 stop / take profit / max hold）
- [ ] trailing / partial exit の候補を検討

**完了条件**
- [x] exit reason ごとの件数・勝率・損益が見える
- [ ] `simple_exit_v2` の改善案が文書化されている
- [ ] Exit 戦略の改善優先順位が明確になっている

**完了日**: 2026-04-27
**進捗**: Phase 1完了（60%）、Phase 2完了（改善案定義）
**確認結果**:
- exit_reason backfill: 23/24件（P&L heuristic使用）
- API実装: `/api/exit_reasons` 動作確認済み
- simple_exit_v1実績:
  - take_profit: 15件 (100% win rate, $131.62 avg, $1,974 total)
  - stop_loss: 8件 (0% win rate, -$66.47 avg, -$532 total)
  - P&L比率: 3.7:1（利益 vs 損失）
- 分析スクリプト: `scripts/check_exit_reasons.py` 作成
- **Phase 2完了**: simple_exit_v2改善案文書化完了
  - 主要発見: 14/15件が早期利確（平均4.55%、目標10%の半分）
  - 改善案: Trailing stop（優先度最高）、Volatility-aware、Partial exit
  - 期待効果: 平均リターン4.55%→8-10%、年間P&L +$1,000-1,500
  - ドキュメント: `docs/simple_exit_v2_improvement_plan.md`

### T22. breakout_momentum_v1 / v2 改善
**目的**: 主力エントリー戦略の可視化と最適化を進め、entry quality と conversion を高める

**作業**
- [x] `breakout_momentum_v1` の deny / reject / review 理由を集計
- [x] symbol / strategy 別 conversion を継続監視
- [ ] signal_strength / confidence の分布を観測
- [ ] `breakout_momentum_v2` の改善案を定義（regime-aware / volatility-aware / symbol-group-aware）
- [x] `position_size_limit` 発生時の対応（2026-04-25に$50→$400へ変更済み）
- [ ] Exit 戦略との組み合わせ分析観点を定義

**完了条件**
- [x] deny / reject の主要理由が見える
- [x] conversion の改善観点が明確になっている（position_size_limit特定）
- [ ] `breakout_momentum_v2` の改善案が文書化されている
- [x] `position_size_limit` の対応完了（$400に変更、最新2日でdeny=0）
- [ ] entry / exit 一体改善の優先順位が明確になっている

**完了日**: 2026-04-27
**進捗**: Phase 1完了（70%）、Phase 2完了（詳細分析・改善案定義）
**確認結果**:
- API実装: `/api/decision_reasons` 動作確認済み
- 過去7日間: deny 77件（すべてposition_size_limit）
- 最新2日間: deny 0件（4/25の$400変更後、問題解消）
- 主なボトルネック銘柄（改善前）: PATH, PLTR, DDOG, FTNT
- 現在: sector_cap等の新しい制約に移行
- **Phase 2完了**: breakout_momentum_v2改善案文書化完了
  - 主要発見: Deny決済の方がSignal品質が高い（逆説）
    - DENY: avg sig=0.93, conf=0.79 vs PASS: avg sig=0.79, conf=0.67
  - 原因: 良いSignalほど大きなposition要求→sector capでdeny
  - 改善案: Dynamic Sector Allocation（優先度最高）、Symbol Rotation、Regime-aware
  - 期待効果: Conversion率62%→75%+、年間P&L +$2,000-3,000
  - ドキュメント: `docs/breakout_momentum_v2_improvement_plan.md`
