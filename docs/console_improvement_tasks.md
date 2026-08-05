# stock_swing 改善計画（R0-R8 改訂版）

**改訂日**: 2026-07-13（Codex Review G1-G10 対応 + min_hold 実装）  
**旧 P0-P17 体系は廃止。本ファイルのみが正式な改善計画。**

---

## 運用ステータス（2026-07-28 更新）

| 項目 | 値 |
|---|---|
| 元本 | $1,000,000 |
| 確定実現 PnL（公式） | **-$65,458.55**（reversed 7件 quarantine 後）|
| quarantined PnL（除外） | （100件）|
| ETF PF（clean records） | **1.258**（65 trades, WR 61.5%） |
| 個別株 PF（clean records） | **0.799**（134 trades, WR 43.3%） |
| 全体 PF（clean records） | **0.969**（199 trades）|
| clean closed | **199件**（54件を quarantine 分離済み）|
| attribution coverage | **100%**（RF-8b 完了）|
| circuit_breaker | **✅ ok**（07-13 解除・race condition 対策済み）|
| 稼働 cron | 12本 全 consecutiveErrors=0 |
| テスト | **676 passed** / 2 skipped |

**clean records 分析（F8 → RF-8b 完了後の最新値）**
```
 trailing_stop  : n=68  WR=85.3%  PF=25.87  net=+$124,669  ← 機能している
 stop_loss      : n=88  WR=25.0%  PF=0.069  net=-$150,837  ← 問題：59%が3日以内早期カット
 breakeven_stop : n=33  WR=27.3%  PF=0.696  net=  -$4,417
 time_based     : n=9   WR=88.9%  PF=6.578  net= +$24,277
 corporate_actn : n=1   WR=100%   PF=∞      net=    +$617
```

**stop_loss 根本原因（G9分析）**
```
 3日以内早期カット: 52件（59%） ← ノイズ起因の誤発動
 ETF stop_loss:    41件 net=-$61,778  ← sector_shock_hold で対処予定
 Stock stop_loss:  47件 net=-$89,058
 対策: min_hold 1日（07-13実装済み）+ sector_shock_hold override（A/B後）
```

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
2026-06-25         ✅ R0   paper_demo に P6/P9 接続（guardrail + experiment tracking）
                   ✅ R1-A exit シグナル発火ログ追加
                   ✅ R2-C 個別株 size_multiplier = 0.5x 適用
                   ✅ R6 C1 Console Run Health + text renderer + alert 体系
                   ✅ R6 C2 Price Integrity + API/Token Monitor

2026-06-26〜27     ✅ R1-A 結果確認（Case B/D: SimpleExitV2 シグナル正常発火確認）
                   ✅ R1-B 完了（commit 063f66d: exit_reason ライフサイクル修復）

2026-06-28〜07-04  ✅ R1 完了（R1-C/D: commit 0d0ba73 + attribution fix commit b658f7d）
                   ✅ R2-A 完了（asset_class フィールド付与: commit b658f7d）

2026-07-01（前倒し完了）
                   ✅ Guardrail hard-halt 有効化（6日間誤発動ゼロ確認済み）
                   ✅ R6-D 完了（Decision Funnel deny_reasons + Broker/Tracker パネル）
                   ✅ R2 全完了（R2-B/D：ETF/株 別メトリクス必須化 + エントリーフィルター）
                   ✅ R3-A 完了（反実仮想スクリプト作成・実行）
                   ✅ R3-B 完了（exit replay 評価 + 結論）
                   ✅ R4-A 完了（signal_strength 飽和原因調査）
                   ✅ R4-B 完了（saturation / min_signal_strength 調整）
                   ✅ R6 C4 完了（R6-E: Attribution パネル・ETF/Stock 別 PF・exit_reason 別 PF）
                   ✅ R6 C6 完了（R6-F: リモート Web 読み取り専用・スマホ対応）
                   ✅ R6-F-GW 完了（Tailscale Serve 実運用ルート設計・検証）
                   ✅ Go/No-Go チェックリスト定義

2026-07-06（前倒し完了）
                   ✅ R6-F-LS 完了（/api/live_summary エンドポイント）
                   ✅ R7-A 完了（Corporate Action 台帳 + 自動検知）
                   ✅ ETF buy guardrail 誤警告解消

2026-07-07〜07-09  ✅ Broker audit / CRWD split 修正 / R2-B/D 前倒し確認
（07-09）           ✅ Tracker rebuild（integrity 8 → 0）
                   ✅ Console 再起動

2026-07-10         ✅ RF フェーズ完了（Codex Review F1〜F7 実装・修復スクリプト実行）
                   ✅ RF-1（F1） quarantine 台帳: pnl_tracker.py gate 実装 + 54件移行
                   ✅ RF-2（F2） GuardrailEngine mismatch 実測値接続（hardcoded 0 廃止）
                   ✅ RF-3（F3） exit_reason_store 全書き込み atomic 化
                   ✅ RF-4（F4） TradeEntry に durable metadata フィールド追加
                   ✅ RF-5（F5） DecisionRecord に AI telemetry フィールド定義
                   ✅ RF-6（F6） stock-reduced mode gate 実装（ENTRY_FILTER_STOCK_REDUCED）
                   ✅ RF-7（F7） sector_shock_hold shadow モジュール + paper_demo shadow log 連携
                   ✅ RF-8（F8） clean-records 初回分析実施（PF/exit別/ETF-Stock別）
                   ✅ exit_reason 回復 127件（attribution: 1.5% → 65.3%）
                   ✅ テスト 719 passed（新規 5 ファイル 32 tests 追加）

── 次のアクション ──────────────────────────────────────

2026-07-10         ✅ RF-6b  ENTRY_FILTER_STOCK_REDUCED=true を cron に追加（14シンボルブロック/10シンボル通過）
                   ✅ RF-8c  stop_loss 原因分析完了（06-25 セクターショックが主因、staged_trailing が最善）
                   🔲 paper_demo 実行ログで sector_shock_hold SHADOW の出力を確認

2026-07-13（前倒）    ✅ RF-8b  attribution coverage 100% 達成（69/69件回収）
2026-07-13（前倒）    ✅ RF-5b  AI telemetry 1,939件 backfill（token_usage.csv + ai_usage.jsonl 生成）

2026-07-13（Codex Review G1-G10 全完了）
                   ✅ G1  circuit_breaker 解除 + race condition 再発防止（注文後3秒 wait）
                   ✅ G2  console false-OK bug 修正（mismatch > 0 → HALTED 表示）
                   ✅ G3  PnL source-of-truth 再構築（INV1+INV2 PASS、569Xf5,690.07 一本化）
                   ✅ G5  token telemetry backfill 完了、新規実行時から本番記録
                   ✅ G6  symbol_registry.yaml（69シンボル）+ 全trade asset_class backfill（unknown=0）
                   ✅ G7  SMH/SOXX/QQQ/SPY/SOXQ benchmark 収集（各90日分）
                   ✅ G8  portfolio_allocation → stock_reduced（ETF=0.85, multiplier=0.25）
                   ✅ G9  stop_loss min_hold 1日 実装（緊急 cap -12%、YAML トグル）
                   ✅ paper_demo dry-run 正常動作確認（sector_shock shadow 6件観測）
                   ✅ テスト 676 passed / 2 skipped

2026-07-14〜07-17  🟠 次回 Codex レビュー推奨（sector_shock shadow 10件以上待ち）
                   ✅ min_hold 実効確認（2026-07-17）
                      - 07-13以降 stop_loss 5件: AMD(14d) / ANET(2d) / QTEC(20d) / NOW(9d) / DELL(1d)
                      - 全て1日以上保有後の発動 → min_hold 正常機能
                      - 1日未満のノイズ誤発動ゼロ ✅
                   ✅ sector_shock shadow 累計確認（2026-07-17）
                      - 累計 6件（07-11: 5件 / 07-14: 1件 / 07-15〜07-17: 0件）
                      - ⚠️ 5件が no_sector_data → バグ检出: sector データ取得失敗のわかり
                      - 1件は relative_weakness_exit（FRWD: symbol -100% vs sector -4.1%）
                      - A/B 開始条件（10件）まで残り4件。引き続き passive 観察
                   ✅ sector_shock shadow データ取得修正（2026-07-17 commit f6f1f6f）
                      - Fix1: sector_1d に benchmark_returns.csv フォールバック追加
                      - Fix2: symbol_1d を proxy でなく all_features.return_1d から取得
                      - 07-16 US (SMH -3.7%)の NOW/DELL は修正後 sector_shock_hold 分類確認
                      - 739 passed / 2 skipped (+3 regression tests)

2026-07-21         ✅ G1-v2  post-run mismatch lag exclusion（commit 84e4532）
                      tracker_only ∩ 今回BUY + broker_only ∩ 今回SELL を mismatch から除外
                      3秒 wait 不足問題を根本解決。+11 tests、763 passed
                   ✅ RF-8b-v2  attribution 70.7% → 98.8%（commit 0aadf00）
                      trade_events 15件 + decisions 58件 = 73/76件回復
                   ✅ Circuit Breaker  HALT クリア（09:39 JST）
                      根本原因: 07-21 market_open cron (META+HPQ) API lag

2026-07-28〜07-30  ✅ hard-halt 環境でのペーパー最終確認（完了）

2026-07-31         ✅ Go/No-Go 最終判定: **🟢 GO（7/7 全条件クリア）**
                   ✅ circuit_breaker HALT 解除（07-30 22:25 JSTの fail-closed）
                   ✅ BUG修正: broker.get_account() → equity 変数再利用（`fdab6cd`）
                   ✅ BUG修正: load_or_capture_day_start に missing上書きロジック追加
                   ✅ BUY停止期間調査: 07-29 22:35 〜 07-31 09:40\uff0）2日11時間）
                      Bug1: FIX-002 STOCK_MULTIPLIER=0.5 allocationバグ / Bug2: broker.get_account() BUY HALT
                   👤 今夜 22:25 JST: 初の修正済み BUY run

2026-08-20以降 🚀 リアルトレード開始（延期: 2026-07-28ユーザー指示）

── Post-Launch（2026-08-20以降）─────────────────────────

2026-08-04〜08-18  🔲 R4-C 完了（signal strength デサイル別 PF 計測スクリプト + コンソール表示）
                   🔲 RF-7b  sector_shock_hold paper A/B 正式実施（shadow log >= 10件確認後）

2026-08-18〜09-01  🔲 R5 着手（昇格・降格ゲート定義 ← R2/R4 完了が前提）
                   🔲 R6 C5 着手（Risk Dashboard ← R5 と並行）

2026-09            🔲 R7-B/C（WebSocket / ニュース感情評価）

2026-10+           🔲 R8（ML：クリーンラベル 1,000 件到達後）
```

---

## 改訂ロードマップ v2（R0-v2〜R8-v2）— Codex Review マージ版

**改訂日**: 2026-07-21（Codex Review H0-H9 統合）
**前バージョン**: R0-R8（2026-07-13）→ git 履歴で参照可能
**Status 定義**: VERIFIED_COMPLETE / IMPLEMENTED_UNVERIFIED / REOPENED / IN_PROGRESS / BLOCKED_BY_DATA / PLANNED

> **重要方針訂正 (2026-07-21)**  
> 運用上の正しい asset allocation 方針: **Stock 85% / ETF 15% 前後**  
> 旧 ETF-first / stock-reduced (ETF 85% / Stock 15%) 記述は廃止。  
> `config/strategy/portfolio_allocation.yaml` を更新済み。

---

### 依存関係

```
R0-v2 Ledger/PnL/Guardrail/Metadata Gate  ← 最優先
 └→ R1-v2 Trade Lifecycle and Attribution
 └→ R2-v2 Classification and Policy Unification
 └→ R6-v2 Console Contract (status分離・完全funnel)
     └→ R3-v2 Exit Replay / Sector Shock A/B  ← R0-v2 完了後のみ開始可
     └→ R4-v2 Signal Calibration
     └→ R5-v2 Portfolio Risk / Promotion Gates ← R0-v2 完了後のみ開始可

R7-v2 Data Reliability  ← R0-v2 完了後、R3/R4/R6 と並行可
R8-v2 ML               ← R0-v2 完了 + clean labels ≥300 後のみ開始可
```

**R0-v2 未完の間、開始禁止**: R3-v2 paper A/B / stop 閾値本採用変更 / R5-v2 昇格判定 / R8-v2 ML 実行影響

---

### ✅ 旧完了フェーズ（R0-R8 v1）— 歴史的記録、削除しない

| タスク | 旧 Status | 新 Status | 根拠 |
|--------|-----------|-----------|------|
| R0: guardrail + experiment 接続 | 完了 | REOPENED | P9 全 metric/action 未接続 |
| R1: exit attribution | 完了 | REOPENED | closed/quarantine 重複 41件 |
| R2: ETF/Stock 分離 | 完了 | REOPENED | allocation 逆転・asset_class unknown=245 |
| R3: 反実仮想検証 | 完了（R3-A/B） | REOPENED → BLOCKED_BY_DATA | 有効 sector_shock trigger=0、価格路 replay 未実装 |
| R4: signal 飽和修復 | R4-A/B 完了 | IMPLEMENTED_UNVERIFIED | R4-C 未実施、saturation 73% 残存 |
| R5: 昇格・降格ゲート | PLANNED | REOPENED | 汚染台帳コホート入力、allocation 逆転 |
| R6: Console | C1-F/GW/LS 完了 | IMPLEMENTED_UNVERIFIED | ledger_quality={} in non-dry-run |
| R7: データ品質 | R7-A 完了 | IN_PROGRESS | R7-B/C 未着手 |
| R8: ML | PLANNED | BLOCKED_BY_DATA | clean labels ≥300 が前提条件 |

---

### 🔴 R0-v2: Safety Containment, Ledger, Guardrail, Metadata Gate

**Status**: VERIFIED_COMPLETE (2026-07-30 Remediation 7フェーズ完了)  
**Priority**: P0（全ロードマップのブロッカー）  
**統合元**: H0 + H1 + H2 + H4 + 旧R0 + P6 + P9  
**Target date**: 2026-07-23〜07-31

#### R0-v2-A: Safety Containment（H0）

**Status**: ✅ VERIFIED_COMPLETE（2026-07-22）  
**Commits**: 2248eb2 + d764953  
**実装内容**:
- circuit_breaker `recovery_pending` ステートマシン（--force-ok による緊急抑払あり）
- コンソールに SAFETY GATE バナー（INVALID 時は NO-GO + PF/WR = NOT_VALID）
- `read_ledger_quality_gate()` / `read_circuit_breaker_config()` 追加
- testing_standards.md + stock_swing/AGENTS.md 作成

**Acceptance criteria**:
- ✅ invalid ledger でも live-ready 表示にならない
- ✅ manual clear だけでは current status が OK にならない
- +39 tests（802 passed）

#### R0-v2-B: Ledger Integrity（H1）

**Status**: ✅ VERIFIED_COMPLETE（2026-07-22）  
**Commits**: 3222b73 + babe6c4 + b7efa25  
**辺決消済み issue**:
```
overlap=41→⨀ reversed=62→⨀ hd_missing=245→⨀ ac_unknown=245→⨀
```
**旧 Evidence** (pre-2026-07-22 履歴):
```
closed/quarantine trade_id overlap: 41件  (P0-1)
entry_time > exit_time: 62件              (P0-1)
holding_days is None in closed: 245件     (P0-1)
asset_class unknown in closed: 245件
```

**実装内容**:
1. closed trade canonical validator（chronology / holding_days 再計算 / quarantine 排他）
2. `holding_days is None` の closed trade を repair または quarantine
3. quarantine ID を tombstone として rebuild に渡し、二重生成を防止
4. `trade_id` を position/lot ID とし、partial fill に `execution_leg_id` を追加
5. broker FIFO matching を `executed_at` 順で決定的に
6. corporate action を通常 trade と分離（split-adjusted qty/price + adjustment record）
7. `PerformanceSnapshot` を単一 source of truth にし、state/report/console/export がこれのみを参照
8. broker equity bridge: starting_equity + cash_flow + realized + unrealized - fees = broker_equity

**Tests**:
- `test_closed_trade_requires_computed_holding_days`
- `test_quarantine_and_closed_are_mutually_exclusive`
- `test_rebuild_is_idempotent`
- `test_rebuild_preserves_attribution_and_metadata`
- `test_partial_fill_has_unique_execution_leg_id`
- `test_broker_equity_bridge`

**Acceptance criteria**:
- invalid chronology=0、missing holding_days=0、closed/quarantine overlap=0
- rebuild を 2 回実行して hash/count/PnL が不変
- closed sum = state = PerformanceSnapshot = console
- broker equity bridge 差分 ≤ $1 または 1bp

#### R0-v2-C: Guardrail End-to-End Wiring（H2）

**Status**: ✅ VERIFIED_COMPLETE（2026-07-22）  
**Commit**: 8f6a147  
**実装内容**:
- `RiskSnapshot`（risk_snapshot.py）: 全 9 metrics を型付き一世に計算
- 副作用なしの compute_daily/weekly/consecutive 関数
- paper_demo: pre-buy/post-run共に build_risk_snapshot() で全 9 一括評価
- reduce_size: _effective_exposure_cap * 0.5 で sizing に反映
- flatten_risky: リスクポジションリスト生成（自動実行禁止）
- +17 tests（850 passed）

**旧 Evidence** (pre-2026-07-22):
- `daily_realized_loss_pct` → MISSING
- `weekly_total_loss_pct` → MISSING
- `consecutive_losing_trades` → MISSING
- `token_spend_spike_pct` → MISSING
- `api_error_rate_pct` → 0.0 固定

**実装内容**:
1. typed `RiskSnapshot` を作り startup / pre-order / post-run で共通利用
2. 全 9 metrics を実測値で供給（api_error_rate_pct を 0.0 固定から実測へ）
3. G1-v2 の symbol 減算を pending reconciliation state machine へ置換
   - poll 2/5/10/20秒、最大60秒、deadline 超過 → unexplained mismatch → HALT
4. 全 action を実行系に接続:
   - `reduce_size` → DecisionRecord/sizing へ反映（現在は破棄）
   - `block_buys` → 新規 BUY 停止
   - `ai_pause` → provider call を skip し skip_reason 記録
   - `flatten_risky` → operator approval 付きプラン生成（自動成行 flatten 禁止）
   - `halt` → BUY 停止、SELL/risk exit のみ許可

**Tests**:
- `test_all_configured_guardrail_metrics_are_supplied`
- `test_reduce_size_changes_final_order_qty`
- `test_ai_pause_skips_provider_call`
- `test_pending_sync_converges_without_halt`
- `test_pending_sync_timeout_halts`
- `test_true_qty_mismatch_is_not_excused`
- `test_manual_clear_requires_verification_run`

**Acceptance criteria**:
- config 上 enabled の rule に未供給 metric が 0件
- 5 actions すべてに E2E test
- 10 scheduled paper runs 連続で unexplained mismatch=0、false HALT=0

#### R0-v2-D: Durable Metadata & Experiment Join（H4）

**Status**: ✅ VERIFIED_COMPLETE（2026-07-22）  
**Commit**: 6b21464  
**実装内容**:
- paper_demo.record_submission 呼び出しに run_id/experiment_id/config_hash 追加
- 新規トレードの join coverage: 0% → 100%
- post-run join_coverage ログ生成
- +8 tests

**旧 Evidence** (pre-2026-07-22):
- decision_id in closed trades: 4/259
- run_id in closed trades: 0/259
- experiment_id: 0/259
- decision-trade join success: 0件

**実装内容**:
1. `record_submission()` へ run_id / experiment_id / prompt_version / config_hash / decision_id を渡す（現在未渡し）
2. order → fill → closed trade → outcome へ同じ ID を伝播
3. `deny_reasons` list を JSON または `|` 区切りで保持（現在 CSV で空欄）
4. join coverage report を毎 run 生成

**Acceptance criteria**:
- deployment 後の decision → order → fill → trade join ≥99%
- run_id / experiment_id / config_hash coverage ≥99%
- deny_reason coverage =100%

---

### ✅ R1-v2: Trade Lifecycle and Attribution

**Status**: VERIFIED_COMPLETE（2026-07-28）  
**Priority**: P1（R0-v2-B 完了後）  
**統合元**: H1 + H4 + 旧R1  
**Completed**: 2026-07-28

**実装済み**:
- execution_leg_id ✅（partial fill の各 lot を `{trade_id}-leg-{n}` で一意識別）
- holding_days 必須化 ✅（202件データ修復 + canonical validator）
- quarantine 排他 ✅（overlap検知を broker_order_id ペアに修正）
- attribution coverage 100% ✅
- reversed 7件 quarantine 移動 ✅（07-25 FIFO ミスマッチ）
- asset_class を rebuild 後に自動 backfill ✅（構造修正）

**Acceptance criteria**:
- ✅ overlap=0 reversed=0 hd_missing=0 ac_unknown=0 pnl_diff=0.0
- ✅ ledger_quality_gate: VALID（2026-07-28 再検証済み）
- ✅ check_ledger_invariants passed=True

---

### ✅ R2-v2: Stock 85% / ETF 15% Classification and Policy Unification

**Status**: VERIFIED_COMPLETE（2026-07-28）  
**Priority**: P1（R0-v2-B 完了後）  
**統合元**: H5 + 旧R2  
**Completed**: 2026-07-28

**方針**: Stock 85% / ETF 15% 前後が唯一の正式 allocation 方針

**実装済み**:
1. `config/strategy/portfolio_allocation.yaml`: Stock=0.85 / ETF=0.15 ✅（2026-07-21）
2. allocator / sizing / console が同じ YAML を参照 ✅（H5 2026-07-23）
3. asset_class unknown=0 ✅（backfill 自動化 + 2026-07-28 修復）
4. sector_shock per-symbol ベンチマーク修正 ✅（2026-07-28）

**Acceptance criteria**:
- ✅ asset_class unknown=0
- ✅ config / allocator / sizing / console target が Stock 85% / ETF 15% で一致

---

### 🔴 R3-v2: Exit Counterfactual and Sector Shock A/B

**Status**: BLOCKED_BY_DATA  
**Priority**: P2（R0-v2 完了後のみ開始可）  
**統合元**: H6 + 旧R3 + F7/RF-7  
**Target date**: 2026-08-03〜08-14（R0-v2 完了後）

**ブロック理由**:
- valid sector_shock_hold trigger: **0件**（以前の「3件」は soft_stop / no_sector_data）
- days_held / state が persistent でない
- signal_strength をリターン代用として使用中（廃止必要）
- 実価格 path による counterfactual 未実装（現在は $0 仮定）
- 台帳汚染により exit 成績が信頼できない

**実装内容**（R0-v2 完了後）:
1. symbol registry の benchmark_symbols を symbol ごとに使用（全銘柄を SMH/SOXX と比較禁止）
2. signal_strength return proxy を廃止、feature 欠損時は `insufficient_data` 分類
3. days_held / thesis_break / portfolio_risk を実値で渡す
4. recovery state を trade_id 単位で atomic persist
5. paper_ab は entry 時または最初の stop trigger 時に deterministic bucket を固定
6. counterfactual を実価格 path で再生（exit now / hold 1/3/5/10d / hard cap / MFE / MAE）
7. historical event replay (≥100 events) と forward shadow (≥10 triggers) を別管理

**Activation criteria for A/B**:
- invalid shadow=0
- historical shock replay ≥100 events
- forward valid stop-trigger shadow ≥10
- treatment が baseline より costs 込み expectancy、CVaR、max drawdown で 2 指標改善

**進捗（2026-08-05）**: `scripts/sector_shock_historical_replay.py` で過去の
loss-mitigation exit（stop_loss + breakeven_stop、計111件、2026-05-14〜07-30）を
当時の実際のセクターベンチマークリターン（data/benchmarks/benchmark_returns.csv）で
再分類し、**historical shock replay 111件（目標100件を達成）** を記録
（`data/sector_shock_historical_replay_log.jsonl`）。ただし有効な
sector-shock context（sector_shock_hold + relative_weakness_exit）は **1件のみ**
（TSM 2026-07-01）。forward valid stop-trigger shadow（目標10件）も現在0件
（data/sector_shock_shadow_log.jsonlは全件17件が soft_stop）。
**結論**: historical replay件数は達成したが、「有効なショック事例」の蓄積は
依然として不足。実際のセクター全体ショック（-3%閾値超え）自体が監査期間中に
ほとんど発生していないのが根本原因であり、A/B開始は引き続き市場のショック
発生待ち。阀値見直し（例: -3.0% → -2.0%）の検討はこのデータを基に行う。

#### R3-v2-Stop: Tiered min_hold v2（offset_pct 再設計・再有効化）

**Status**: IMPLEMENTED_UNVERIFIED（2026-08-05）  
**Priority**: P2（sector_shock A/B とは独立、R0-v2完了済みのため即日実施可）  
**経緯**: 07-27 Plan A（`52736ca`）→ 07-29 FIX-007（`687c5c5`）で無効化（絶対
return_pct基準の7日tierがstandard/high-conviction銘柄で到達不可能だったため）
→ 08-05 offset_pctベースに再設計して再有効化（commit `27a8742`）。

**実装内容**:
- tier判定を「発火した有効stop閾値からの相対オフセット（offset_pct）」で行うよう変更
  （`offset_pct = (return_pct - eff_stop_loss_pct) * 100`）
- conviction tier（-5%/-7%/-9%）に依存せず全tierで到達可能に
- `config/strategy/simple_exit_v2.yaml`: `tiered_min_hold_enabled: true`（offset_pct: -2.0pp→7日
  / -5.0pp→3日 / それ以上→base 1日）
- テスト: Plan Aテスト群全面更新（+2件 low/high conviction到達性回帰テスト）。
  フルスイート 1325 passed / 2 skipped（既知の無関係つ2件のみ）

**未実施（フォローアップ課題）**:
- 07-27時点のシミュレーション根拠（+$41K改善）は絶対値ベースのバックテストだった
  ため、offset_pctベースでの再シミュレーションが未実施
- paper実測での効果検証（「正しい止損率」の改善確認）も未実施

**Acceptance criteria**（次回フォローアップで確認）**:
- `scripts/analyze_stop_loss_post_exit.py` で offset_pct 導入後の新規 stop_loss tradeを
  別集計し、正しい止損率が向上（目標≥70%）するかを確認
- 直近30日 stop_loss net_pnl（console `stop_loss_health.recent_30d`）が悪化していないことを
  確認
- 目安確認日: 2026-08-19頃（08-05導入から約2週間の段階で一度中間レビュー）

**ロールバック**: `tiered_min_hold_enabled: false` に戻すだけ

#### R3-v2-Breakeven: Staged Floor（段階的floor、Breakeven Stop）

**Status**: IMPLEMENTED_UNVERIFIED（2026-08-05）  
**Priority**: P2（sector_shock A/Bとは独立、即日実施可）

**背景**: Breakeven Stop（peak_returnが活性化ライン到達後、return≤40%で即exit、
floor固定0%）はPF 0.7前後・WR 20〜27%とExit 3戦略中最弱。Post-exit driftシミュレー
ション（breakeven_stop発火43件、`scripts/analyze_breakeven_staged_floor.py`）で、
固定0%floorがさらなる上昇を見逃して早利確しすぎているケースが確認された（見込み
改善額 +$4,979、n=43、6件改善/0件悪化）。

**実装内容**: Trailing Stopのstaged_trailingと同じ発想で、peak_returnが上がるほど
floorを段階的に引き上げ（ratchet）:
- peak +5%到達 → floor 0%（現行ルールと完全一致）
- peak +8%到達 → floor +3%
- peak +12%到達 → floor +6%
- `config/strategy/simple_exit_v2.yaml`: `staged_breakeven_enabled: true`
- 実装: `SimpleExitV2Strategy._resolve_breakeven_floor()`（commit 参照）
- テスト: +9件新規追加。フルスイート 1333 passed / 2 skipped（既知の無関係つ2件のみ）

**未実施（フォローアップ課題）**:
- シミュレーションはyfinance日次OHLCの近似であり、n=43と少ない。paper実測での
  効果検証が未実施

**Acceptance criteria**（次回フォローアップで確認）**:
- breakeven_stop発火トレードのexit_reason別内訳を確認（"Staged breakeven stop"が
  実際に発火しているか）
- 直近30日のbreakeven_stop net_pnlが改善傾向にあるかを確認
- 目安確認日: **2026-09-05**（08-05導入から1ヶ月後）

**ロールバック**: `staged_breakeven_enabled: false` に戻すだけ

---

### 🟡 R4-v2: Signal and Confidence Calibration

**Status**: IMPLEMENTED_UNVERIFIED  
**Priority**: P2（R0-v2 完了後推奨）  
**統合元**: H7 + 旧R4  
**Target date**: 2026-08-17〜08-28

**実装済み（未検証）**:
- R4-A: signal_strength 飽和原因調査 ✅
- R4-B: min_signal_strength 調整（confidence ≥0.40 filter） ✅

**未実装 / 未検証**:
- saturation: 73% が strength=1.0 → R4-B 後も改善なし
- R4-C: デサイル別 PF スクリプト（post-launch 予定、データ不足で今は実施不可）
- raw score / normalized score / cross-sectional percentile 保存
- confidence を calibration 可能な probability として定義（固定 0.85 多発の解消）
- feature snapshot を decision 時点の as-of データで immutable 保存
- decile 別 PF / expectancy / calibration curve 生成

**Learning 制約**: recommendation-only。自動本番反映禁止。

---

### 🔴 R5-v2: Portfolio Risk and Promotion Gates

**Status**: REOPENED  
**Priority**: P2（R0-v2 完了後）  
**統合元**: H5 + H7 + 旧R5  
**Target date**: 2026-08-17〜08-28

**再 open 理由**:
- promotion gate が汚染台帳コホートを入力に使っている
- allocation policy が逆転していた（→ R2-v2 で訂正済み）
- market beta / sector/factor exposure / pairwise correlation / top-5 concentration 未実装

**実装内容**:
1. Stock 85% / ETF 15% 前後を allocation band (target + threshold) で実装
2. order 後の projected allocation で判定
3. market beta / sector factor / cluster cap を一元管理
4. `data_quality=RED` では PF/WR を `not_valid` 表示し、promotion gate に渡さない
5. clean audited cohort のみで promotion 判定

---

### 🟡 R6-v2: Console and Operational Observability

**Status**: IMPLEMENTED_UNVERIFIED  
**Priority**: P1（R0-v2 と並行）  
**統合元**: H3 + H9 + 旧R6  
**Target date**: 2026-07-28〜07-31

**実装済み**:
- C1-F / GW / LS パネル群 ✅
- Run Health / Price Integrity / API Monitor ✅
- non-dry-run に ledger_quality / entry_filter_stats 伝達 ✅（2026-07-22）
- 完全 7-stage funnel（generated→reconciled） ✅（2026-07-22）
- status 分離（run.last_run / run.data_quality） ✅（2026-07-22）
- data_quality=INVALID 時に PF/WR = NOT_VALID 表示 ✅（R0-v2-A SAFETY GATE）

**残未実装**:
- mtime/config hash キャッシュ（毎回 CSV 全読込み防止）← H9
- WebSocket ← H9（state correctness 確認後）
- 完全 funnel: generated → risk_denied → entry_blocked → allocation_blocked → guardrail_blocked → qty_zero → submitted → accepted → filled → reconciled
- manual clear 後 → `RECOVERY_PENDING` 表示
- mtime/config hash cache（毎 rerun での CSV 全読み込み防止）

**Performance SLO**: initial render p95 ≤2秒、cached rerun p95 ≤500ms

---

### 🟡 R7-v2: Data Reliability and Operational Edge Cases

**Status**: IN_PROGRESS  
**Priority**: P2（R0-v2 完了後 R3/R4/R6 と並行可）  
**統合元**: H8 + 旧R7  
**Target date**: 2026-08-03〜08-14

**完了 (VERIFIED_COMPLETE)**:
- R7-A: Corporate Action 台帳 + 自動検知 ✅

**未実装**:
- source ごとの SLA + quality report
  - broker position/order: ≤30秒
  - intraday quote: market open 中 ≤2分
  - daily bar: 前営業日 close 確定後
  - sector benchmark: exit 判断時点と同じ as-of
- `event_time` / `available_at` / `ingested_at` / `source` / `revision_id` / `quality_status` を canonical schema へ追加
- Massive client の connection pool 共有（`Connection pool is full` 解消）
- market closed 時は maintenance job 以外早期終了
- macro (FRED) の regime lineup（現在 unknown のまま）
- R7-B/C: WebSocket / ニュース感情評価

---

### 🔵 R8-v2: Learning and ML

**Status**: BLOCKED_BY_DATA  
**Priority**: P3（R0-v2 完了 + clean labels ≥300 後）  
**統合元**: H7 + 旧R8  
**Target date**: 2026-10 以降

**開始条件**:
- R0-v2〜R4-v2 の acceptance criteria をすべて満たすこと
- clean joinable outcomes ≥300（単純 calibration 開始）
- ML training は clean labels ≥1,000 が原則
- champion/challenger / model registry / drift detection / rollback を用意してから開始

**学習制約**: recommendation-only。自動本番反映禁止。

---

## 次のアクション（直近）— v2 改訂版

```
2026-07-22         ✅ R0-v2-A  safety containment（recovery_pending・SAFETY GATE）
                   ✅ R0-v2-B  ledger integrity 全完了（data repair + canonical validator + equity bridge）
                   ✅ R0-v2-C  guardrail E2E（RiskSnapshot 全 9 metrics + reduce_size + flatten_risky）
                   ✅ R0-v2-D  metadata join（run_id/exp_id/config_hash せ 0% → 100%）
                   ✅ R2-v2溈  portfolio_allocation.yaml 訂正
                   ✅ R6-v2溈  non-dry-run ledger_quality + 7-stage funnel + status 分離
                   ✅ R1-v2溈  execution_leg_id（partial fill 一意化）
                   ✅ AGENTS.md  Codex review H0–H9 自動参照 設定
                   ✅ testing_standards.md 作成

                   🔴 Go/No-Go required 全件 ✅（ledger=VALID / CB=ok / attr=100% / crons OK）
                   ⚠️  preferred 未達: overall PF=0.686（目標 1.20）/ stop_loss WR=24%（目標 30%）

2026-07-23（木）    ✅ R2-v2  allocator 統一（H5: allocation_config.py + projected band check + 30 tests）
                         allocation band で projected overweight 専判定

2026-07-24（金）    ✅ R1-v2  rebuild idempotency + quarantine tombstone（前倒し：07-23 完了）

2026-07-25（土）    🔲 バッファ / paper demo 観察（木金実装 の cron 正常動作確認）

2026-07-26（日）    🔲 Go/No-Go 事前レポート作成
                         ・ PF/WR 現状整理 + preferred 条件との差分
                         ・ 50%サイズ開始可否の判断材料まとめ

2026-07-27（月）    🔲 R6-v2 H9（任意）/ paper 最終確認

2026-07-28〜30   paper demo 観察期間（実装なし）
                   ・ sector_shock_hold shadow カウント
                   ・ 直迕5日の trailing_stop / stop_loss 動向

2026-07-31（木）    🚨 Go/No-Go 最終判定
                   ・ required 全件 ✅ → 判断点は「overall PF 0.686 を許容するか」
                   ・ YES: 50%サイズで 08-20以降 開始
                   ・ NO: sector_shock_hold 完成（推定 08-20）まで延期

2026-08-20以降 🚀（予定）  リアルトレード開始（50%サイズ）

2026-08-05          ✅ R3-v2-Stop  tiered min_hold v2（offset_pct再設計・再有効化、commit 27a8742）

2026-08-05          ✅ R3-v2-Breakeven  staged floor（段階的floor導入）

2026-08-05          ✅ R3-v2  sector_shock historical replay 111件蓄積開始（目標100件達成）

2026-08-19頃          🔲 R3-v2-Stop 中間レビュー: post-exit drift再分析で「正しい止損率」改善確認

2026-09-05          🔲 R3-v2-Breakeven 中間レビュー: staged floorのpaper実測での改善確認（08-05導入から1ヶ月後）

2026-08-03〜08-14  R3-v2    exit replay / sector shock shadow（R0-v2 完了後のみ）
                   R7-v2    data SLA / source lineage

2026-08-17〜08-28  R4-v2    signal calibration + decile
                   R5-v2    portfolio risk + promotion gates A/B

2026-08-31以降     Gate review → micro-live 可否判定
```

---

## やらないこと（制約）— v2 更新版

```
❌ R0-v2 未完のまま sector_shock paper A/B を開始しない
❌ R0-v2 未完のまま stop 閾値を本採用変更しない
❌ R0-v2 未完のまま R5-v2 promotion 判定を行わない
❌ R0-v2 未完のまま R8-v2 ML の execution 影響を発生させない
❌ ETF-first / stock-shadow を恒久方針とする変更はユーザー承認なしに行わない
❌ 汚染台帳コホート（closed/quarantine 重複 41件等）を PF 分析や promotion gate に使わない
❌ manual clear だけで current_status を OK にしない（verification run 必須）
❌ signal_strength を日次リターン代用として sector_shock 分類に使わない（feature 欠損 → insufficient_data）
❌ counterfactual を "$0 仮定" で計算した結果を昇格判断に使わない（実価格 path 必須）
❌ clean labels ≥1,000 件に達するまで ML を実行に影響させない
❌ ETF と個別株を 1 つの混合戦略として扱わない
❌ スマートフォンから遠隔 buy/sell/cancel/reset を実装しない（読み取り専用のみ）
```

---

## 優先順位まとめ — v2

| 優先度 | Phase | Status | 備考 |
|--------|-------|--------|------|
| 🔴 P0 BLOCKER | **R0-v2** | **REOPENED** | 全ロードマップのブロッカー。ledger/guardrail/metadata |
| ✅ P1 | R1-v2 | VERIFIED_COMPLETE | 2026-07-28 完了 |
| ✅ P1 | R2-v2 | VERIFIED_COMPLETE | 2026-07-28 完了 |
| 🟡 P1 | R6-v2 | IMPLEMENTED_UNVERIFIED | R0-v2 と並行 |
| 🟡 P2 | R3-v2 | BLOCKED_BY_DATA | R0-v2 完了後のみ（sector_shock A/B）。R3-v2-Stop（tiered min_hold v2）は独立して2026-08-05実装済み・IMPLEMENTED_UNVERIFIED |
| 🟡 P2 | R4-v2 | IMPLEMENTED_UNVERIFIED | R0-v2 完了推奨後 |
| 🔴 P2 | R5-v2 | REOPENED | R0-v2 完了後 |
| 🟢 P2 | R7-v2 | IN_PROGRESS | R0-v2 完了後 parallel |
| 🔵 P3 | R8-v2 | BLOCKED_BY_DATA | 10月以降 |

---

## Codex Review 2026-07-29（SSR-20260729-01）対応 — R0-v3以降

**レビュー日**: 2026-07-29
**baseline commit**: 744e3fa → 0ae1ce6（68 commits）
**critical findings**: P0-1〜P0-5（下記）

### Critical findings summary

| ID | 問題 | 影響 | 対応 |
|---|---|---|---|
| P0-1 | collect_data.pyがsynthetic dataをproduction pathへ書き込み | 全feature/学習/backtest無効化リスク | FIX-001 |
| P0-2 | allocation checkが最終sizing前に実行→band未強制 | overweight BUY通過 | FIX-002 |
| P0-3 | recently_sold_symbols=全historical sells→時刻制限なし | 再購入suppression | FIX-003 |
| P0-4 | guardrail daily_loss計算が前回unrealizedを0仮定 | 指標誤計算・fail-open | FIX-005 |
| P0-5 | full consoleが0.0.0.0 bind + 認証なしwrite endpoint | 外部からconfig書き換え可能 | FIX-009 |
| P1-1 | P6 join coverage: run_id/exp_id/config_hash = 0% | decision→trade追跡不能 | FIX-006 |
| P1-2 | 7d min-hold tierが到達不能（stop条件と矛盾） | シミュレーション+$41K無効 | FIX-007（disable） |
| P1-3 | export時のpytest証跡なし（collect_data.pyがSYSTEM python使用） | テスト証跡無効 | テスト実行改善 |
| P1-4 | AI token: rule-basedをactualとして計上 | コスト計算誤り | FIX-010 |
| P1-5 | current_mode.yaml手書きVALIDとexport invariant不一致 | 誤判定 | FIX-004 |

### Export data integrity findings（independent_analysis_20260729.json）— 全件解消済み（2026-08-01確認）

以下は 2026-07-29 export 時点の発見。07-29夹宏修復 + 07-30/07-31 の追加修復で全件解消している（docs/daily_logs/2026-07-29.md, 2026-07-30.md, 2026-07-31.md 参照）。以下は歴史的記録として保持。

- closed_trades.csv: quantity/realized_pnl フィールドが0/205（qty/pnlという内部名でexport） → **解消**（FIX-004 canonical export-row mapper導入）
- duplicate trade_id: ADBE-3fd1e2a4 が2件 → **0件**（07-29台帳修復）
- closed/quarantine overlap: 15件（previouslyは0と報告） → **0件**（07-29台帳修復）
- attribution coverage: 1.96%（現行台帳とjoinできるのは4件のみ） → **98.5%**（07-30/07-31確認、docs/daily_logs/2026-07-30.md で2026-07-31.md）
- equity curve max drawdown: 12.71%（state.max_drawdown_pct=0.91%と不一致） → 未再検証（export専用の計算パスの不一致で、本番台帳のledger_quality_gateはVALID確認済みのため優先度低）

### v3タスクリスト — 2026-08-01 実態反映済み（出典: docs/codex reviews/stock_swing_fix_batch_result_20260729.md）

| Task | Roadmap | Priority | Status | 説明 |
|---|---|---|---|---|
| FIX-001 | R7-v3 | P0 | **VERIFIED_COMPLETE**（`40bcc1d`） | synthetic data production分離 |
| FIX-002 | R2-v3/R5-v3 | P0 | **VERIFIED_COMPLETE**（`c948f57`） | allocation sizing後enforcement |
| FIX-003 | R0-v3/R1-v3 | P0 | **VERIFIED_COMPLETE**（`c948f57`） | fill ledger + recently_sold修正 |
| FIX-004 | R0-v3/R6-v3 | P0 | **PARTIAL**（`c948f57`） | dynamic ledger validity + export mapping。repo内にclosed_trades.csv専用exporterがなく、paper_demo.pyにcanonical export-row mapperを追加したが、repo外のexport専用scriptは未対応 |
| FIX-005 | R0-v3/P9 | P0 | **VERIFIED_COMPLETE**（`c948f57`） | guardrail metric + fail-closed |
| FIX-006 | R0-v3/P6 | P1 | **VERIFIED_COMPLETE**（`c948f57`） | P6 top-level join |
| FIX-007 | R3-v3 | P1 | **VERIFIED_COMPLETE**（`687c5c5`）→ **v2再設計・再有効化**（2026-08-05） | 7d tier disable + exit freeze。08-05: offset_pct（有効stop閾値からの相対オフセット）ベースに再設計し、conviction tierに依存せず到達可能にした上で再有効化。詳細は下記「2026-08-05 Stop Loss tiered min_hold v2」参照 |
| FIX-009 | R6-v3 | P1 | **VERIFIED_COMPLETE**（`992188e`） | console security |
| FIX-010 | R6-v3/R8-v3 | P2 | **VERIFIED_COMPLETE**（`c948f57`） | token accounting separation |

テスト: 1118 passed, 2 skipped（07-29時点、証拠: docs/test_evidence/pytest_output_fix_batch_20260729.txt）。その後 08-01時点で 1267 passed, 2 skippedまで増加。

### 現行status（v3 merge時点）— 2026-08-01 実態反映済み

上記の export data integrity findings（overlap/duplicate/attribution）は全件解消済みのため、以下の REOPENED 判定は解除。現在の正式ステータスは上部「完了フェーズ」欄と「優先順位まとめ — v2」表を参照（R1-v2/R2-v2はVERIFIED_COMPLETE、2026-07-28完了）。R3〜R8の進捗はPromotion requirements節参照。

| Phase | 07-29時点Status | 2026-08-01 時点の確認結果 |
|---|---|---|
| R0-v2 Safety/Ledger/Integration | REOPENED | overlap/duplicate/export PnL欠落は全件解消。guardrail式不FIX-005で修正済み。ledger_quality_gate=VALID（07-28以降継続） |
| R1-v2 Trade Lifecycle | VERIFIED_COMPLETE（2026-07-28） | 変更なし |
| R2-v2 Allocation | VERIFIED_COMPLETE（2026-07-28） | 変更なし（FIX-002でprojected bandの最終enforcementも追加対応） |
| R3-v2 Exit/Sector Shock | BLOCKED_BY_DATA | 08-01時点でも未着手。sector_shock_shadowは直近17件中 sector_shock_detected=True 0件だが調査済み（下記参照）。バグではなく監査期間中にセクターショックの定義を満たす事象が単に発生していなかっただけ。current_mode.yamlのcurrent_valid_shadow_countを 3→0 に修正（実ログと不一致していた古い手動集計値） |

**sector_shock_shadow 0件の調査結果（2026-08-01）**: `data/sector_shock_shadow_log.jsonl` 全17件（07-23〜07-30）を全件確認。分類ロジック（`SectorShockAnalyzer.classify()`）は実装として正しく動作しており、監査期間中の `avg_sector_return_pct` の最大下落はMETA(07-27)の-2.38%で、`sector_shock_threshold_pct=-3.0%`に一度も到達していない。つまり「bugではなく、単に監査期間中にSMH/SOXX/QQQ/SPY等が-3%以上一日下落するほどのセクター全体ショックが一度も発生していない」というのが真相。A/B開始条件（有効shadow≥10件）の達成は、実際のセクターショック発生を待つ必要があり、人為的に促進するべきではない。
| R4-v2 Signal Calibration | REOPENED | 未再検証、未対応 |
| R5-v2 Portfolio/Promotion | REOPENED | 未再検証、未対応 |
| R6-v2 Console | IMPLEMENTED_UNVERIFIED | FIX-009でconsole securityは対応済み（127.0.0.1 bind、write endpointデフォルトoff）。P6 join_coverageはFIX-006でjoin metadataは完了だが、2026-08-01に別途発見された `import json` 欠落バグで実際のレポートファイルは一度も書き出されていなかった（commit `968c1cc`で修正済み）。source_sla（R7-v2-A）は`broker`ソースが`required: true`なのに一度も収集されず`failing_sources`固定だった問題も同日発見し、`collect_broker`/`collect_broker_bars`を実装しcronに組み込み解消（commit `6f48954`） |
| R7-v2 Data Reliability | REOPENED | FIX-001でsynthetic dataはproduction分離済み。残余リスクは未再検証 |
| R8-v2 Learning/ML | BLOCKED_BY_DATA | 変更なし |

### Promotion requirements（live-ready条件）

次を全て満たすまでlive-ready = NO-GO:
- current test run PASS（JSON/JUnit/coverage）
- 20 consecutive scheduled runsでunexplained mismatch=0
- duplicate fill application=0
- closed/quarantine overlap=0
- sum(closed.pnl) vs state cumulative PnL差 <= $1
- run_id/experiment_id/config_hash coverage >=99%
- required source coverage >=99.5%、synthetic production records=0

---

## 2026-08-05 Stop Loss tiered min_hold v2（FIX-007再設計・再有効化）

**背景**: 07-27 Plan A（commit `52736ca`）で導入した tiered min_hold は、
return_pct の絶対値（例: 「return > -5% → 7日」）で tier 判定していたが、
07-29 FIX-007（commit `687c5c5`）で無効化された。理由: standard(-7%)/
high-conviction(-9%) の stop_loss は、その閾値に到達した時点で既に
return ≤ -7%/-9% であり、「-5%より大きい」を満たすことが構造的に
不可能だった（7日 tier が事実上デッドコード化していたのは low-conviction
(-5%)銘柄のみ）。

**再設計方針**: 絶対 return_pct ではなく、**発火した有効 stop 閾値からの
相対オフセット（offset_pct、単位: percentage point）** で tier 判定するよう
変更。
```
offset_pct = (return_pct - eff_stop_loss_pct) * 100
```
conviction tier（-5%/-7%/-9%）に関わらず、閾値をわずかに超えた直後は
常に offset_pct ≈ 0（ノイズ域）、深く超えるほど offset_pct が大きくマイナス
（真の止損域）になるため、全ての conviction tier で 7日 tier が到達可能に
なった。

**設定変更**（`config/strategy/simple_exit_v2.yaml`）:
```yaml
tiered_min_hold_enabled: true   # false → true に復帰
tiered_min_hold_levels:
  - offset_pct: -2.0   # 閾値超過が2pp以内 → 7日様子見（ノイズ域）
    min_hold_days: 7
  - offset_pct: -5.0   # 閾値超過が2〜5pp    → 3日様子見（中間域）
    min_hold_days: 3
  # 閾値超過が5pp超               → base min_hold_days (1日、真の止損域)
```

**実装変更**: `SimpleExitV2Strategy._effective_min_hold_days()` が
`eff_stop_loss_pct`（conviction調整後の実際の閾値）を引数に取り、
offset_pct を計算するように変更。呼び出し元（stop_loss 判定ブロック）も
連動して更新。

**テスト**: `test_simple_exit_v2_strategy.py` の Plan A テスト群を
offset_pct ベースに全面更新（+2件: low/high conviction 到達性の回帰テスト）。
`test_fix007_yaml_disable.py` も「再有効化されている」ことを検証する内容に更新
（+1件: 全 conviction tier での到達可能性検証）。
フルテストスイート: 1325 passed / 2 skipped（既存の無関係な2件の失敗のみ）。

**ロールバック**: `tiered_min_hold_enabled: false` に戻すだけで即座に
旧動作（一律 min_hold_days=1）に戻る。

**期待効果**: 07-27時点のシミュレーション根拠（stop_loss損失 -$167K→-$126K、
+$41K改善）と同じ post-exit drift の知見を、conviction tier非依存の形で
再現。ただし v2 の offset_pct ベースでの再シミュレーション・paper実測での
効果検証は未実施（次回フォローアップ課題）。
- console current snapshot reachable、freshness SLA内
- post-fix clean paper cohortでcost-adjusted PF >1、expectancy >0
