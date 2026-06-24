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

**進捗更新**: 2026-05-15
- `paper_demo_*` 4ジョブの現況を再確認
- `market_open` / `midday` / `market_close` は `status=ok` を確認
- `premarket` は依然 `timeout` 残りで、last duration は約62分、consecutiveErrors=2
- timeout 対策として `paper_demo.py` を二段階取得へ変更
  - daily bars は全銘柄取得
  - breakout 候補のみ intraday 5-minute bars を取得
  - commit: `af87ab6` (`Use two-stage intraday fetch in paper demo`)
- premarket cron コマンドを更新
  - `python -u -m stock_swing.cli.paper_demo --allow-outside-hours --min-momentum 0.05 --intraday-candidate-limit 15`
- dry-run では intraday 取得対象が `64 symbols -> 34 candidates` に減少、関連テスト `35 passed`
- **判定**: premarket timeout の再発解消はまだ未確認のため、T15 は継続中

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
- [x] 主要ジョブの success/error/timeout 監視観点を定義
- [x] 遅延・連続失敗・未実行を検知する基準作成
- [x] 日次確認フローを明文化

**完了条件**
- [x] 主要 cron の健全性確認手順が定義済み
- [x] timeout / 失敗の見逃しが減る

**完了日**: 2026-04-28
**成果物**:
- `scripts/check_cron_health.py` - ヘルスチェックスクリプト
- `scripts/check_paper_demo_status.sh` - paper_demo 専用
- `docs/runbooks/CRON_DAILY_CHECK.md` - 日次確認フロー
- `docs/t17_cron_health_analysis.md` - 監視観点詳細

### T18. operational verification checklist の継続運用
**目的**: 完了済み機能の劣化を防ぐ

**作業**
- [x] `operational_verification_checklist.md` を週次/随時更新
- [x] 確認済み項目と未確認項目を管理
- [x] 実害のあった項目を優先監視に昇格

**完了条件**
- [x] checklist が形骸化せず使われている
- [x] 確認結果が daily log に反映される

**完了日**: 2026-04-28
**成果物**:
- `docs/operational_verification_log_2026-04-28.md` - 本日の確認結果
- `docs/operational_verification_checklist.md` 更新
- 優先監視項目の明確化

### T19. summary / alert の観測性改善
**目的**: summary が「返る」だけでなく「役立つ」状態にする

**作業**
- [x] alert の妥当性見直し
- [x] noisy alert / missing alert の改善
- [x] 必要なら UI への表示追加

**完了条件**
- [x] top alerts が運用判断に使える
- [x] 誤警報が抑えられている
- [x] summary の主要情報が見やすい

**完了日**: 2026-04-28
**成果物**: `docs/alert_improvements_2026-04-28.md`
**改善内容**:
- Severity 4段階明確化（critical/high/medium/low）
- 閾値最適化（~$100K account 基準）
- 新 alert 追加（losing_streak, low_conversion, strong_day等）
- 表示改善（最大8件、パーセント表示、詳細説明）

### T20. paper_demo 運用モード最適化 (進行中)
**目的**: paper_demo を継続運用可能な負荷へ調整する

**作業**
- [x] 実行時間・signal 数・submission 数を観測
- [ ] cron 用の軽量設定を必要に応じて分離
- [ ] universe / threshold / bar-limit の再調整

**完了条件**
- [ ] paper_demo が安定して回る
- [ ] 負荷と出力品質のバランスが取れている
- [ ] live cron が timeout / error なしで連続して正常完走する
- [ ] live decision で stock 6% / ETF 4.2% / sector 55% の sizing が意図どおり適用される
- [ ] 数営業日運用して、peak exposure / sector concentration / ETF偏重 / 大きいサイズ帯が実際に抑制され、副作用（過剰 skip など）が許容範囲に収まる

**進捗更新**: 2026-05-07
- paper_demo 4ジョブを wrapper 経由から direct Python 実行へ統一
- `toolsAllow` に `process` を追加し、background 時の追跡を可能化
- `market_open` の重さは data collection ではなく注文処理・reconciliation 側が支配的と確認
- `paper_demo.py` / `paper_executor.py` に軽量化を実装
- 今夜の `premarket / market_open` 実績確認後、軽量設定分離の要否を判断する

**進捗更新**: 2026-05-15
- `position_sizing.py` / `paper_demo.py` に sizing 改善案A を実装
- stock の `max_position_notional_pct` を `8% -> 6%` に縮小
- `max_sector_exposure_pct` を `80% -> 55%` に縮小
- ETF は stock の `0.7x` cap（実効 `4.2%`）へ変更
- `tests/unit/test_position_sizing_policy.py` を追加し、関連回帰テスト `31 passed` を確認
- `paper_demo --dry-run --universe full --allow-outside-hours` で broker 接続 / data collection / feature computation 正常を確認
- closed trades 67件ベースの簡易リプレイで、peak total exposure `-14.73%`、ETF entry notional `-21.04%`、total entry notional `-19.85%` を確認
- 追加で `paper_demo.py` を二段階 intraday 取得へ変更
  - daily 全件スクリーニング後、breakout 候補のみ intraday 取得
  - `--intraday-candidate-limit` を追加し、premarket は `15` に設定
  - dry-run で intraday 取得対象が `64 -> 34` 候補へ減少
  - 追加テスト込みで `35 passed`
  - commit: `af87ab6` (`Use two-stage intraday fetch in paper demo`)
- **判定**: sizing / exposure 抑制と premarket 軽量化の両方に前進。ただし live cron 完走性と数営業日の運用監視が未了のため、T20 は継続中

### T21. simple_exit_v1 / v2 改善
**目的**: Exit 戦略の可視化と改善を通じて、利確・損切り品質を高める

**作業**
- [x] closed trade に `exit_reason` を保存
- [x] コンソールで exit reason 別成績を表示
- [x] `simple_exit_v1` の現行成績を継続監視
- [x] `simple_exit_v2` の改善案を定義（可変 stop / take profit / max hold）
- [x] trailing stop 実装（Priority 1）
- [x] breakeven stop 実装（2026-05-27: peak +3% で stop を 0% に移動）
- [x] peak_price 永続化（2026-05-27: セッション間トレイリングが機能するよう）
- [x] エントリー強度連動 Exit 閾値（2026-05-27: 高/標準/低確信で stop・trailing を動的変更）
- [x] exit_reason 追跡改善（2026-05-27: pending_exit_reasons.json でセッション間引き継ぎ）

**完了条件**
- [x] exit reason ごとの件数・勝率・損益が見える
- [x] `simple_exit_v2` の改善案が文書化されている
- [x] trailing stop が実装されテスト済み
- [x] breakeven stop 実装済み
- [x] エントリー強度連動閾値 実装済み
- [ ] 数営業日後に Profit Factor が改善されているか再測定（現状 0.47x）

**2026-05-27 分析結果**:
- Profit Factor: **0.47x**（危険水域 — 期待値マイナス）
- Trade Expectancy: **-$331/trade**
- 全 77 closed trades が exit_reason=`broker_fill`（Exit 戦略が一度も機能していなかった）
- 今日の実装により次回以降は exit_reason が正確に記録される
- MDB(-7.7%) / CHPS(-9.8%) が hard stop 圏内 → 今夜の paper_demo で sell シグナル予定

**完了日**: 2026-04-28 (Phase 3 Priority 1 完了)
**成果物**:
- `src/stock_swing/strategy_engine/simple_exit_v2_strategy.py`
- `tests/unit/test_simple_exit_v2_strategy.py` (9テストすべてPASS)
- `docs/simple_exit_v2_improvement_plan.md`
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

### T26. Exit戦略の高度化 — 一時的下落とトレンド崩壊の区別
**目的**: 固定%ストップによる「一時的な値動きでの誤カット」を減らしつつ、本物の値崩れには確実に対応する

**背景（2026-06-22 議論）**
- 現行の `-7% からストップ` は機械的で実装は簡単だが、一時的な下落で数日で回復する場合に損をする
- 保有日数別PnLを見ると、短期クローズが一貫して赤字・長期保有が黒字だが、これが「短期カットが原因」なのか「生存バイアス」なのかは未判定
- **前提**: 反実仮想検証（Analytics Batch 2 #7）の結果を踏まえてから実装判断すること

**検討アプローチ（優先度順）**

#### アプローチA: 連続確認ウィンドウ（工数:小 / 効果:中〜高）
- 現行: `-7%を1日記録したらカット`
- 変更: `終値が-7%ラインを N日連続で下回ったらカット`（N=2〜3）
- メリット: コード変更が数行、現行構造を壊さない
- デメリット: 本当に崩れている時も N日待つため損失が膨らむリスク
- 向くケース: 相場全体の一時的な全面安（5/14のような急落日）

#### アプローチB: MA20割り込み確認（工数:中 / 効果:高）★推奨
- `current_price > MA20` の間はトレンド継続とみなし保有継続
- `MA20割り込み かつ return < -5% かつ 2日継続` → カット
- メリット: 「トレンド内の揺れ」と「トレンド自体が崩れた」を区別できる
- デメリット: MA20の日次計算が必要（取得可能だが追加実装あり）
- 向くケース: モメンタム戦略と相性が良い（モメンタム崩れ = MA割り込みと連動しやすい）

#### アプローチC: ATRベース動的ストップ（工数:中 / 効果:高）★推奨
- 固定-7%を廃止し、`ATR(14) × N倍` をストップ幅にする
- 例: ボラが高い銘柄は自動的に余裕が広がり、低い銘柄はタイト
- メリット: 銘柄ごとのボラティリティに自動適応
- デメリット: ATRが大きい銘柄はストップが遠くなりすぎるため上限設定が必要
- 向くケース: ポートフォリオ内でボラが大きく異なる場合（現在の構成に合う）

#### アプローチD: 保有日数連動型ストップ（工数:小 / 効果:中）
- Day 1-5: ストップなし or -12%（初期ノイズを無視）
- Day 6-14: -7% ハードストップ有効化
- Day 15+: ピーク比 -4% のトレーリングに移行
- メリット: 「買い直後の短期ノイズ」を物理的に排除できる
- デメリット: 初期に大きく崩れても何もしない期間ができる
- 向くケース: エントリー直後の調整が頻繁に起きているパターンが確認された場合

#### アプローチE: 出来高＋値動きの複合判定（工数:大 / 効果:最高）
- 下落 + 出来高が20日平均の1.5倍以上 → 本物の崩れ → カット
- 下落 + 出来高が少ない → 一時的 → 保有継続
- メリット: 機関投資家の売りを検知できる。理論的に最も正確
- デメリット: 出来高データの取得・統合が必要（追加実装コスト大）
- 向くケース: 反実仮想検証でA〜Dが不十分と判明した場合のフェーズ2

**推奨実装順序**
1. **反実仮想検証を先に実施**（Analytics Batch 2 #7）— 「短期カットが原因か生存バイアスか」を確認
2. 検証結果でカット回避が有効と判明したら **A（連続確認）＋B（MA20）を組み合わせて実装**
   - カット条件: return < -7% **かつ** MA20割り込み **かつ** 2日以上継続
   - この組み合わせで「5/14全面安のような一時的-7%」を保護できる
3. ATRベース（C）は次のイテレーションで検討
4. 出来高複合（E）はニュース感情フィーチャー（T25）と並行して長期検討

**作業**
- [ ] 反実仮想検証の結果レビュー（前提条件）
- [ ] アプローチA: 連続確認ウィンドウを `simple_exit_v2.yaml` + `SimpleExitV2Strategy` に実装
- [ ] アプローチB: MA20計算を `PriceMomentumFeature` または新規 feature として追加
- [ ] AとBの組み合わせ条件を `SimpleExitV2Strategy` に統合
- [ ] ATR取得ロジックの調査（アプローチC検討用）
- [ ] dry-run で誤カット回数の変化を検証
- [ ] exit_replay.py にA〜C相当のシミュレーションを追加して比較評価
- [ ] 回帰テスト追加（`test_simple_exit_v2_strategy.py` 拡張）

**完了条件**
- [ ] 反実仮想検証の結果が「早期カット回避が有効」であることを確認済み
- [ ] 少なくともA＋Bが実装済みでテスト通過
- [ ] dry-run で exit シグナルの発火パターンが変化したことを確認
- [ ] 数営業日の実稼働後に Profit Factor の変化を再測定

**優先度**: 中（反実仮想検証の完了を待ってから着手）  
**依存関係**: Analytics Batch 2 #7（反実仮想検証）→ 本タスク  
**追加日**: 2026-06-22  

---

### T22. breakout_momentum_v1 / v2 改善 (進行中) (Phase 3 Priority 1 完了)
**完了日**: 2026-04-28
**目的**: 主力エントリー戦略の可視化と最適化を進め、entry quality と conversion を高める

**作業**
- [x] `breakout_momentum_v1` の deny / reject / review 理由を集計
- [x] symbol / strategy 別 conversion を継続監視
- [x] signal_strength / confidence の分布を観測
- [x] `breakout_momentum_v2` の改善案を定義（regime-aware / volatility-aware / symbol-group-aware）
- [x] `position_size_limit` 発生時の対応（2026-04-25に$50→$400へ変更済み）
- [x] Exit 戦略との組み合わせ分析観点を定義

**完了条件**
- [x] deny / reject の主要理由が見える
- [x] conversion の改善観点が明確になっている（position_size_limit特定）
- [x] `breakout_momentum_v2` の改善案が文書化されている
- [x] `position_size_limit` の対応完了（$400に変更、最新2日でdeny=0）
- [x] entry / exit 一体改善の優先順位が明確になっている

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
- **2026-05-07更新**:
  - entry / exit 一体分析観点を `docs/t22_entry_exit_analysis_framework_2026-05-07.md` に整理
  - `scripts/analyze_entry_exit_pairs.py` を追加し、closed trades の entry_strategy × exit_reason / regime 深掘りを可能化
  - cautious regime での ARM / DELL / CIEN 悪化傾向を確認
  - 具体改善案は `docs/t22_cautious_regime_symbol_actions_2026-05-07.md` に整理
  - ただし過剰最適化回避のため、cautious regime 向け個別改善は当面ペンディング

---

## 2026-05-15 重大問題の解決と今後の対応

### 完了: Exit Strategy の根本修正
**問題**: Alpaca fetch_bars() API がすべての symbols (stocks + ETFs) で 2026-04-22 に停止
**影響**:
- 23日前の stale data による 15-40% price deviation
- ETF total loss: -$9,367.59 (37 trades)
- すべての exit signals が誤判定

**実施した修正**:
1. ✅ Stale data detection 実装 (`72ca13a`)
   - `PriceMomentumFeature`: 7日以上古いデータに `stale_data` フラグ
   - `SimpleExitV2Strategy`: Position current_price を最優先
   - テスト追加: `test_stale_price_data.py`

2. ✅ Massive API 統合 (`c91f530`)
   - `HybridDataFetcher`: Massive primary, Broker fallback
   - すべての symbols で fresh data 取得（2026-05-14）
   - ETF trading 安全に再開

3. ✅ Massive WebSocket 設定文書化 (`ded5b3f`)
   - Business plan 向け正しい設定を文書化
   - 実装ガイド作成: `docs/massive_websocket_implementation.md`

### T23. Massive API 運用監視
**目的**: Massive API の安定運用と最適化

**作業**
- [x] paper_demo cron で Massive API 動作確認
- [x] Rate limit 超過なし
- [x] paper_demo 実行時間が許容範囲内（各約5分）
- [ ] Broker fallback 時のアラート設定

**完了条件**
- [x] 連続営業日、すべての symbols で fresh data 取得を確認
- [x] Rate limit 超過なし
- [x] paper_demo 実行時間が許容範内（< 60分）

**完了日**: 2026-05-27（基本的に安定運用を確認）

### T24. Massive WebSocket 実装（Phase 2）
**目的**: Real-time price data でコンソールと取引判断を強化

**作業**
- [ ] `MassiveWebSocketClient` 実装
  - Connection & authentication
  - Subscribe to symbols (AM.AAPL format)
  - Message parsing & handling
- [ ] Console 統合
  - Real-time price display
  - Unrealized P&L live update
- [ ] Trading system 統合
  - Intraday entry/exit signals
  - Real-time alert triggers
- [ ] テスト
  - Manual test with wscat
  - Automated integration tests

**完了条件**
- [ ] WebSocket client が安定動作（reconnection 機能含む）
- [ ] Console で real-time prices 表示
- [ ] Intraday signals が real-time data を使用

**優先度**: 中（Massive API REST 運用が安定してから）
**参考**: `docs/massive_websocket_implementation.md`

### T25. Corporate Action / Stock Split 正規対応
**目的**: KLAC のような stock split 発生時に、価格・数量・監査・再構築を一貫して扱えるようにする

**背景**
- 2026-06-12 に KLAC が 10-for-1 split-adjusted 取引へ移行
- broker の paper data / order history / position API で split 前後の倍率差が混在し、`entry_price`・`avg_entry_price`・`peak_price`・監査結果に歪みが出た
- 現在は Yahoo 突合ベースの暫定補正で運用継続中だが、heuristic 依存のため恒久対応が必要

**作業**
- [ ] `corporate_actions` 台帳を追加
  - `symbol`, `action_type`, `factor`, `effective_at`, `source`, `verified_at`
  - 一次ソースは IR / SEC / 公式 corporate action を優先
- [ ] raw 値と normalized 値の責務を整理
  - broker 約定・position の生値を保持
  - split-adjusted の計算用フィールドを別管理
- [ ] open position の split 適用処理を実装
  - `qty`, `entry_price`, `peak_price`, `stop_price`, `risk_per_share` を効力日で変換
- [ ] closed trade の前後跨ぎ split 正規化
  - entry と exit が異なる基準のまま計算されないように統一
- [ ] データ取得層に adjusted/unadjusted メタデータを追加
  - `HybridDataFetcher`, `MassiveClient`, broker fallback の混在検知
- [ ] `rebuild_pnl_state_from_broker.py` / `audit_trades_with_market_data.py` / reconciliation を corporate action 優先へ変更
  - heuristic 補正は fallback 扱いに縮小
- [ ] runbook とテスト追加
  - split 検知時の手順
  - KLAC ケースの回帰テスト

**完了条件**
- [ ] split 発生銘柄で tracker / broker / audit の整合が手補正なしで保たれる
- [ ] rebuild 後に `peak_price` や `avg_entry_price` の倍率異常が再発しない
- [ ] broker fallback と adjusted daily bars の混在時も監査誤検知が出ない
- [ ] runbook に沿って月次運用で再現可能

**優先度**: 中
**実施タイミング**: 2026-06 月末から 2026-07 前半で対応
**暫定対処**:
- Yahoo / market data 突合による倍率補正
- broker daily bar より Yahoo fallback を優先
- rebuild / audit / peak_price 復元の局所補正
**備考**: 実装前に KLAC 以外の split 履歴も 1-2 銘柄サンプルで確認する

### T15. paper_demo cron 完走性確認（継続中）
**進捗更新**: 2026-05-27
- 4ジョブとも `status=ok` が継続中（last duration 各約5分）
- premarket timeout は実質解消済み（二段階取得 + Massive API）
- **引き続き**: 数営業日の安定継続を確認中

**完了条件**:
- [x] premarket が 60分以内に完了
- [ ] 連続3営業日、4ジョブすべて完走（継続監視）
- [x] decision count / submitted count が妥当

### T20. paper_demo 運用モード最適化（継続中）
**進捗更新**: 2026-05-27
- sizing 改善案A 実装完了・Massive API 統合完了
- **2026-05-27 追加実装**:
  - exposure 上限到達時に zero-sized buy を preflight で除外 (`4c362cc`)
  - PaperExecutor precomputed sizing 再利用
  - stale open buy order 自動キャンセル機能を reconcile_orders に追加 (`61b5df1`)
- **残課題**: SIGTERM 問題は解消せず（snapshot は early write で保護済み）

**完了条件**:
- [x] Massive API 経由で price deviation がない
- [x] zero-sized buy の無駄な broker submit を排除
- [x] stale day order の翌日自動キャンセル
- [ ] live cron 安定完走（3営業日連続 / 継続監視）
- [ ] sizing 改善効果の数営業日検証

---

## Phase 3 — ニュース感情フィーチャー

### T25. ニュース感情フィーチャーの実装・評価（3ステップ計画）
**目的**: 収集中のニュースデータを取引判断に実際に活用し、成績向上を検証する

#### Step 1: 株式44銘柄データ蓄積・相関評価（〜2026-06-15 目安）
**前提**: 2026-05-25 より news_collection cron を 8銘柄 → 44銘柄へ拡張済み

**作業**
- [ ] 2〜3週間のニュースデータを蓄積（自動）
- [ ] `scripts/analyze_news_impact.py` を再実行し統計的有効性を確認
  - 相関係数 |r| > 0.3 かつ サンプル数 n ≥ 30 を合格基準とする
- [ ] 有効性なし → T25 を中断（コスト対効果が見合わない）
- [ ] 有効性あり → Step 2 へ進む

**完了条件**
- [ ] analyze_news_impact.py が n≥30 で実行できる
- [ ] 結果を `docs/daily_logs/` に記録

#### Step 2: ETF ニュースマッピング追加（Step 1 通過後）
**背景**: ETF は個社ニュースを持たないが、構成株式のニュース感情を集約することでセンチメントを近似できる  
**追加APIコスト**: ゼロ（構成株式のニュースを Step 1 で既に収集済み）  
**実装コスト**: 約半日

**ETF → 代表銘柄マッピング案**
```python
ETF_SECTOR_MAP = {
    # 半導体ETF
    "SOXX":  ["NVDA","AMD","INTC","QCOM","AMAT","LRCX","MU","MRVL","AVGO","ARM"],
    "SOXQ":  ["NVDA","AMD","INTC","QCOM","AMAT","LRCX","MU","MRVL","AVGO","ARM"],
    "SMH":   ["NVDA","ASML","TSM","AVGO","AMD","QCOM","AMAT","INTC","LRCX","MU"],
    "SMHX":  ["NVDA","AMD","INTC","QCOM","AMAT","LRCX","MU","MRVL","ARM"],
    "FTXL":  ["NVDA","AMD","AVGO","QCOM","AMAT","LRCX","KLAC","MU"],
    # ブロードテックETF
    "PSCT":  ["HPE","DELL","CSCO","IBM","ANET","SNPS","CDNS","HPQ"],
    "QTEC":  ["NVDA","MSFT","GOOGL","AMAT","LRCX","SNPS","CDNS","KLAC"],
    "PTF":   ["NVDA","AMD","AVGO","QCOM","AMAT","ARM","MU"],
    # クラウド・ソフトウェア
    "SKYY":  ["CRM","SNOW","MDB","DDOG","ORCL","NOW","MSFT","GOOGL"],
    # 量子・AI特化
    "QTUM":  ["GOOGL","IBM","MSFT","NVDA","INTC","AMZN"],
    "CHPS":  ["NVDA","AMD","INTC","QCOM","AMAT","MU","ARM","AVGO"],
    "CHPX":  ["NVDA","AMD","INTC","QCOM","AMAT","MU","ARM","AVGO"],
    # その他
    "TTEQ":  ["NVDA","MSFT","GOOGL","AMZN","META","AVGO","AMD"],
    "GTOP":  ["NVDA","MSFT","GOOGL","AMZN","META","TSLA","AVGO"],
    "FRWD":  ["NVDA","AMD","AVGO","QCOM","AMAT","ARM","KLAC"],
    "TDIV":  ["MSFT","AVGO","CSCO","IBM","QCOM","INTC","HPE"],
    "SHOC":  ["NVDA","AMD","AVGO","QCOM","AMAT","KLAC","MU"],
}
```

**作業**
- [ ] `analyze_news_impact.py` に ETF_SECTOR_MAP を追加
- [ ] ETF の感情スコアを構成銘柄の加重平均で算出
- [ ] ETF トレードを含めて相関分析を再実行

**完了条件**
- [ ] ETF を含む全クローズトレードに感情スコアが付与できる
- [ ] 相関分析の対象が 77件以上に拡大

#### Step 3: NewsFeature の実装と paper_demo への組み込み（Step 2 通過後）
**作業**
- [ ] `feature_engine/news_sentiment_feature.py` を実装
  - 直近24hのニュース感情スコアを特徴量として出力
  - ETF は ETF_SECTOR_MAP 経由で集約
- [ ] `breakout_momentum_strategy.py` に news_sentiment を入力として追加
  - negative news 時は buy を抑制 or confidence を下げる
- [ ] paper_demo の `--dry-run` で動作確認
- [ ] 回帰テスト追加

**完了条件**
- [ ] decision ファイルの `feature_refs` に `news_sentiment` が含まれる
- [ ] 既存テストがすべて通る

**優先度**: 中（Step 1 の評価結果次第）
**開始条件**: Step 1 で有効性確認後

---

---

## Console Fetch Stability — 実装済み（2026-05-28 完了）

> **完了**: 2026-05-28 午後に Batch 1〜2 を全て実装・テスト済み（37/37 PASSED）。
> 以下は Batch 3 + Frontend 改善として残っているタスク（ペンディング）。
> 現状は TTL キャッシュ・ThreadingHTTPServer・atomic write で安定化済み。

### ✅ 完了済み（2026-05-28）
- [x] `src/stock_swing/storage/atomic_json.py` — atomic_write_json / read_json_with_retry
- [x] `pnl_tracker.py` / `exit_reason_store.py` — atomic write / retry read に変更
- [x] `console/services/response_cache.py` — スレッドセーフ TTL キャッシュ
- [x] `console/services/safe_file_reader.py` — last-known-good フォールバック付き JSON リーダー
- [x] `console/app.py` — ThreadingHTTPServer + RLock + TTL キャッシュ + `_timed_json`（timing + request_id）
- [x] Unit tests: 37/37 PASSED

### 残タスク（ペンディング）

### CF-1. Batch 3: スナップショット方式（長期最適化）
**優先度**: 低（現状の TTL キャッシュで同等効果が得られているため）

**概要**: paper_demo / reconcile が実行のたびに `data/console/dashboard_snapshot.json` を書き出し、コンソールはそれを読むだけにする。

**作業**
- [ ] `src/stock_swing/console_snapshot/build_snapshot.py` を新規作成
  - atomic write で `data/console/dashboard_snapshot.json` を出力
  - schema: `generated_at / source / summary / positions / trading / risk_guardrails / data_quality / warnings`
- [ ] `paper_demo.py` および `reconcile_orders.py` の末尾から `build_snapshot()` を呼び出す
- [ ] `console/app.py` に `GET /api/dashboard_snapshot` エンドポイントを追加
  - スナップショットを読むだけ（broker 不呼び出し、重い計算なし）
  - 目標レイテンシ: < 100ms
  - ファイル不在時は `available: false` を返す

**メリット**: コンソールと trading プロセスが完全疎結合。レイテンシが数秒→数十ms。
**デメリット**: データ鮮度がスナップショット更新タイミング依存（最大 15〜30 分ラグ）。trading コード変更が発生。

**開始条件**: T15/T20 が安定完走確認後、かつ Failed to Fetch が再発した場合に優先度を上げる。

---

### CF-2. Task F1: フロントエンド stable fetch wrapper
**優先度**: 中（サーバー側は安定化済み。残る一時的 Failed to Fetch をユーザーから隠せる）

**概要**: `console/ui/app.js` のポーリング fetch を AbortController タイムアウト + リトライ + 重複排除 + stale バッジ付きの中央 wrapper に置き換える。

**作業**
- [ ] `console/ui/api-client.js` に `fetchJsonStable(url, options)` を実装
  - `AbortController` で 8 秒タイムアウト
  - 指数バックオフリトライ（最大 3 回）
  - `inflight` Map で同一エンドポイントの重複リクエスト排除
  - `lastGood` Map で最後の成功レスポンスをキャッシュ
  - 失敗時は `{ data: lastGood, stale: true, error }` を返す（UI を白くしない）
- [ ] `app.js` の各 `fetch()` 呼び出しを `fetchJsonStable()` に置き換え
- [ ] stale 時に UI に非ブロッキングな「データ古い」バッジを表示

**メリット**: 偶発的な Failed to Fetch がユーザーに見えなくなる。実装コスト半日程度。
**デメリット**: `app.js` の全面改修が必要。テストがブラウザ依存で書きにくい。

---

### CF-3. Task F2: ポーリング間隔の最適化
**優先度**: 中（工数小・リスク小・即効性あり。CF-2 と組み合わせると効果倍増）

**概要**: 重いエンドポイントのポーリング間隔を伸ばし、タブ非表示時は停止する。

**推奨間隔**
```
/api/dashboard_snapshot  10〜30 秒
/api/live_metrics        10〜15 秒
/api/positions           15〜30 秒
/api/decision_reasons    60 秒
/api/strategy_analysis   60〜300 秒
/api/exit_reasons        60 秒
```

**作業**
- [ ] `app.js` の各 `setInterval` を上記推奨値に変更
- [ ] `document.visibilityState === 'hidden'` 時はポーリングを一時停止
- [ ] WebSocket 接続中は重いエンドポイントのポーリングをスキップ

**メリット**: 実装 30 分程度。サーバー負荷が単純に減る（strategy_analysis を 60s→300s にするだけでリクエスト数 5 分の 1）。副作用リスクほぼゼロ。
**デメリット**: リアルタイム感がわずかに下がる。根本的な解決にはならない。

---

---

## Analytics Batch 1 — 実装済み（2026-05-28 完了）

> **完了**: 2026-05-28 午後に P1 4件を全て実装・テスト済み（51/51 PASSED）。
> 全エンドポイントは broker 資格情報不要・TTL キャッシュ付き。

### ✅ 完了済み（2026-05-28）
- [x] `src/stock_swing/analytics/strategy_attribution.py` — ETF/Stock/戦略/exit_reason 別 PF・損益分析
  - ETF PF=0.168 / Stock PF=1.731 を実データで確認済み
- [x] `src/stock_swing/analytics/data_quality_audit.py` — signal_strength 欠損・price override・quality_flags 検出
  - open 53件全て signal_strength 欠損 / price overrides 4シンボルをアクティブ確認
- [x] `src/stock_swing/risk/risk_budget.py` — 総・銘柄・セクター・ETF 別リスク予算 + buy 候補拒否ロジック
  - **注意**: 現在 open risk 6.6%（ポリシー上限 3% の 2.2 倍）。paper_demo 組み込み前に閾値チューニング必須
- [x] `src/stock_swing/analytics/exit_replay.py` — 7種類の exit ポリシー比較（推定値・peak_price 近似）
  - `tighter_stop_4pct` が最良（+$1,012 改善）。全 85 trades で peak_price 欠損のため breakeven/trail は測定不能
- [x] コンソールエンドポイント 4本追加（`/api/strategy_attribution` / `/api/data_quality` / `/api/risk_budget` / `/api/exit_replay`）
- [x] Unit tests: 51/51 PASSED（合計 60/60）

### 残タスク（Analytics Batch 2 以降）
- [ ] **P2: Entry Quality Scoring** — buy 候補のエントリー品質スコアリング
- [ ] **P2: ETF Strategy Separation** — ETF 専用戦略・独立メトリクス
- [ ] **P2: Paper Trade Audit Trail** — 全 buy/sell/deny を外部監査可能な形式で記録
- [ ] **P2: Backtest vs Paper Drift Monitor** — ライブ挙動とバックテスト想定の乖離検出
- [ ] **P2: Benchmark Attribution Maintenance** — SPY benchmark 更新を cron / daily report 前処理へ組み込み、α/β のデータ鮮度を維持
- [ ] **P3: Capital Heatmap** — セクター・銘柄・資産クラス別集中リスク可視化
- [ ] **P3: Promotion Gate** — ペーパーデモ卒業基準の定義・コンソール表示
- [ ] **Risk Budget 閾値チューニング** — 現 6.6% open risk を踏まえたポリシー値の見直し

---

## Analytics Maintenance — Benchmark Attribution（2026-06-01 追加）

### 完了済み
- [x] SPY benchmark を `venv/bin/python scripts/update_benchmark_data.py` で更新
  - 更新後: 2026-04-02〜2026-05-29、40営業日
- [x] α/β/Sharpe 計算前に、同日複数 `daily_snapshots` を日次最終 snapshot へ正規化
  - 対象: `console/services/benchmark_service.py`
- [x] 回帰テスト追加
  - `tests/test_console_services.py::TestBenchmarkService`

### 状態
- αは表示可能: 実データで `+1.21%`
- βは現時点では未表示が正しい
  - 正規化後に SPY と一致するユニーク日次 snapshot が 3営業日分のみ
  - `BenchmarkService.calculate_beta()` は最低5本の return、つまり6営業日分の一致データを要求

### 後日対応
- [ ] SPY benchmark 更新を cron または `daily_report_morning` 前処理に組み込む
- [ ] 6営業日分以上の一致データがたまった後、分析タブでβが自然表示されることを確認
- [ ] `scripts/fetch_benchmark.py` は broker rate limit を受けやすいため、運用経路は `scripts/update_benchmark_data.py` を優先する

---

---

## Signal Strength 診断（2026-06-23）

### 現状の問題

| 項目 | 内容 |
|---|---|
| 分布の偏り | BUY シグナルの **73%が strength=1.0** （mean=0.94）|
| 閘別化不十分 | 現在の閾値 0.85 は全 BUY シグナルの 86% を包含し、「強い」の判別力がたい |
| intraday_enhanced の 隣陛い | intraday enhanced は 100% が 0.85 以上、閾値が実質無効 |
| 実績データなし | `entry_signal_strength` が trade レコードに保存されていない（0/190 件） |

### 改善タスク（改善計画リストに登録）

- [ ] **S1. `entry_signal_strength` を trade レコードに保存** — 将来の強度 vs 勝率・損益分析の前提条件
- [ ] **S2. シグナル強度の粒度化** — breakout_momentum で一律 1.0 になる原因を調査し、動流・ボラティリティ・コンファーメーション等を囍み込んで 0.5–1.0 の広い分布に改善
- [ ] **S3. 動的 cap 閾値の再評価** — S2 完了後、実帾データで 0.85 閾値の山笲が適切か確認（現状は 86% 記録 → 識別力不足）
- [ ] **S4. 強度 vs パフォーマンス分析** — S1+S2 完了後、strength 分布別の勝率・ PF を計測し閾値を根拠に基づかせる

### 現時点の繊ぎ起ぎ対応
現在の動的 cap（0.85 閾値）は「市場シグナルが多いか少ないか」をカウントする設計としては機能する（山笲は高すぎるが、シグナル少数 = cap 下がりの意図は維持される）。S2 の完成までは現行のまま運用。

---

---

---

## 実装フェーズ管理（P0〜P12）

実装の進捗を P-フェーズ単位で管理する。各フェーズは独立デプロイ可能な単位。

### ✅ P0: 基礎ガードレール（2026-05-28 完了）

| サブタスク | 内容 | 状態 |
|---|---|---|
| P0-A | ETF buy ガードレール（後に解除・条件変更） | ✅ |
| P0-B | Exit quality 改善（peak_price 永続化・breakeven stop） | ✅ |
| P0-C | Risk budget ガードレール（warn 5% / block 8%） | ✅ |
| P0-D | Parameter alignment / qty contract 整理 | ✅ |

### ✅ P1: Analytics Batch 1（2026-05-28 完了）

| サブタスク | 内容 | 状態 |
|---|---|---|
| P1-A | `strategy_attribution.py` — ETF/Stock 別 PF・損益分析 | ✅ |
| P1-B | `data_quality_audit.py` — signal_strength 欠損・price override 検出 | ✅ |
| P1-C | `risk_budget.py` — 総・銘柄・セクター・ETF 別リスク予算 | ✅ |
| P1-D | `exit_replay.py` — 7 種類の exit ポリシー比較 | ✅ |

### ✅ P2: Console Fetch Stability（2026-05-28 完了）

| サブタスク | 内容 | 状態 |
|---|---|---|
| P2-A | `atomic_json.py` — atomic write + retry read | ✅ |
| P2-B | `response_cache.py` + `safe_file_reader.py` | ✅ |
| P2-C | `console/app.py` — ThreadingHTTPServer + RLock + TTL キャッシュ | ✅ |

### ✅ P3: Exit 戦略強化（2026-05-27 完了）

| サブタスク | 内容 | 状態 |
|---|---|---|
| P3-A | Breakeven stop（peak +3% → return ≤0% で売却） | ✅ |
| P3-B | peak_price 永続化（57件 open trades を初期化） | ✅ |
| P3-C | Entry 強度連動 exit 閾値（高/標準/低確信 3段階） | ✅ |
| P3-D | exit_reason 追跡（`pending_exit_reasons.json` でセッション間引き継ぎ） | ✅ |

### ✅ P4: リスク高度化（2026-06-23 完了）

| サブタスク | 内容 | 状態 |
|---|---|---|
| P4-A | Walk-Forward Exit Validation (`walkforward_exit_analysis.py`) | ✅ |
| P4-B | Correlation Cluster Risk Cap (`correlation_cluster.py` + paper_demo 統合) | ✅ |
| P4-C | Structured Console Summary (`console_summary.py` + `emit()`) | ✅ |
| P4-D | Staged AI Context Packs (`context_budget.py` — minimal/normal/expanded/emergency) | ✅ |

### ✅ P5: CI ガードレール + Signal Strength 計測基盤（2026-06-23 完了）

| サブタスク | 内容 | 状態 |
|---|---|---|
| P5-A | `scripts/secret_scan.py` — CI 用シークレットスキャン | ✅ |
| P5-B | S1: `entry_signal_strength` を trade レコードに保存 | ✅ |

---

### 🔲 P6: Console Stability 完成 + Analytics Batch 2 基盤

**目的**: フロントエンド安定化と Analytics 第2弾の基礎的計測を揃える

| サブタスク | 内容 | 優先度 | 依存 |
|---|---|---|---|
| P6-A | CF-2: フロントエンド stable fetch wrapper (`api-client.js`) | 中 | なし |
| P6-B | CF-3: ポーリング間隔最適化（重い EP を 60〜300 秒へ） | 中 | なし |
| P6-C | Risk Budget 閾値チューニング（6.6% open risk を実態に合わせ調整） | 高 | なし |
| P6-D | SPY Benchmark 更新を cron/daily_report_morning 前処理に組み込み | 中 | なし |

**完了条件**
- [ ] `fetchJsonStable()` wrapper 実装済み・stale バッジ動作確認
- [ ] ポーリング間隔変更後のサーバー負荷低減を確認
- [ ] Risk Budget deny ロジックが paper_demo に組み込まれた
- [ ] β表示に必要な 6 営業日分以上のデータが自動蓄積される仕組みが稼働

---

### 🔲 P7: 反実仮想検証 + Exit 戦略高度化 (T26)

**目的**: 「短期カットが原因か生存バイアスか」を定量評価し、Exit 戦略を根拠に基づいて高度化する

**前提**: S1（P5-B）完了済み → 実績データ蓄積を待って実施

| サブタスク | 内容 | 優先度 | 依存 |
|---|---|---|---|
| P7-A | 反実仮想検証スクリプト — 短期クローズ負けトレードを仮保有した場合の推計 | 高 | P5-B |
| P7-B | T26-A: 連続確認ウィンドウ（N 日連続 -7% 未満でカット）| 高 | P7-A |
| P7-C | T26-B: MA20 割り込み確認（MA20 割り込み + return<-5% + 2日継続）| 高 | P7-A |
| P7-D | A+B 組み合わせ条件を `SimpleExitV2Strategy` に統合 | 高 | P7-B, P7-C |
| P7-E | T26-C: ATR ベース動的ストップ（ボラティリティ適応） | 中 | P7-D 評価後 |

**完了条件**
- [ ] 反実仮想検証の結果が「早期カット回避が有効」であることを確認
- [ ] T26 A+B 実装済み・テスト通過
- [ ] exit_reason の多様化（`ma20_stop` / `consecutive_stop` が記録される）
- [ ] 数営業日後に Profit Factor の変化を再測定

---

### 🔲 P8: シグナル強度の粒度化 (S2〜S4)

**目的**: 一律 1.0 問題を解消し、強度に基づいたフィルタリングを機能させる

**前提**: P5-B（S1）完了 → 実績データが一定量蓄積された後に実施

| サブタスク | 内容 | 優先度 | 依存 |
|---|---|---|---|
| P8-A | S2: `breakout_momentum` 強度算出ロジック改修（momentum / volatility / confirmation 組み込み） | 高 | P5-B |
| P8-B | S3: 動的 cap 閾値の再評価（実績データで 0.85 閾値の識別力を検証） | 中 | P8-A |
| P8-C | S4: strength 分布別 勝率・PF 計測 → 閾値を根拠に定める | 中 | P8-A, P8-B |

**完了条件**
- [ ] BUY シグナルの strength 分布が 0.5〜1.0 に広がっている（現在 73% が 1.0）
- [ ] 動的 cap の 0.85 閾値に識別力があることを実績データで確認
- [ ] strength 別 PF が定量化され、次フェーズの判断基準として使える

---

### 🔲 P9: Corporate Action 対応 (T25-struct)

**目的**: KLAC のような stock split 発生時に、price/qty/audit を一貫して扱えるようにする

**目安**: 2026-07 前半

| サブタスク | 内容 | 優先度 | 依存 |
|---|---|---|---|
| P9-A | `corporate_actions` 台帳追加（symbol / action_type / factor / effective_at） | 中 | なし |
| P9-B | open position の split 適用（qty / entry_price / peak_price / stop_price 変換） | 中 | P9-A |
| P9-C | closed trade の前後跨ぎ split 正規化 | 中 | P9-A |
| P9-D | `rebuild_pnl_state` / `audit` / reconciliation を corporate action 優先に変更 | 中 | P9-A〜C |
| P9-E | Runbook + KLAC ケース回帰テスト | 中 | P9-D |

**完了条件**
- [ ] split 発生銘柄で tracker / broker / audit の整合が手補正なしで保たれる
- [ ] rebuild 後に peak_price / avg_entry_price の倍率異常が再発しない

---

### 🔲 P10: ニュース感情フィーチャー (T25-feature)

**目的**: 収集中のニュースデータを取引判断に実際に活用し、成績向上を検証する

**前提**: 2026-06-15 目安にデータ蓄積完了 → Step 1 評価を先に実施

| サブタスク | 内容 | 優先度 | 依存 |
|---|---|---|---|
| P10-A | Step 1: `analyze_news_impact.py` で n≥30 / \|r\|>0.3 を確認 | 中 | データ蓄積 |
| P10-B | Step 2: ETF_SECTOR_MAP を追加して ETF の感情スコアを近似 | 中 | P10-A 通過 |
| P10-C | Step 3: `news_sentiment_feature.py` 実装 + paper_demo 組み込み | 中 | P10-B |

**完了条件**
- [ ] analyze_news_impact.py が n≥30 で相関係数基準を通過
- [ ] decision ファイルの `feature_refs` に `news_sentiment` が含まれる
- [ ] 既存テストが全て通る

---

### 🔲 P11: Analytics Batch 2 + 高度可視化

**目的**: 運用分析の深度を高め、ペーパーデモ卒業判断を可能にする

| サブタスク | 内容 | 優先度 | 依存 |
|---|---|---|---|
| P11-A | Entry Quality Scoring — buy 候補のエントリー品質スコアリング | 中 | P8-A |
| P11-B | ETF Strategy Separation — ETF 専用戦略・独立メトリクス | 中 | なし |
| P11-C | Paper Trade Audit Trail — 全 buy/sell/deny を外部監査可能な形式で記録 | 中 | なし |
| P11-D | Backtest vs Paper Drift Monitor — ライブ挙動とバックテスト想定の乖離検出 | 中 | なし |
| P11-E | Capital Heatmap — セクター・銘柄・クラス別集中リスク可視化 | 低 | なし |
| P11-F | Promotion Gate — ペーパーデモ卒業基準の定義・コンソール表示 | 低 | P11-A〜D |

**完了条件**
- [ ] entry quality score が decision ファイルに記録される
- [ ] ETF 専用メトリクスがコンソールに独立して表示される
- [ ] paper → live 昇格の定量基準が定義されコンソールに表示される

---

### 🔲 P12: リアルタイム配信 + 高度インフラ (T24)

**目的**: Massive WebSocket による real-time 価格でコンソールと exit 判断を強化する

**前提**: Massive API REST 運用が安定した後

| サブタスク | 内容 | 優先度 | 依存 |
|---|---|---|---|
| P12-A | `MassiveWebSocketClient` — 接続・認証・subscribe・再接続 | 中 | なし |
| P12-B | Console 統合 — real-time 価格表示・unrealized PnL live update | 中 | P12-A |
| P12-C | Trading system 統合 — intraday exit signal に real-time data を使用 | 中 | P12-A |

**完了条件**
- [ ] WebSocket client が stable（reconnection 含む）
- [ ] Console で real-time prices 表示
- [ ] Intraday exit signal が real-time data を参照している

---

### 🔲 P13: ML シグナル分類器 + 戦略進化（長期）

**目的**: データ蓄積後に機械学習で signal quality を予測し、Sharpe・Win rate を大幅改善する

**前提**: P8 完了 + 1000 件以上のラベル済みシグナル（2〜3ヶ月のデータ）

| サブタスク | 内容 | 優先度 | 依存 |
|---|---|---|---|
| P13-A | XGBoost シグナル品質分類器（momentum / ATR / sector / regime を入力、勝敗を予測） | 低 | 1000件+ data |
| P13-B | Regime-adaptive 戦略（Bull/Neutral/Bear でパラメータ自動切替） | 低 | P8 |
| P13-C | Kelly Criterion ポジションサイジング最適化 | 低 | P13-A |
| P13-D | 統計的裁定（cointegrated pairs の mean-reversion） | 低 | なし |

**完了条件**
- [ ] シグナル分類器の精度が 60%+ を達成
- [ ] Regime 切替が自動で動作し、Sharpe が改善
- [ ] Kelly sizing が paper_demo で適用されている

---

## フェーズロードマップ（2026年6月〜）

```
2026-06  P5 ✅ → P6（CF-2/3 + Risk Budget）
2026-07  P7（反実仮想 + T26 Exit 高度化）, P9（Corporate Action）
         P8（Signal Strength 粒度化）並行
2026-08  P10（ニュース感情 Step 1 評価 → 実装）
         P11（Analytics Batch 2 + 可視化）並行
2026-09  P12（Massive WebSocket）
2026-10+ P13（ML 分類器・長期戦略進化）
```

---

## 優先順位まとめ（2026-05-28 更新）

### 今週中
1. **T15 / T20 / T23**: 平日 cron の安定完走監視を継続
2. **Risk Budget 閾値チューニング**: 現在 open risk 6.6%（ポリシー上限 3% の 2.2 倍）→ 実態に合った上限値を検討。deny ロジックを paper_demo に組み込む前に必須

### 2〜3週間後（〜6/15）
3. **T25 Step 1**: analyze_news_impact.py で株式 44 銘柄の感情相関評価

### Step 1 通過後（順次）
4. **T25 Step 2**: ETF ニュースマッピング追加
5. **T25 Step 3**: NewsFeature 実装・paper_demo 組み込み
6. **T24**: Massive WebSocket 実装（Phase 2）

### Analytics Batch 2（並行対応可）
7. **反実仮想検証（Counterfactual Hold Analysis）**: 短期クローズされた負けトレードを仮に保有し続けた場合の損益を推計し、「短期カットが損失の原因か／生存バイアスか」を定量評価する（P1 — T26 の前提条件）
8. **T26 Exit戦略の高度化（一時的下落 vs トレンド崩壊の区別）**: 反実仮想検証の結果を受けて実施。MA20確認＋連続ウィンドウを優先実装（P1）
9. **S1. `entry_signal_strength` を trade レコードに保存** — 実績 vs 強度分析の前提（P1）
10. **S2. シグナル強度の粒度化** — breakout_momentum 一律 1.0 問題を解消し、0.5〜1.0 の広い分布に（P2）
11. **S3. 動的 cap 閾値再評価** — S2 完了後、実績データで 0.85 閾値の適切性を検証（P2）
12. **S4. 強度 vs パフォーマンス分析** — 分布別勝率・PF で閾値を根拠に定める（P2）
13. **Entry Quality Scoring**: buy 候補のエントリー品質スコアリング（P2）
14. **ETF Strategy Separation**: ETF 専用戦略・独立メトリクス（P2）
15. **Paper Trade Audit Trail**: 全 buy/sell/deny の外部監査可能な記録（P2）
16. **Backtest vs Paper Drift Monitor**: ライブ挙動とバックテスト想定の乖離検出（P2）
17. **Benchmark Attribution Maintenance**: SPY benchmark 更新の定期化とβ表示確認（P2）
18. **Capital Heatmap**: セクター・銘柄・資産クラス別集中リスク可視化（P3）
19. **Promotion Gate**: ペーパーデモ卒業基準の定義・コンソール表示（P3）
