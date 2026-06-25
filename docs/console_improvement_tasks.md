# stock_swing 改善計画（R0-R8 改訂版）

**改訂日**: 2026-06-25  
**改訂理由**: 外部 AI レビューに基づきゼロベースで再構成。旧 P0-P17 番号体系を廃止し R0-R8 に統一。

---

## 運用ステータス（2026-06-25 現在）

| 項目 | 値 |
|---|---|
| 元本 | $1,000,000 |
| 確定実現 PnL | +$25,578 |
| 現在 equity（確定分） | $1,028,250 |
| 含み益（推定） | +$60,150 |
| 全体 PF | 1.180（ETF: 2.270 / 個別株: 0.777） |
| 勝率 | 50.8%（99W / 95L） |
| 稼働 cron | 12本 全 consecutiveErrors=0 |
| テスト | 475 passed / 1 known fail |

---

## 完了フェーズ（歴史的記録）

旧 P0-P9 として実装された内容の要約。詳細は git log を参照。

| フェーズ | 完了日 | 内容 |
|---|---|---|
| P0 | 2026-05-28 | ETF buy guardrail / peak_price 永続化 / risk budget warn-block / qty contract |
| P1 | 2026-05-28 | strategy_attribution / data_quality_audit / risk_budget / exit_replay |
| P2 | 2026-05-28 | atomic JSON / TTL キャッシュ / ThreadingHTTPServer |
| P3 | 2026-05-27 | breakeven stop / trailing stop / entry強度連動 exit 閾値 / exit_reason 追跡 |
| P4 | 2026-06-23 | walk-forward exit validation / correlation cluster cap / structured console summary / staged AI context packs |
| P5 | 2026-06-23 | secret_scan CI / entry_signal_strength save 開始 |
| P6 | 2026-06-25 | ExperimentContext/Registry / PromptRegistry / FeatureSnapshotStore / BucketAssigner / Experiment Performance Reporter |
| P9 | 2026-06-25 | GuardrailEngine / CircuitBreakerStore / pre_trade_check / flatten_plan / report_guardrails |

### ⚠️ 実装済み・未接続モジュール

以下は**コードは完成しているが paper_demo に呼び出し箇所がない**：

| モジュール | 場所 | 接続すべき箇所 |
|---|---|---|
| ExperimentContext | `src/stock_swing/experiments/` | paper_demo 起動時・決定ファイル・注文・fill |
| GuardrailEngine | `src/stock_swing/guardrails/rule_engine.py` | startup / AI前 / buy前 / run後 |
| CircuitBreakerStore | `src/stock_swing/guardrails/circuit_breaker.py` | startup でロード、run後で保存 |
| pre_trade_check.py | `src/stock_swing/guardrails/pre_trade_check.py` | paper_demo の各ガードポイント |

---

## 改訂ロードマップ（R0-R8）

外部 AI レビューの推奨順序に従う。exit 戦略の閾値変更・ML は後段に置く。

---

### 🔴 R0: 安全モジュール統合ゲート（最優先・即実施）

**目的**: 実装済みの P6/P9 モジュールを実際の paper_demo ループに接続する  
**背景**: モジュールが存在するだけでは guardrail も実験追跡も機能しない

#### R0-A: ExperimentContext の paper_demo 接続

**作業**
- [ ] `paper_demo.py` 起動時に `build_experiment_context()` を呼び出す
- [ ] `ExperimentRegistry.register()` で run ごとのマニフェストを保存
- [ ] 全決定オブジェクトに `experiment_id` / `run_id` / `config_hash` / `prompt_hash` を付与
- [ ] 注文・fill・レポートにも `experiment_id` を伝搬
- [ ] `config/experiments/default_experiment.yaml` を実際の設定値と合わせる

**完了条件**
- [ ] paper_demo が `data/experiments/<experiment_id>/manifest.json` を生成する
- [ ] 決定ファイルに `experiment_id` フィールドが含まれる

---

#### R0-B: GuardrailEngine + CircuitBreaker の paper_demo 接続

**作業**
- [ ] **startup**: `pre_trade_check.check_startup(breaker_store)` → is_halted なら buy を全スキップ
- [ ] **AI前**: `should_skip_ai(breaker_state, guard_decision)` → True なら AI コール省略・deny として記録
- [ ] **buy 候補選別**: `apply_to_buy_candidate()` を全候補に適用
- [ ] **run 後**: `post_run_update(metrics, guard_engine, breaker_store)` でメトリクス評価・state 更新

**接続するメトリクス（最小セット）**
```yaml
stale_price_event_count:       # 当 run の stale price 発生件数
broker_tracker_mismatch_count: # reconcile 後の mismatch 件数
daily_realized_loss_pct:       # 当日の確定損失 %
api_error_rate_pct:            # AI API エラー率
order_rejection_rate_pct:      # 注文拒否率
consecutive_losing_trades:     # 直近連続負けトレード数
```

- [ ] `config/guardrails/autonomous_stop.yaml` の閾値を paper-only に合わせて調整
  - 最初は**警告のみ**（block/halt はログだけ）→ 2週間の実績確認後に有効化

**完了条件**
- [ ] paper_demo run で `data/guardrails/circuit_breaker.json` が更新される
- [ ] 強制 halt 時に buy 注文が送信されない
- [ ] ai_pause 時に AI が呼び出されない
- [ ] block_buys 時に buy が deny されるが reconciliation とレポートは続行

---

#### R0-C: YAML 閾値のペーパー検証期間（warning_only モード）

**作業**
- [ ] `config/guardrails/autonomous_stop.yaml` に `paper_warning_only: true` フラグを追加
- [ ] GuardrailEngine に warning_only モード実装（GuardAction.allow を強制返却するが警告ログを出す）
- [ ] 1〜2週間の警告ログから実際のトリガー頻度を確認し閾値を調整
- [ ] 閾値の根拠を `docs/runbooks/guardrail_calibration.md` に記録

**R0 全体の受け入れ基準**
- paper_demo run がすべての関連アーティファクトに `experiment_id` と `run_id` を持つ
- halt / ai_pause / block_buys の強制テストが通る
- `report_guardrails.py` でコンソールから状態を確認できる

---

### 🔴 R1: Exit Attribution 修復（最優先・即実施）

**目的**: 全 195 件 `exit_reason=broker_fill` の根本原因を特定・修復する  
**重要**: exit 戦略の閾値変更は R1 が解決するまで凍結する

#### まず根本原因を判定する（4仮説）

| ケース | 仮説 | 確認方法 |
|---|---|---|
| Case A | SimpleExitV2 の exit シグナルが一度も発火していない | ログに exit signal 出力があるか確認 |
| Case B | シグナルは発火しているが reason メタデータが注文前に失われる | pending_exit_reasons.json と order の照合 |
| Case C | sell が SimpleExit 以外（手動 or reconcile）から送信されている | 注文の origin を確認 |
| Case D | reconcile_orders が close 時に original reason を上書きしている | reconcile コードパスを確認 |

---

#### R1-A: Exit シグナル発火確認

**作業**
- [ ] `paper_demo` 実行時に exit シグナルの発火をログ出力（`exit_check: symbol=X signal=Y fired=True/False`）
- [ ] `SimpleExitV2Strategy` が sell を推奨するたびに `pending_exit_reasons.json` に書き込まれているか確認
- [ ] 直近 paper_demo ログと `pending_exit_reasons.json` を照合

**完了条件**
- [ ] exit シグナル発火の有無が明確になる（Case A〜D のどれかを特定）

---

#### R1-B: Exit Reason ライフサイクル修復

**作業**
- [ ] 売り注文送信前に `exit_event` を `trade_event_store` に記録
  ```
  trade_event(kind=exit_signal, symbol=X, order_id=Y, exit_reason=Z, source=SimpleExitV2)
  ```
- [ ] `pending_exit_reasons.json` に `order_id / client_order_id` を key として保存
- [ ] `reconcile_orders` で fill 確認時に `pending_exit_reasons` から理由を引き継ぐ
- [ ] `record_exit()` が reason を必須パラメータとして受け取るよう変更（デフォルト `broker_fill_unknown`）

**完了条件**
- [ ] SimpleExit が生成した sell のクローズで `exit_reason` が `signal_stop` / `signal_breakeven` / `signal_trailing` になる
- [ ] SimpleExit 以外からのクローズは `broker_fill_unknown` になる

---

#### R1-C: Exit Reason 分類レポート

**作業**
- [ ] `scripts/report_exit_attribution.py` を作成
  - `signal_stop` / `signal_breakeven` / `signal_trailing` / `broker_fill_unknown` / `reconstructed` の件数を表示
- [ ] `attribution_completeness = (known_reason / total_closed) × 100` を計算
- [ ] 目標: **attribution completeness >= 95%**

**完了条件**
- [ ] レポートが exit reason 別の件数・PF・勝率を表示する
- [ ] `broker_fill` が消え、意味のある reason で分類される

---

#### R1-D: Exit 戦略 E2E テスト

**作業**
- [ ] `test_exit_reason_survives_to_closed_trade.py`：SimpleExitV2 sell シグナル → closed trade に reason が残るまでの E2E テスト
- [ ] reconcile_orders が fill 時に pending_exit_reasons から reason を引き継ぐテスト
- [ ] unknown origin の fill が `broker_fill_unknown` になるテスト

**R1 全体の受け入れ基準**
- `exit_reason=broker_fill` が消え、意味のある分類に置き換わる
- attribution completeness >= 95%
- SimpleExit 発火 / 非発火 / reconcile 起因のクローズが区別可能
- exit_reason 別の PF 計算が可能になる

---

### 🟠 R2: ETF vs 個別株 戦略分離（高優先）

**目的**: ETF PF=2.270 vs 個別株 PF=0.777 の混在を解消し、戦略・予算・レポートを分離する

**現在のデータ**
```
ETF:   72 trades / +$48,733 / PF 2.270 / WR 62%
個別株: 123 trades / -$23,156 / PF 0.777 / WR 44%
```

---

#### R2-A: asset_class フィールドの付与

**作業**
- [ ] 全決定・注文・trade レコードに `asset_class: etf | stock | unknown` を追加
- [ ] `ETF_SYMBOLS` 定義を一元管理（現在分散している可能性あり）
- [ ] `rebuild_pnl_state_from_broker.py` が過去トレードに `asset_class` を付与できるよう更新

**完了条件**
- [ ] 全 closed trade に `asset_class` が入っている
- [ ] `unknown` がゼロになる

---

#### R2-B: ETF・個別株 別メトリクスの必須化

**作業**
- [ ] `strategy_attribution.py` / コンソールの全 PF / 勝率 / expectancy をデフォルト分離表示
- [ ] 全体 PF 単独表示を廃止し「ETF PF / Stock PF」を主指標にする
- [ ] コンソールの概要パネルに ETF/Stock 別 PF を常時表示

**完了条件**
- [ ] 全レポートが ETF と個別株を別々に表示する

---

#### R2-C: 個別株サイズ削減（暫定対策）

**作業**
- [ ] 個別株の `size_multiplier` を 0.5 に設定（ETF は 1.0 維持）
- [ ] 環境変数 `STOCK_SIZE_MULTIPLIER=0.5` または YAML で設定可能にする
- [ ] R1 で attribution_completeness >= 95% かつ attribution 済み stock trades >= 20件 蓄積後に再評価

**暫定基準**
- ETF: フルサイズ継続（PF=2.270 実績あり）
- 個別株: 0.5x サイズ（PF 回復まで）

---

#### R2-D: 個別株エントリーフィルター強化

以下を個別株のみに追加チェック（ETF は不要）:
- [ ] `min_volume_threshold`: 流動性フィルター
- [ ] `max_adr_pct`: ギャップリスク（Average Daily Range）
- [ ] `stock_rolling_pf_gate`: 過去 N 件の rolling PF が閾値未満なら deny

**R2 全体の受け入れ基準**
- コンソール・レポートが常に ETF/Stock 別指標を表示する
- 個別株 drawdown が ETF 利益を侵食しても即座に気づける
- 個別株の昇格基準（R5 参照）が定義されている

---

### 🟠 R3: 反実仮想検証（高優先・R1 着手後）

**目的**: 短期クローズが本当に損失の原因か、生存バイアスかを定量評価する  
**重要**: 結果が出るまで exit 戦略の閾値変更は行わない

**現在の観察値（要注意）**
```
< 1日:  n=84  avg -$363  WR 43%
1-3日:  n=6   avg -$620  WR 50%
3-7日:  n=40  avg -$1,799 WR 15%
7-14日: n=28  avg +$988  WR 71%
> 14日: n=37  avg +$2,813 WR 92%
```

---

#### R3-A: 反実仮想保有シミュレーション

**作業**
- [ ] `scripts/counterfactual_hold_analysis.py` を作成
  - 各 closed loser について仮想的に +1/+3/+5/+10 営業日保有した場合の損益を推計
  - 価格データは Massive API / price_overrides から取得
- [ ] 生存バイアス補正: winner についても「もし早期にカットしていたら」を推計
- [ ] ETF / 個別株 で別集計
- [ ] entry_signal_strength 別集計（データが溜まったら）

**完了条件**
- [ ] 「短期カットを避けた場合の期待値改善 or 悪化」が数値で示される
- [ ] ETF / 個別株 で別の結論が出ている

---

#### R3-B: Exit 戦略改善案の評価

反実仮想検証の結果を踏まえて比較評価する（`exit_replay.py` の拡張）：

| アプローチ | 内容 | 工数 |
|---|---|---|
| A: 連続確認ウィンドウ | N 日連続で stop ライン割れでカット | 小 |
| B: MA20 割り込み確認 | MA20 割れ + return<-5% + 2 日継続 | 中 |
| C: ATR ベース動的ストップ | ボラ連動でストップ幅を自動調整 | 中 |

**作業**
- [ ] `exit_replay.py` にアプローチ A/B/C を追加実装
- [ ] walk-forward validation で現行ポリシーと比較
- [ ] 採用基準: 反実仮想で有効性確認 + E2E テスト通過 の両方

**R3 全体の受け入れ基準**
- 「短期クローズ = 損失の原因」か「生存バイアス」かが定量的に判定されている
- exit 戦略の変更が根拠あるデータに基づいている
- R1 の attribution_completeness >= 95% が達成済みである

---

### 🟠 R4: Signal Strength 飽和修復（高優先）

**目的**: 73% が `strength=1.0` の状態を解消し、強度フィルタを機能させる

**現在の問題**
```
BUY シグナルの 73% が strength=1.0
閾値 0.85 が BUY の 86% を包含 → 識別力ゼロ
```

---

#### R4-A: 飽和原因の調査

**作業**
- [ ] `breakout_momentum_strategy.py` の strength 算出ロジックを確認
- [ ] 一律 1.0 になる原因（ハードコード・サブコンポーネント未実装・スケーリング不足）を特定
- [ ] 調査結果を `docs/signal_strength_saturation_root_cause.md` に記録

---

#### R4-B: サブコンポーネント追加

以下のサブスコアを組み合わせて 0.0〜1.0 の連続値を生成する：

| サブコンポーネント | 計算方法 | 重み案 |
|---|---|---|
| momentum_quality | 移動平均乖離率・モメンタム強度 | 0.30 |
| volume_confirmation | 出来高が N 日平均の X 倍 | 0.20 |
| volatility_penalty | ATR 過大 → 減点 | 0.20 |
| trend_alignment | MA20/MA50 の方向性一致 | 0.15 |
| regime_alignment | 現在の市場レジームとの整合 | 0.15 |

**作業**
- [ ] 各サブコンポーネントを実装
- [ ] ETF と個別株でウェイトを別々に設定可能にする
- [ ] 強度分布ヒストグラムをコンソールに表示

---

#### R4-C: 強度別パフォーマンス計測

**作業**
- [ ] デサイル（0.0-0.1, ..., 0.9-1.0）別に PF・勝率を計測
- [ ] 十分なサンプル（各デサイル n>=20）が溜まるまで強度によるハードフィルターをかけない
- [ ] `scripts/report_signal_strength_distribution.py` で表示

**R4 全体の受け入れ基準**
- strength=1.0 比率が 73% から 30% 以下に改善する
- 閾値 0.85 が BUY の 50% 以下を包含する（識別力が生まれる）
- ETF / 個別株 別の強度分布が確認できる

---

### 🟡 R5: ポートフォリオ配分 + 昇格・降格ゲート（中〜高優先）

**目的**: 資本配分を戦略品質に基づいて管理し、ペーパーデモ卒業基準を定義する  
**前提**: R2（ETF/Stock 分離）と R4（strength 修復）が完了した後に本格化

---

#### R5-A: 戦略・資産クラス別資本予算

**作業**
- [ ] ETF 戦略・個別株戦略 別の資本上限を YAML で設定
- [ ] 各戦略の drawdown が上限を超えたらサイズを自動縮小
- [ ] 利益保護ルール: 月次 PnL が +X% を超えたら翌月の最大エクスポージャーを制限

---

#### R5-B: 昇格ゲート（Promotion Gate）

**ペーパーデモ卒業 or サイズ増加の基準**

```
サンプル:
  - 戦略レベル昇格: closed trades >= 50件
  - ETF のみ暫定チューニング: >= 20件

パフォーマンス:
  - 全体 PF >= 1.20
  - 直近 rolling window PF >= 1.10
  - max drawdown が設定上限内
  - unresolved broker/tracker mismatch がゼロ
  - exit attribution completeness >= 95%

運用:
  - guardrails がアクティブ（R0 完了済み）
  - experiment_id が全 run に付与されている
  - critical console alert がゼロ
```

**作業**
- [ ] `scripts/check_promotion_gate.py` を作成（全条件を自動チェック）
- [ ] コンソールに Promotion Gate パネルを追加
- [ ] ETF・個別株の昇格基準を別々に定義

---

#### R5-C: 降格・ロールバックゲート

**作業**
- [ ] 直近 rolling window PF < 0.85 が N 回連続 → サイズを自動縮小
- [ ] mismatch が閾値超 → 即座にサイズをゼロに → 手動承認で復帰
- [ ] `config/guardrails/autonomous_stop.yaml` に rollback ルールを追加

**R5 全体の受け入れ基準**
- 昇格基準が文書化され `check_promotion_gate.py` で自動確認できる
- どの戦略も静かに全資本を消費できない
- ETF と個別株の昇格基準が独立している

---

### 🟡 R6: コンソール・リモート監視（中〜高優先）

**目的**: コンソールを運用判断に使えるツールにする

**設計原則**
- リモートアクセスは**読み取り専用**（buy/sell/cancel/reset の遠隔操作は実装しない）
- トークン認証のみでアクセス可能
- 口座残高は概算のみ表示、API キーは非表示

---

#### R6-A: Run Health パネル

- [ ] guardrail 状態（OK / DEGRADED / HALTED）を常時表示
- [ ] 直近 paper_demo / reconcile の実行時間・ステータス
- [ ] exit attribution completeness %
- [ ] experiment_id がアクティブかどうか

#### R6-B: Price Integrity パネル

- [ ] stale price 発生件数（過去 24h）
- [ ] price override が適用されているシンボル一覧
- [ ] broker/tracker 価格乖離が 5% 超のシンボル一覧

#### R6-C: Token / API モニター

- [ ] 当日の AI API 呼び出し数・コスト・エラー率
- [ ] context_pack 使用分布（minimal/normal/expanded/emergency）
- [ ] ai_pause 発生回数とその理由

#### R6-D: Decision Funnel パネル

- [ ] `scanned → candidates → ai_evaluated → buy / deny / hold` の各段階の件数
- [ ] deny 理由の分布
- [ ] 当日の submission / fill / open order 数

#### R6-E: Attribution パネル（R1/R4 完了後に有効化）

- [ ] ETF / Stock 別 PF・勝率をリアルタイム表示
- [ ] exit_reason 別 件数・PF
- [ ] signal_strength デサイル別 PF

#### R6-F: リモート読み取り専用アクセス

- [ ] `/api/status` エンドポイント（JSON）
- [ ] トークン認証の実装
- [ ] レート制限（1分間 10 req 以下）

**R6 全体の受け入れ基準**
- system が OK/DEGRADED/HALTED のどれかが即座にわかる
- 価格異常・broker 乖離が即座に見える
- スマートフォンから読み取り専用でアクセスできる

---

### 🟢 R7: 運用エッジケース・データ品質（中優先）

**目的**: 実世界の市場イベントがシステムを静かに破壊しないようにする

#### R7-A: Corporate Action 対応（KLAC 10-for-1 split 経験済み）

**作業**
- [ ] `corporate_actions` 台帳の追加（symbol / action_type / factor / effective_at / source）
- [ ] open position に split 適用（qty / entry_price / peak_price / stop_price を自動変換）
- [ ] closed trade の前後跨ぎ split 正規化
- [ ] `rebuild_pnl_state` / `audit` / reconciliation を corporate action 優先に変更
- [ ] split 検知時の runbook + KLAC ケース回帰テスト

**完了条件**
- [ ] split 発生銘柄で tracker/broker/audit の整合が手補正なしで保たれる

---

#### R7-B: WebSocket リアルタイム価格（検討段階）

**外部レビューの見解**: スイングトレードには必須ではないが intraday exit 保護に有効

**前提**: PriceResolver の stale 検知が安定してから実装する

- [ ] `MassiveWebSocketClient` の設計（接続・認証・subscribe・再接続）

---

#### R7-C: ニュース感情フィーチャー（評価段階）

**前提条件**: 歴史分析で有意な相関（|r|>0.3, n>=30）が確認されてから実装

- [ ] Step 1: `analyze_news_impact.py` で相関確認（2026-06-15 目安でデータ蓄積中）
- [ ] Step 2: ETF_SECTOR_MAP で ETF のセンチメントを構成株の加重平均で近似
- [ ] Step 3: 相関確認後のみ `news_sentiment_feature.py` を実装

**R7 全体の受け入れ基準**
- split 発生時に手補正なしで整合が保たれる
- WebSocket は PriceResolver が安定してから追加される
- ニュース感情は有効性が確認されてから実装される

---

### 🔵 R8: ML 予測（長期・急がない）

**目的**: クリーンなラベルが十分に蓄積された後に ML を導入する  
**重要**: ML が guardrail や価格整合性チェックをバイパスしないこと

**前提条件（すべて必須）**
```
✓ exit_reason attribution が修復済み（R1 完了）
✓ strategy_id が正確（R0 完了）
✓ entry_signal_strength が修復済み（R4 完了）
✓ deny / missed opportunity のアウトカムが記録されている
✓ experiment_id / run_id が全 run に付与済み（R0 完了）
✓ クリーンラベル >= 1,000 件
```

**タスク（前提条件充足後）**
- [ ] R8-A: 期待リターンデータセットの構築
- [ ] R8-B: Confidence calibration
- [ ] R8-C: Buy 候補の meta-labeling
- [ ] R8-D: Exit タイミングアドバイザリーモデル
- [ ] R8-E: Regime-adaptive 戦略選択

**R8 の受け入れ基準**
- ML はシャドウモードで先行実行される
- guardrail や価格整合性チェックをバイパスできない
- A/B または walk-forward の証拠で昇格が評価される

---

## 次の 10 ステップ（推奨実施順）

```
 1. R0-A: ExperimentContext を paper_demo に接続
 2. R0-B: GuardrailEngine / CircuitBreaker を paper_demo に接続
 3. R0-C: YAML 閾値を warning_only モードで 2 週間検証
 4. R1-A: exit シグナル発火確認（ログ追加）
 5. R1-B: exit_reason ライフサイクル修復（pending_exit_reasons + reconcile 連携）
 6. R2-A: asset_class フィールド付与 + ETF/Stock 別レポート必須化
 7. R2-C: 個別株 size_multiplier = 0.5 を暫定適用
 8. R6-A/B: Run Health / Price Integrity パネル追加（読み取り専用）
 9. R3-A: 反実仮想保有シミュレーションスクリプト作成
10. R4-A: signal_strength 飽和の根本原因調査
```

---

## やらないこと（制約）

外部 AI レビューで強調された禁止事項：

```
❌ exit attribution が修復されるまで exit 閾値を変更しない（R1 完了まで凍結）
❌ クリーンラベルが 1,000 件に達するまで ML を実行に影響させない
❌ ETF と個別株を 1 つの混合戦略として扱わない
❌ スマートフォンから遠隔 buy/sell/cancel/reset を実装しない（読み取り専用のみ）
❌ YAML 閾値が paper 検証されるまで guardrail を hard-halt として有効化しない
❌ 反実仮想分析で生存バイアスを制御するまで「短期保有 = 有害」と結論づけない
```

---

## フェーズロードマップ（2026年）

```
2026-06 後半  R0（P6/P9 接続）, R1（exit attribution 修復）
2026-07       R2（ETF/Stock 分離）, R6（コンソール拡充）
              R3（反実仮想） ← R1 完了次第
2026-08       R4（Signal Strength 修復）, R5（昇格ゲート定義）
2026-09       R7（Corporate Action, WebSocket 検討, ニュース感情評価）
2026-10+      R8（ML: クリーンラベル 1,000 件到達後）
```

---

## 優先順位まとめ（2026-06-25 改訂）

| 優先度 | フェーズ | 理由 |
|---|---|---|
| 🔴 即実施 | R0 | 実装済みモジュールが眠っている。接続するだけで機能する |
| 🔴 即実施 | R1 | exit attribution なしに exit 戦略は評価不能。閾値変更も不可 |
| 🟠 高 | R2 | ETF/株の混在が全指標を歪めている。暫定サイズ削減は即適用可 |
| 🟠 高（R1後） | R3 | exit 変更の根拠データを得る。生存バイアスの排除が先 |
| 🟠 高 | R4 | signal_strength が識別力ゼロのまま。強度フィルターが機能していない |
| 🟡 中〜高 | R5 | R2/R4 の指標が揃った後に昇格基準を定義 |
| 🟡 中〜高 | R6 | 読み取り専用コンソールは低リスクで即効性あり |
| 🟢 中 | R7 | Corporate Action は次の split まで猶予あり |
| 🔵 長期 | R8 | 前提条件（クリーンラベル 1,000 件）が揃ってから |
