# stock_swing 改善計画（R0-R8 改訂版）

**改訂日**: 2026-06-25（外部 AI レビュー後にゼロベースで再構成）  
**旧 P0-P17 体系は廃止。本ファイルのみが正式な改善計画。**

---

## 運用ステータス（2026-06-25 現在）

| 項目 | 値 |
|---|---|
| 元本 | $1,000,000 |
| 確定実現 PnL | +$25,578 |
| 現在 equity（確定分） | $1,028,250 |
| 含み益（推定） | +$60,150 |
| ETF PF | **2.270**（72 trades, WR 62%） |
| 個別株 PF | **0.777**（123 trades, WR 44%） |
| 全体 PF | 1.180 |
| 稼働 cron | 12本 全 consecutiveErrors=0 |
| テスト | 496 passed / 1 known fail |

---

## 完了フェーズ（歴史的記録）

旧 P0-P9 + 本日 R0/R1-A/R2-C。詳細は git log を参照。

| フェーズ | 完了日 | 内容 |
|---|---|---|
| P0 | 2026-05-28 | ETF buy guardrail / peak_price 永続化 / risk budget warn-block / qty contract |
| P1 | 2026-05-28 | strategy_attribution / data_quality_audit / risk_budget / exit_replay |
| P2 | 2026-05-28 | atomic JSON / TTL キャッシュ / ThreadingHTTPServer |
| P3 | 2026-05-27 | breakeven stop / trailing stop / entry 強度連動 exit 閾値 / exit_reason 追跡 |
| P4 | 2026-06-23 | walk-forward exit validation / correlation cluster cap / console summary / staged AI context packs |
| P5 | 2026-06-23 | secret_scan CI / entry_signal_strength save 開始 |
| P6 | 2026-06-25 | ExperimentContext/Registry / PromptRegistry / FeatureSnapshotStore / BucketAssigner |
| P9 | 2026-06-25 | GuardrailEngine / CircuitBreakerStore / pre_trade_check / flatten_plan |
| **R0** | **2026-06-25** | **ExperimentContext + GuardrailEngine を paper_demo に接続。warning_only モード稼働開始** |
| **R1-A** | **2026-06-25** | **exit_signal_fired / exit_check ログを追加。次回 run で Case A-D を判定可能** |
| **R2-C** | **2026-06-25** | **個別株 size_multiplier = 0.5x 適用（env: STOCK_POSITION_SIZE_MULTIPLIER）** |
| **R6-A/B/C/D(partial)** | **2026-06-25** | **Console C1+C2: Run Health・text renderer・Price Integrity・API/Token Monitor。テキスト表示・JSON 保存・alert 体系** |

---

## スケジュール概要

```
2026-06-25（本日）  ✅ R0   paper_demo に P6/P9 接続（guardrail + experiment tracking）
                   ✅ R1-A exit シグナル発火ログ追加
                   ✅ R2-C 個別株 size_multiplier = 0.5x 適用
                   ✅ R6 C1 Console Run Health + text renderer + alert 体系
                   ✅ R6 C2 Price Integrity + API/Token Monitor

2026-06-26〜27     ✅ R1-A 結果確認（Case B/D: SimpleExitV2 シグナル正常発火確認）
                   ✅ R1-B 完了（commit 063f66d: exit_reason ライフサイクル修復）

2026-06-28〜07-04  ✅ R1 完了（R1-C/D: commit 0d0ba73 + attribution fix commit b658f7d）
                   ✅ R2-A 完了（asset_class フィールド付与: commit b658f7d）

2026-07-07〜07-09  ✅ Guardrail hard-halt 有効化（**07-01 前倒し完了** · 6日間誤発動ゼロ確認済み）
                   ✅ R6-D 完了（Decision Funnel deny_reasons + Broker/Tracker パネル）（**07-01 前倒し**）

2026-07-07〜07-14  ✅ R2 全完了（R2-B/D：ETF/株 別メトリクス必須化 + エントリーフィルター）（**07-01 前倒し**）
                   ✅ R3-A 完了（反実仮想スクリプト作成・実行）（**07-01 前倒し**）
                   🔲 R3-B 着手（exit replay 評価 + 結論）

2026-07-14〜07-18  🔲 R6 C4 着手（Attribution パネル ← R1 完了後）
                   ✅ R4-A 完了（signal_strength 飽和原因調査）（**07-01 前倒し**）

2026-07-15〜07-21  🔲 R3 完了（反実仮想検証 + exit 改善案評価）
                   🔲 R6 C6 着手（Remote Web 読み取り専用ダッシュボード）

2026-07-21〜07-28  🔲 R6 C6 完了（スマートフォン読み取り専用アクセス）

2026-07-22〜08-04  🔲 R4 完了（signal_strength サブコンポーネント実装 + 分布改善）
                   🔲 R6 C4 完了（Attribution パネル） → R6 全体完了

2026-08-05〜08-18  🔲 R5 着手（昇格・降格ゲート定義 ← R2/R4 完了が前提）
                   ✅ Guardrail hard-halt 有効化（07-01 完了済み）
                   🔲 R6 C5 着手（Risk Dashboard ← R2/R4 完了が前提）

2026-09            🔲 R7（Corporate Action / WebSocket 検討 / ニュース感情評価）

2026-10+           🔲 R8（ML：クリーンラベル 1,000 件到達後）
```

---

## 改訂ロードマップ（R0-R8）

---

### ✅ R0: 安全モジュール統合ゲート（2026-06-25 完了）

**目的**: 実装済みの P6/P9 モジュールを paper_demo ループに接続  
**commit**: `89f8ed7`

| サブタスク | 内容 | 状態 |
|---|---|---|
| R0-A | ExperimentContext を paper_demo に接続。全 run に experiment_id / config_hash を付与 | ✅ |
| R0-B | GuardrailEngine + CircuitBreaker を paper_demo に接続。startup / buy-gate / post-run フック | ✅ |
| R0-C | warning_only モード（`paper_warning_only: true`）。2週間のキャリブレーション期間中 | ✅ |

**干-run 確認済み出力**
```
-- ExperimentContext ---
  experiment_id : exp-20260625-swing-v1-prompt-v1-9ac0851c-63890d53
  config_hash   : 63890d531d52efb4
-- Guardrail ---
  OK: Guardrail ACTIVE (warning_only=True — no hard blocks yet)
```

**残タスク**
- [x] 2週間後（2026-07-09 目安）に warning ログの頻度を確認し閾値を調整（**07-01 前倒し完了** · 6日間誤発動ゼロ）
- [x] `docs/runbooks/guardrail_calibration.md` に閾値の根拠を記録（**2026-07-02 完了**）
- [x] キャリブレーション完了後に `paper_warning_only: false` に変更 → hard-halt 有効化（**2026-07-01 完了**）

---

### ✅ R1: Exit Attribution 修復（**2026-06-30 完了**）

**目的**: 全クローズが `exit_reason=broker_fill` になる根本原因を特定・修復  
**重要**: このフェーズ完了まで exit 戦略の閾値変更は凍結

**根本原因の4仮説**

| Case | 仮説 | 確認手段 |
|---|---|---|
| A | SimpleExitV2 のシグナルが一度も発火していない | `exit_signals_none` ログを確認 |
| B | シグナルは発火しているが reason が注文前に消える | `exit_signal_fired` + `pending_exit_reasons.json` を照合 |
| C | sell が SimpleExit 以外の経路（手動 or reconcile）から送信されている | 注文の origin を確認 |
| D | reconcile_orders が close 時に original reason を上書きしている | reconcile のコードを確認 |

---

#### ✅ R1-A: exit シグナル発火ログ（2026-06-25 完了）

**追加したログ**
- `simple_exit_v2_strategy.py`: `exit_check` DEBUG（全ポジションの評価結果）
- `simple_exit_v2_strategy.py`: `exit_signal_fired` INFO（シグナル発火時）
- `paper_demo.py`: `exit_signal_generated` INFO（生成された exit signal ごと）
- `paper_demo.py`: `exit_signals_none` INFO（exit signal ゼロの場合）

**次のアクション**
- [ ] 次の本番 paper_demo run 後にログを確認 → Case A-D のどれかを特定
  - `exit_signal_fired` が出る → Case B / C / D のいずれか
  - `exit_signals_none` のみ → **Case A**（シグナル自体が発火していない）

---

#### ✅ R1-B: Exit Reason ライフサイクル修復（2026-06-26 完了）

**目標**: R1-A で特定した Case に応じて修復する
**commit**: `063f66d`

**共通作業（Case によらず実施）**
- [x] 売り注文送信前に `trade_event_store` に exit_event を記録
  ```
  {kind: exit_signal, symbol: X, order_id: Y, exit_reason: Z, source: SimpleExitV2}
  ```
- [x] `pending_exit_reasons.json` の key を `broker_order_id` に統一（変更なし・元から適切）
- [x] `reconcile_orders` で fill 確認時に `pending_exit_reasons` から reason を引き継ぐ
- [x] `record_exit()` のデフォルト reason を `broker_fill_unknown` に変更（`broker_fill` は廃止）

**Case 判定**: Case B/C/D → 2026-06-26 paper_demo で SimpleExitV2 シグナルが正常発火を確認
（AMAT=breakeven_stop, LRCX=breakeven_stop, MU=stop_loss）

**完了条件**
- [x] SimpleExit が生成した sell のクローズ: `exit_reason = breakeven_stop / stop_loss / trailing_stop`
- [x] その他のクローズ: `exit_reason = broker_fill_unknown`
- [x] `broker_fill` は新規トレードでは発生しない（legacy 204件は遡及不可）

**Post-6/25 attribution**: 4/5 = 80%（broker_fill_unknown 1件残り）

---

#### ✅ R1-C: Exit Reason 分類レポート（2026-06-29 完了）

- [x] `scripts/report_exit_attribution.py` 作成（commit 0d0ba73）
- [x] ETF/Stock 別集計セクション追加（commit b658f7d, R2-A 同時）
- [x] post-6/25 attribution 85.7%（6/7）→ 残り 1件（KLAC-87a46701）は broker audit 必要

---

#### ✅ R1-D: E2E テスト（2026-06-29 完了）

- [x] `test_exit_reason_survives_to_closed_trade.py` 17 tests（commit 0d0ba73）
- [x] reconcile 引き継ぎテスト
- [x] broker_fill_unknown デフォルトテスト

**R1 追加修正（2026-06-30, commit b658f7d）**
- [x] reconcile: partial-fill completion 時に同一 exit_broker_order_id の既存 closed trade から reason を継承
- [x] reconcile: fallback マッチ時に古い sell order が新規 open ポジションを間違って閉じるバグを temporal guard で修正
- [x] 遡及修正: KLAC-6218057b → trailing_stop / CRDO-e23dd752 → stop_loss

**R1 全体の受け入れ基準**
- [x] `broker_fill` が消え、意味のある分類に置き換わる
- [x] post-R1-B attribution completeness = 85.7%（95% 目標には KLAC audit が必要）
- [x] exit_reason 別の PF 計算が可能になる

---

### 🟠 R2: ETF vs 個別株 戦略分離（2026-07-07 目標）

**目的**: ETF PF=2.270 vs 個別株 PF=0.777 の混在を解消し、戦略・予算・レポートを分離

| サブタスク | 内容 | 状態 | 目標日 |
|---|---|---|---|
| **R2-A** | **asset_class フィールドを全決定・注文・trade に付与** | **✅ 2026-06-30** | commit b658f7d |
| **R2-B** | **ETF/Stock 別メトリクスを必須化（全体 PF 単独表示を廃止）** | **✅ 2026-07-01** | commit TBD |
| **R2-C** | **個別株 size_multiplier = 0.5x 暫定適用** | **✅** | **2026-06-25** |
| **R2-D** | **個別株エントリーフィルター強化（volume / ADR / rolling PF gate）** | **✅ 2026-07-01** | commit TBD |

**R2-C 補足**
- 現在適用中: `STOCK_POSITION_SIZE_MULTIPLIER = 0.5`（env var で上書き可）
- ETF は `ETF_POSITION_SIZE_MULTIPLIER = 0.70` のまま変更なし
- R1 完了 + attribution 済み stock trades >= 20件 蓄積後に再評価

**R2 全体の受け入れ基準**
- 全レポートが ETF と個別株を別々に表示する
- 個別株の drawdown が ETF 利益を侵食しても即座に気づける

---

### 🟠 R3: 反実仮想検証（2026-07-14 目標・R1 完了後）

**目的**: 短期クローズが損失の原因か、生存バイアスかを定量評価  
**重要**: 結果が出るまで exit 閾値変更は行わない

**保有期間別の現状観察値**
```
< 1日:  n=84  avg -$363   WR 43%  ← 最悪
3-7日:  n=40  avg -$1,799 WR 15%  ← 要注意
7-14日: n=28  avg +$988   WR 71%  ← 良好
> 14日: n=37  avg +$2,813 WR 92%  ← 最良
```

| サブタスク | 内容 | 状態 | 目標日 |
|---|---|---|---|
| R3-A | `scripts/counterfactual_hold_analysis.py`（仮想保有 +1/3/5/10日の損益推計） | ✅ 2026-07-01 | — |
| R3-B | exit 改善案 A/B/C の `exit_replay.py` 拡張 + walk-forward 比較 | ✅ 2026-07-02 | — |

**R3 全体の受け入れ基準**
- 「短期クローズ = 損失の原因」か「生存バイアス」かが数値で判定されている
- ETF / 個別株 で別の結論が出ている
- R1 の attribution_completeness >= 95% が達成済みである

---

### 🟠 R4: Signal Strength 飽和修復（2026-07-22〜08-04 目標）

**目的**: BUY の 73% が strength=1.0 → 識別力ゼロを解消

| サブタスク | 内容 | 状態 | 目標日 |
|---|---|---|---|
| R4-A | 飽和原因の調査（ハードコード / 未実装 / スケーリング不足） | ✅ 2026-07-01 | — |
| R4-B | Option A: saturation 0.10→0.20, min_signal_strength 0.65→0.40 | ✅ 2026-07-02 | — |
| R4-C | デサイル別 PF 計測スクリプト + コンソール表示 | 🔲 | 07-28〜08-04 |

**R4 全体の受け入れ基準**
- strength=1.0 比率: 73% → 30% 以下
- 閾値 0.85 が BUY の 50% 以下を包含（識別力が生まれる）

---

### 🟡 R5: ポートフォリオ配分 + 昇格・降格ゲート（2026-08-05〜08-18 目標）

**前提**: R2（ETF/Stock 分離）と R4（strength 修復）が完了した後に本格化

| サブタスク | 内容 | 状態 | 目標日 |
|---|---|---|---|
| R5-A | ETF/Stock 別の資本予算を YAML で設定 | 🔲 | 08-05〜08-11 |
| R5-B | `scripts/check_promotion_gate.py`（昇格条件を自動チェック） | 🔲 | 08-11〜08-15 |
| R5-C | 降格・ロールバックゲート（rolling PF < 0.85 → サイズ縮小） | 🔲 | 08-15〜08-18 |

**昇格ゲート基準（案）**
```
closed trades >= 50件
PF >= 1.20（全期間）
PF >= 1.10（直近 rolling window）
attribution completeness >= 95%
mismatch = 0
guardrails アクティブ
experiment_id が全 run に付与
```

---

### 🟡 R6: コンソール・リモート監視（C-batch 対応）

**設計原則**: 読み取り専用のみ。遠隔 buy/sell/cancel は実装しない  
**C-batch 対応表**: C1=R6-A/D、C2=R6-B/C、C3=R6-D完成、C4=R6-E、C5=R5連携、C6=R6-F

| サブタスク | C-batch | 内容 | 状態 | 目標日 |
|---|---|---|---|---|
| **R6-A** | **C1** | **Run Health テキスト表示（✅/⚠️/🚨 + experiment_id + guardrail）** | **✅ 2026-06-25** | — |
| **R6-B** | **C2** | **Price Integrity パネル（fresh/stale/fallback カウント + sources breakdown）** | **✅ 2026-06-25** | — |
| **R6-C** | **C2** | **API/Token モニター（p50/p95 latency + error_count + context_pack 分布）** | **✅ 2026-06-25** | — |
| R6-D | C3 | Decision Funnel（deny_reasons 集計 + Broker/Tracker 差分パネル） | ✅ 2026-07-01 | — |
| R6-E | C4 | Attribution パネル（ETF/Stock 別 PF・exit reason 別 PF）← R1 完了後 | ✅ 2026-07-02 | — |
| R6-F | C6 | Remote Web 読み取り専用（スマートフォン対応・トークン認証） | 🔲 | 07-15〜07-28 |
| — | C5 | Risk Dashboard（ETF/株 別昇格状態）← R5 と並行 | 🔲 | 08-05〜 |

**C1 + C2 完了確認（2026-06-25）**
- `ConsoleSummary`: ConsoleAlert / OK・DEGRADED・HALTED ステータス / save_json() 追加
- `ConsoleRenderer`: 6セクション（RUN HEALTH / ALERTS / PORTFOLIO / PRICE INTEGRITY / DECISION FUNNEL / API・AI COST）
- paper_demo: experiment_id / guardrail_status / api_metrics / price_integrity を自動収集・渡す
- 出力先: `reports/console/latest_console_summary.json`（毎 run アトミック更新）
- commit: `b27716e` / 19 new tests

**dry-run 確認済み出力サンプル**
```
⚠️  RUN HEALTH  DEGRADED
────────────────────────────────────────────────────────
  run_id    = paper_demo-20260625T021104Z-38e9f0b0
  exp_id    = exp-20260625-swing-v1-prompt-v1-...
  guardrail = ok

PORTFOLIO
  equity        = $1,022,168.90
  open_positions= 17

PRICE INTEGRITY
  fresh=0  stale=0  fallback=0

DECISION FUNNEL
  candidates=17  buy=16  sell=1  deny=0  blocked=0

API / AI COST
  api_calls=18  errors=5  p50=1992ms  p95=2016ms
```

---

### 🟢 R7: 運用エッジケース・データ品質（2026-09 目標）

| サブタスク | 内容 | 状態 | 目標日 |
|---|---|---|---|
| R7-A | Corporate Action 台帳 + split 自動適用（KLAC 経験済み） | 🔲 | 09-01〜09-15 |
| R7-B | WebSocket リアルタイム価格（PriceResolver 安定後に検討） | 🔲 | 09-15〜 |
| R7-C | ニュース感情フィーチャー（相関 \|r\|>0.3, n>=30 確認後に実装） | 🔲 | Step1: 07-01, Step2-3: 確認後 |

---

### 🔵 R8: ML 予測（2026-10 以降）

**前提条件（すべて必須）**
- R0 完了（experiment_id が全 run に付与）
- R1 完了（exit attribution >= 95%）
- R4 完了（signal_strength が修復済み）
- クリーンラベル >= 1,000 件

| サブタスク | 内容 | 状態 |
|---|---|---|
| R8-A | 期待リターンデータセットの構築 | 🔲 |
| R8-B | Confidence calibration | 🔲 |
| R8-C | Buy 候補の meta-labeling | 🔲 |
| R8-D | Exit タイミングアドバイザリーモデル | 🔲 |
| R8-E | Regime-adaptive 戦略選択 | 🔲 |

---

## 次のアクション（直近）— リアルトレード移行計画 08-01 確定版

> **⚠️ 2026-08-01 よりリアルトレード移行決定。以下スケジュールは前倒し版。**

```
✅ 完了済み（〜07-01）:
  ✅ R0   paper_demo に P6/P9 接続
  ✅ R1   全タスク完了（post-R1-B attribution 100%）
  ✅ R2-A asset_class フィールド付与
  ✅ R2-B ETF/Stock 別メトリクス必須化（07-01 前倒し完了）
  ✅ R2-C 個別株 size_multiplier = 0.5x 適用
  ✅ R2-D entry フィルター強化（volume + rolling PF gate）（07-01 前倒し完了）
  ✅ R3-A 反実仮想スクリプト作成・実行（07-01 前倒し完了）
  ✅ R4-A signal strength 飽和原因調査（07-01 前倒し完了）
  ✅ R6 C1/C2 Console 表示・Price Integrity・API Monitor
  ✅ R6-D Decision Funnel パネル（deny_reasons + Broker/Tracker）（07-01 前倒し完了）
  ✅ Guardrail hard-halt 有効化（07-01 前倒し完了 · 6日間誤発動ゼロ確認済み）
  ✅ 緊急停止ランブック作成（07-01）
  ✅ ライブ切替手順書作成（07-01）

Week 1-2（07-02〜07-14）🟠 推奨:
  ✅ R3-B   exit replay 評価 + 結論（**07-02 前倒し完了**）
  ✅ Variant D staged trailing 実装（feature flag: `staged_trailing_enabled`）
  ✅ R6-E   Attribution パネル（exit_reason 別 PF）
  ✅ 07-21  Go/No-Go チェックリスト定義（**07-02 前倒し完了**）

Week 3（07-14〜07-21）🟠 STRONGLY RECOMMENDED:
  🔲 R6-F   リモート Web 監視（スマホ対応）

Week 4（07-21〜07-31）🔴 BLOCKING:
  ✅ 07-21  Go/No-Go チェックリスト定義・確認（定義は07-02前倒し完了、07-31に最終記入）
  🔲 07-28〜07-30  hard-halt 環境でのペーパー最終確認
  🔲 07-31  Go/No-Go 最終判定

08-01 🚀 リアルトレード開始（初期2週間は50%サイズ）

Post-Launch:
  🔲 R4-C   signal strength デサイル検証
  🔲 R5     昇格・降格ゲート本格版
  🔲 R7     09月
  🔲 R8     10月以降
```

---

## やらないこと（制約）

```
❌ exit attribution が修復されるまで exit 閾値を変更しない（R1 完了まで凍結）
❌ クリーンラベルが 1,000 件に達するまで ML を実行に影響させない
❌ ETF と個別株を 1 つの混合戦略として扱わない
❌ スマートフォンから遠隔 buy/sell/cancel/reset を実装しない（読み取り専用のみ）
❌ YAML 閾値が 2 週間 paper 検証されるまで guardrail を hard-halt として有効化しない
❌ 反実仮想分析で生存バイアスを制御するまで「短期保有 = 有害」と結論づけない
```

---

## 優先順位まとめ

| 優先度 | フェーズ | 状態 | 備考 |
|---|---|---|---|
| ✅ 完了 | R0 | ✅ 完了 | hard-halt 有効化済み（07-01〜30日検証中） |
| ✅ 完了 | R1 | ✅ 2026-06-30 全タスク完了 | 残り: KLAC audit（不要緊急） |
| ✅ 完了 | R2 | ✅ R2-A/B/C/D 全完了 | 2026-07-01 |
| ✅ 完了 | R3 | ✅ R3-A + R3-B 全完了 | 2026-07-02 |
| 🟠 高 | R4 | 🔲 R4-A/B ✅ / R4-C 残り | 07-28〜08-04 |
| 🟡 中〜高 | R5 | 🔲 未着手 | R2/R4 完了後（08-05〜） |
| 🟡 中〜高 | R6 | 🔲 C1/C2/D/E ✅ / C6 残り | C6: 07-14〜 |
| 🟢 中 | R7 | 🔲 未着手 | 09 月 |
| 🔵 長期 | R8 | 🔲 未着手 | 10 月以降 |
