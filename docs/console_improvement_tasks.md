# stock_swing 改善計画（R0-R8 改訂版）

**改訂日**: 2026-07-13（Codex Review G1-G10 対応 + min_hold 実装）  
**旧 P0-P17 体系は廃止。本ファイルのみが正式な改善計画。**

> ⚠️ **別トラック注記（2026-08-19追加）**: ブローカー移行（Alpaca → IBKR）は
> 本ファイルのR0-R9ロードマップ（戦略パフォーマンス評価）とは完全に独立した
> 別トラックとして進行中。9/15 Go/No-Go判定には一切影響しない。
> 計画・進捗は `docs/broker_migration_ibkr_plan.md` を参照（Track A完了済み、
> Track BはD0＝移行開始日確定待ち）。

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

2026-09-15 🚀 リアルトレード開始（延期: 2026-08-14ユーザー指示、旧: 08-20）

── Post-Launch（2026-09-15以降）─────────────────────────

2026-08-04〜08-18  ✅ R4-C 完了（signal strength デサイル別 PF 計測スクリプト。2026-08-14、
                         既存実装済みだったことを発見・検証・週次cron化）
                   🔲 RF-7b  sector_shock_hold paper A/B 正式実施（shadow log >= 10件確認後、
                         現状 valid trigger事例が不足しており市場のショック発生待ち）

2026-08-18〜09-15  ✅ R5 着手・大部分完了（cluster exposure可視化 + promotion gate 5条件。2026-08-14）
                         残: 閾値妥当性のpaper観測検証（延期で確保できた期間で実施）
                   🔲 R6 C5 着手（Risk Dashboard ← R5 と並行）

2026-09以降        🔲 R7-B（WebSocket、延期で確保できた期間を活用し着手検討）
                   ✅ R7-C（ニュース感情評価）→ 2026-08-08 Plan D として shadow mode 実装済みと判明・記載訂正

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
発生待ち。

**阀値見直し検証結果（2026-08-05）→ 変更見送り**: -3.0%→-2.0%への引き下げを
検証した結果（61営業日中検知日数9日→14日）、新規検知される7件のうち
hold候補は3件のみ（AVGO/SHOC/SOXX、relative_weakness_ratio≭2.0）。ユーザー判断により
**現行 -3.0% を維持**（理由: 効果限定的・検証データ不足・件数確保目的での阀値調整は本末転倒）。
詳細: `docs/daily_logs/2026-08-05.md` の「Sector Shock 閾値見直し検証、変更見送り」節参照。

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

**2026-08-19 中間レビュー**:
- `python3 scripts/analyze_stop_loss_post_exit.py --since 2026-08-05`:
  stop_loss 8件、全件 negative PnL。post-exit driftベースの「正しい止損率」は
  **87.5%（7/8）** で、目標の70%を上回った。
- `python3 scripts/analyze_stop_loss_post_exit.py --since 2026-08-05 --counterfactual`:
  主指標では **-$10,811.85**（stop_loss実損失 - 保有継続の反実仮想PnL）で、
  8件中4件は保有継続の方が良かった。主な悪化要因は 2026-08-06 の NBIS 3件で、
  stop後10営業日以内に大きく反発した。
- `reports/console/latest_console_summary.json`（2026-08-19 01:00 UTC）:
  `stop_loss_health.recent_30d = {count: 18, net_pnl: -37470.64, avg_ret_pct: -8.72}`。
  導入前ベースライン（`27a8742^:reports/console/latest_console_summary.json`）の
  `{count: 26, net_pnl: -72496.95, avg_ret_pct: -8.74}` と比べ、rolling 30d net_pnl は
  悪化していない。
- tiered_min_hold suppression（`get_suppression_stats()` 経由、最新console summary）:
  `total=0`。保存済み最新runでは tier別発火は
  `noise_7d=0 / mid_3d=0 / severe_1d=0` で、抑制発火の観測はまだない。

**判断**:
- **継続**。Acceptance criteria の 2項目
  （正しい止損率≥70%、recent_30d net_pnl非悪化）は満たしたため、
  `tiered_min_hold_enabled: true` を維持する。
- ただし counterfactual 主指標はまだマイナスで、特に severe 側の急反発
  （NBIS型）では stop_loss がコスト化しうる。次回レビューでは
  severe帯の事例追加を重点監視する。

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

#### R3-v2-Stop-Redesign: Stop Loss 役割純化リデザイン（2026-08-14）

**Status**: IMPLEMENTED_UNVERIFIED（2026-08-14、3項目とも実装完了・paper検証待ち）
**Priority**: P2（既存stop_loss機構の改修、独立して実施可）
**背景**: ユーザーとの議論で、stop_lossの目的を「単体で勝つ戦略」ではなく
「数ヶ月以上の長期にわたって回復の見込みがない急落から資産を守ること」と再定義。
この定義に照らして実データ検証（post-exit 60営業日追跡、n=60真の止損）した結果:
- **「回復不能」だった実例は0件**（60日間ずっとexit価格を下回り続けたケースなし）
- **entry価格まで回復したケース: 68.3%**（中央値6営業日で回復）
- **反実仮想比較で正味-$152,188のコスト**（stop_lossしなかった場合との差、実損失
  -$159,787 vs 60日保有した場合-$7,599）
- 運用銘柄の年率ボラティリティが30-75%と大きく分散しており、固定-5/-7/-9%閾値は
  高ボラ銘柄には1-2σ（通常のノイズ）にすぎない
- max_hold_days（20日/2日/3日）という短期スイング設計と「数ヶ月」という脅威の
  時間軸が構造的に矛盾（ポジションがそもそも数ヶ月保有されない）

**方針決定（ユーザー承認: 選択肢A「役割純化」）**: stop_lossは「短期の損失限定戦術」
として役割を純化し、長期資産防衛は既存のポートフォリオガードレール（daily/weekly
loss halt、circuit breaker、promotion_gate）に委ねる。**max_hold_daysは変更しない**
（数ヶ月保有前提の戦略変更は不採用）。

**実装内容（3点、全てデフォルト無効・既存動作を破壊しない設計）**:

1. **評価軸の是正**（`scripts/analyze_stop_loss_post_exit.py`）:
   従来の主指標「正しい止損率」（事後に下落したか）は高ボラ銘柄では統計的にほぼ
   常に真になり意味をなさないため、**反実仮想cost/benefit比較を主指標に変更**。
   `--counterfactual`フラグでtrade recordの`qty`から反実仮想PnL（stop_lossせず
   lookforward_days保有した場合）を計算し表示。テスト10件追加。

2. **sector_shock_hold のローリング判定修正**（`sector_shock_hold.py`）:
   従来は単日リターンのみで判定していたため、2026-06-05の実際のセクターショック
   （SMH -9.2%）が翌営業日の一時反発（06-08 SMH +5.0%）で見逃され、shadow_count
   が3ヶ月間0件のままだった。ローリング3日累積リターン（`sector_shock_rolling_
   threshold_pct`、デフォルト-5.0%）をOR条件で追加し、単日チェックが見逃した
   ショックも検知できるように変更。既存の単日チェックはそのまま維持（後方互換）。
   実データ（LRCX 2026-06-08ケース）で正しく`sector_shock_hold`に再分類されることを
   確認。`paper_demo.py`にbenchmark_returns.csvの`return_3d`列を読み込む配線を追加。
   テスト13件追加、既存38件は無変更でパス。

3. **ATRベースの動的閾値**（`simple_exit_v2_strategy.py`）:
   `volatility_adjusted_stop_enabled`（デフォルトfalse）で有効化すると、conviction
   tier（-5/-7/-9%）の基準閾値に、当該銘柄のATR%と当該run内の全銘柄平均ATR%の比
   （`volatility_multiplier`、[0.5, 1.75]でクランプ）を掛けて調整。trailing_stop /
   breakeven_stopには適用しない（既に良好に機能しているため、役割純化のスコープを
   stop_loss分岐のみに限定）。`config/strategy/simple_exit_v2.yaml`に設定追加。
   テスト23件追加（純粋関数9件+統合14件、high-ATR銘柄で閾値が広がり誤発動を回避、
   low-ATR銘柄で閾値が狭まり早期発動することをend-to-endで確認）。

**テスト合計**: 46件新規追加。フルスイート1701 passed / 2 skipped
（既存の無関係な2件の失敗のみ、変更前から存在確認済み）。

**ヒストリカル検証（2026-08-14、paper有効化前）**:
改修3（ATR動的閾値）について、paper環境を有効化せずに2段階の検証を実施:

1. **簡易検証**（`scripts/simulate_volatility_adjusted_stop.py`）: 過去のstop_loss
   発動60件を対象に、閾値調整版で発動していたか/していなかったかを再計算。
   広がった側13件で反実仮想比較（60日保有仮定）: 正味-$43,716（広い閾値の方が得）。
   狭まった側30件は一方向的な近似（既に発動済みトレードのみ、新規誤発動は未検証）。

2. **日次パス検証**（`scripts/simulate_daily_path_volatility_stop.py`、より厳密）:
   全closed trade 228件中208件（同日決済20件を除く）を対象に、
   `SimpleExitV2Strategy`の実メソッド（`_resolve_trailing_rule` / `_resolve_
   breakeven_floor` / `_effective_min_hold_days`）をそのまま流用し、
   trailing_stop→breakeven_stop→stop_loss→time_basedの優先順位を日次で忠実に
   再現。簡易検証の2つの構造的欠落（① exit優先順位を無視、② 新規誤発動リスク
   未検証）を解消。
   - **サニティチェック**: baseline再現のexit_reasonが実本番結果と59%一致
     （日中値・ATR再計算タイミングの違いにより完全一致は期待していない）
   - **最重要リスクチェック**: 狭めた閾値による新規誤発動 = **0件**
     （元々non-stop_loss exitだったトレードが新たにstop_loss化したケースなし）
   - **全体集計**（195件）: ベースライン合計PnL -$189,862 → 調整版 -$166,962、
     **正味+$22,900の改善**（改善17件+$28,597、悪化10件-$5,697）
   - 象徴例: NBIS(06-04) stop_loss -$3,415 → trailing_stopまで生存 +$4,594
   - テスト13件追加（`test_simulate_daily_path_volatility_stop.py`）

**paper有効化（2026-08-14）**: ヒストリカル検証2段階の結果（新規誤発動0件・正味
+$22,900改善方向）を踏まえ、`volatility_adjusted_stop_enabled: true`に変更し
paper環境で有効化。中間レビューは**2026-08-28頃**（cron登録済み:
`stock_swing_volatility_adjusted_stop_review_20260828`）。

**未実施（今後の検証課題）**:
- ヒストリカル検証はエントリー時点ATR固定・±3日窓universe近似・日次終値のみ
  という制約あり（詳細はスクリプト内docstring参照）。paper実測が最終確認となる
- ATR閾値のmultiplier範囲（0.5〜1.75）・sector_shockのrolling閾値（-5.0%）は
  初期値であり、08-28中間レビューでのpaper運用データに基づく再検討が必要

**やらないこと（今回のスコープ外、明示的に見送り）**:
```
❌ news_sentiment / macro_regime を exit判定に接続する
   （構造的崩壊シグナルレイヤーは新設しない。役割純化方針により長期資産防衛は
   ポートフォリオガードレール側の課題として残す）
❌ max_hold_daysの変更（数ヶ月保有前提への戦略変更は不採用）
❌ promotion_gateの自動ブロック化（既存のobservability-onlyのまま）
```

---

### 🟡 R4-v2: Signal and Confidence Calibration

**Status**: IMPLEMENTED_UNVERIFIED  
**Priority**: P2（R0-v2 完了後推奨）  
**統合元**: H7 + 旧R4  
**Target date**: 2026-08-17〜09-04（延期反映: リアルトレード開始が09-15に延期のため残項目着手期間を拡大）

**実装済み（未検証）**:
- R4-A: signal_strength 飽和原因調査 ✅
- R4-B: min_signal_strength 調整（confidence ≥0.40 filter） ✅

**検証結果（2026-08-05、実データ再集計）— R4-Bは実は大きく改善していた**:
旧記載は「R4-B後も改善なし」だったが、全 decisions（breakout_momentum系、2026選)を
実際に集計したところ誤りだったことが判明:
- R4-B実装前（〜07-01）: n=1,579 、飽和（strength≥09.99）**74.3%**
- R4-B実装後（07-02〜）: n=399、飽和 **14.8%**
- 07-02当日に明確な転換点（56%→30%）が確認でき〇07-07以降は10〜20%台で安定
- つまりR4-B（飽和閾値 0.10→0.20）は**意図通りの大幅改善を達成済み**だった。
  旧記載は途中集計ノイズ（集計期間がR4-B前後をまたぐ含み値だった可能性）による誤記載だったと推定

**未実装 / 未検証（修正後の残項）**:
- ~~R4-C: デサイル別 PF スクリプト~~ → **既に実装済み（`scripts/analyze_signal_strength_decile.py`）だったことを2026-08-14に確認**。
  n=86（closed かつ signal_strength 記録済み）で実行、decile 5（0.753–0.821）が PF=2.455 で最良、
  decile 1（0.476–0.533）が PF=0.020 で最悪。テスト13件を新規追加（未検証のまま放置されていた）。
  週次cron（`stock_swing_r4c_signal_strength_decile`、月曜09:00 JST）を新規登録し read-only で
  `reports/signal_strength_decile.json` を継続更新（learning制約: recommendation-only、自動閾値変更なし）
- ~~raw score / normalized score / cross-sectional percentile 保存~~ →
  **raw score / normalized score 部分は2026-08-17完了**。`breakout_momentum_strategy.py` /
  `event_swing_strategy.py` それぞれに `_calculate_raw_signal_score()`（clamp・regime補正前の
  素点、1.0超もそのまま保持）を新規追加し、`signal.metadata`に`raw_signal_score` /
  `normalized_signal_score`として両方保存（既存の`signal_strength`計算・フィルタ挙動は無変更）。
  既存の`FeatureSnapshotStore`配線（R11-E、08-15）経由で`data/feature_snapshots/`にも自動的に
  含まれる。テスト4件追加（1858 passed）。
  → **cross-sectional percentile部分も2026-08-17完了**。`signal_prioritization.py`に
  `annotate_cross_sectional_percentile()`を新規追加し、`paper_demo.py`のentry signal生成直後
  （`prioritize_buy_signals_v2()`呼び出し**前**）に配線。同一run内の全buy候補の中で
  signal_strengthが何パーセンタイル位置か（最弱=0.0、最強=1.0）を`signal.metadata`の
  `cross_sectional_percentile` / `cross_sectional_n`として保存。既存の`prioritize_buy_signals_v2`は
  signal_strength/confidenceを直接参照するため優先順位付け・セクターcap挙動は無変更
  （回帰テストで確認済み）。テスト6件追加（合計1863 passed）。`--dry-run`実run（43候補）でも
  エラーなく動作確認済み。
- confidence を calibration 可能な probability として定義（固定 0.85 多発の解消）—
  **未着手（意図的に）**。2026-08-17に`scripts/check_confidence_calibration_readiness.py`を
  新規作成し（`check_r8v2_ml_readiness.py`と同型パターン）、`data/decisions/*.json`の
  `evidence.sizing.confidence_multiplier`が記録されているdecision件数を集計するreadiness
  ゲートを実装。**実行結果（2026-08-17時点）: 08-14のconfidence_multiplier記録開始以降
  でも記録件数はわずか21件（目安100件の約1/5）でNOT_READY**。confidenceはsizingに
  直接影響するため、データ不足のまま定義を変えるのは未検証な行動変更となるため、
  本作業は意図的に実施しない。代わりに蓄積状況を可視化するscriptを実装し、
  08-25の`stock_swing_r4v2_progress_check_20260825`cronが自動的にこの進捗を検知できる
  ようにした。テスト10件追加（1873 passed）。
- feature snapshot を decision 時点の as-of データで immutable 保存 → **R11-E（08-15）で対応済み**
  （`FeatureSnapshotStore`経由、`paper_demo.py`の`decision_engine.process()`直後に配線）
- decile 別 expectancy / calibration curve 生成 → **expectancy部分は2026-08-17完了**。
  `scripts/analyze_signal_strength_decile.py`の`compute_decile_stats()`に`expectancy`
  （decile内の1トレード平均PnL、net_pnlをtrade件数で正規化した値）を追加。
  実行結果（08-17時点）: decile 5が最良（expectancy=+$832/trade）、decile 8が最悪
  （-$1,670/trade）。テスト3件追加（`test_analyze_signal_strength_decile.py`、
  全16件pass）。週次cron（`stock_swing_r4c_signal_strength_decile`）が既存の
  `reports/signal_strength_decile.json`にこのフィールドを自動的に含めるようになった
  （現状どのconsole/rendererからも未参照のスタンドアロンレポートのため、既存表示への
  影響なし）。calibration curve生成は未着手のまま残る

**Learning 制約**: recommendation-only。自動本番反映禁止。

#### R4-v2-Watchlist: 小サンプルウォッチリスト（可視化のみ、自動ブロックなし）

**Status**: IMPLEMENTED_UNVERIFIED（2026-08-05）  
**Priority**: P2（entry filterの可視化拡張、自動ブロックは含まないため即日実施可）

**背景**: stock_reduced gate（min_n=5）はPF<1.0の銘柄を自動ブロックするが、
n=2【4の小サンプルですでに大幅赤字の銘柄（IBM n=3 pnl=-$8,513 WR=0%、
ORCL n=3 pnl=-$8,306 WR=33%、PLTR n=2 pnl=-$6,712 WR=0%、CDNS n=2 pnl=-$5,940 WR=0%）
が検知されずに放置されていた。

**方針判断**: min_nを単純に下げると小サンプルでの誤判定リスクが上がるため、
**自動ブロックの拡張ではなく可視化の追加**という保守的なアプローチを採用。

**実装内容**:
- `entry_filter.py`: `get_small_sample_watchlist()` 新規関数
  - 対象: 非ETF、n=2〜4件（stock_reduced_min_trades未満）、net_pnl<0
  - `pf_gate_skip_symbols` は除外（既存のゲートと一貫）
  - **何もブロックしない（read-only observability）**
- `paper_demo.py`: run毎に計算して`entry_filter_stats`に格納
- `console_summary.py` / `console_renderer.py`: BUY STOP LISTの下に
  「⚠️ SMALL-SAMPLE WATCHLIST」としてコンソール表示
- テスト: `test_entry_filter.py` に8件新規追加

**今後の検討事項**: このウォッチリストに一定期間以上載った銘柄を手動で
`pf_gate_skip_symbols`の逆（deny-list）に追加するフローを次回検討する価値がある。

**2026-08-06 追記**: 上記実装はCLI/`paper_demo`のconsole summary（Telegram等）にのみ
配線されており、Web console（`console/app.py` + `dashboard_service.py`）には未配線で
ダッシュボードUIからは見えない状態だったことが判明。`DashboardService._get_small_sample_watchlist()`
を新規追加（既存の`_get_buy_stop_list()`と同パターン）し、`funnel.small_sample_watchlist`として
`/api/dashboard`経由で配信、UI（`console/ui/app.js`）にBUY STOP LISTと並ぶパネルとして追加（commit
`962fbc8`）。ブロック挙動の変更なし（read-only observability継続）。

---

### 🔴 R5-v2: Portfolio Risk and Promotion Gates

**Status**: REOPENED（実装は2026-08-14に大部分完了、閾値妥当性のpaper検証が残課題）  
**Priority**: P2（R0-v2 完了後）  
**統合元**: H5 + H7 + 旧R5  
**Target date**: 2026-08-17〜09-12（延期反映: 実装完了済みのため残期間は閾値検証専用）

**再 open 理由**:
- promotion gate が汚染台帳コホートを入力に使っている
- allocation policy が逆転していた（→ R2-v2 で訂正済み）
- market beta / sector/factor exposure / pairwise correlation / top-5 concentration 未実装
  → **2026-08-14 部分対応**: correlation cluster exposure（`correlation_cluster.compute_cluster_exposures()`、
  semis/cloud_software/hyperscale/cybersecurity等6クラスタ）は既にBUY自動ブロックとして実装済み
  （paper_demo `_filter_buys_by_cluster_cap()`）だったが、web dashboardに可視化が一切なかった
  （deny_reasonsテキスト経由の間接的な把握のみ）。`DashboardService._get_cluster_exposure()`を新規追加し
  `funnel.cluster_exposure`として配信、UI（`console/ui/app.js`）に「🔗 CORRELATION CLUSTER EXPOSURE」
  パネルとして追加（read-only observability、ブロック挙動の変更なし）。テスト9件追加。
  market beta（ポートフォリオ全体のbeta/alpha/Sharpeは`benchmark_service.py`に既存実装あり）と
  pairwise correlation / top-5 concentrationの明示的な promotion gate 連携は依然未実装のまま。
  → **2026-08-14 追加対応**: `src/stock_swing/risk/promotion_gate.py`を新規実装し、
  cluster_cap / top5_concentration（閾値40%、`AllocationConfig.correlated_cluster_cap_pct`と整合）/
  portfolio_beta（閾値1.5、`benchmark_service._interpret_beta()`の"High volatility"閾値と整合）/
  clean_cohort_pf（閾値1.0、n≥20）の4条件を組み合わせたfail-closed判定を実装（pure function、I/Oなし）。
  `scripts/check_go_no_go.py`に`check_promotion_readiness()`として配線し、`--save`時に
  「補足: R5-v2 Promotion Gate」セクションとしてレポートに追記（Required判定・GO/NO-GO最終判定・
  戻り値には一切影響しない、参考情報のみ）。実データ確認: top5_concentration=52.0%（閾値40%超過）、
  clean_cohort_pf=0.914（閾値1.0未達、n=228）、cluster_cap/beta（0.704）は両方pass。
  テスト33件追加（`test_promotion_gate.py` 27件 + `test_check_go_no_go_promotion.py` 6件）。
  → **2026-08-14 追加対応（第2弾）**: `src/stock_swing/risk/pairwise_correlation.py`を新規実装し、
  残っていたpairwise correlation（銘柄間の実相関係数計算）にも対応完了。専用の日次価格履歴ストアが
  存在しないため、`collect_data.collect_broker_bars()`が継続的に書き込んでいる
  `data/raw/broker/broker_{symbol}_*.json`（marketdata/bars エンドポイント）スナップショットを
  日付重複排除しながら蓄積・再構成する方式を採用（新規APIコール・新規データ収集なし）。
  Pearson相関係数を日次リターン系列から計算、閾値0.80以上のペアを検出。`promotion_gate.py`に
  5つ目の条件`pairwise_correlation`として統合、`check_go_no_go.py`が保有中銘柄について自動計算。
  テスト61件追加（`test_pairwise_correlation.py` 29件 + `test_promotion_gate.py`更新5件 +
  `test_check_go_no_go_promotion.py`更新2件）。実装中に相関係数計算の実バグを発見・修正
  （共分散を母集団分散`/n`で計算する一方`statistics.variance()`は標本分散`/(n-1)`を使っており、
  完全相関のはずが0.9286と出る不整合があった → `statistics.pvariance()`に統一して修正）。
  実データ確認: 保有27銘柄中、105ペア中6ペアが|相関|≥0.80で検出（ANET/CRDO=0.82、AVGO/CRDO=0.88、
  CRDO/MRVL=0.84、CRWD/PANW=0.84、INTC/MRVL=0.92、PANW/PATH=0.83）。
  **これでR5-v2の再open理由に挙げられた4項目（beta/cluster cap/pairwise correlation/
  top-5 concentration）は全て対応完了**（promotion gate自体の運用開始判断は別途ユーザー承認が必要）。

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
- manual clear 後 → `RECOVERY_PENDING` 表示 ✅（R0-v2-A、2026-07-22。`console/adapters/system_adapter.py` /
  `console/services/dashboard_service.py` に実装済み。下記「残未実装」に重複記載されていたのを
  2026-08-15のロードマップ棚卸しで訂正）
- mtime キャッシュ（毎回 CSV/JSON 全読込み防止）✅（H9、2026-07-27。`src/stock_swing/utils/
  mtime_cache.py` の `MtimeFileCache` / `_load_json_cached()` を `dashboard_service.py` の
  7箇所 + `remote_readonly_app.py` に配線済み。キャッシュヒット時 0.0ms 達成、MEMORY.md参照。
  「残未実装」に長期間記載され続けていたのを2026-08-15のロードマップ棚卸しで訂正）

**残未実装**:
- ~~config hash キャッシュ（config変更時の自動invalidation）~~ → **2026-08-17完了**。
  `DashboardService._load_yaml_cached()` を新規追加（既存の `_load_json_cached()` と同型の
  `MtimeFileCache` パターン）。`_get_asset_class_for_symbol()` / `_get_buy_stop_list()` /
  `_get_small_sample_watchlist()` の3箇所で毎回 `yaml.safe_load(reg_path.read_text())` を
  直接呼んでいたのをこのキャッシュ経由に変更（特に `_get_asset_class_for_symbol` はopen
  position件数分だけ毎リクエスト繰り返されていた）。mtime/size変更時のみ再パースする
  同一invalidation契約。テスト5件追加（キャッシュ変更検知含む、test_dashboard_service.py
  38 passed）。実データでの動作も確認済み
- WebSocket ← H9（state correctness 確認後。R7-v2と重複項目、2026-09以降着手検討）

**Performance SLO**: initial render p95 ≤2秒、cached rerun p95 ≤500ms（mtimeキャッシュ導入によりcachedrerunは既に0.0ms〜達成、H9進捗確認済み）

---

### 🟡 R7-v2: Data Reliability and Operational Edge Cases

**Status**: IN_PROGRESS（source SLA/FRED/ニュース感情は2026-08-14完了。残るのはWebSocketのみ）  
**Priority**: P2（R0-v2 完了後 R3/R4/R6 と並行可）  
**統合元**: H8 + 旧R7  
**Target date**: 2026-08-03〜08-14（完了項目）、WebSocketは2026-09以降（延期で確保できた期間で着手検討）

**完了 (VERIFIED_COMPLETE)**:
- R7-A: Corporate Action 台帳 + 自動検知 ✅

**未実装** → **2026-08-17 ロードマップ棚卸しで判明: 両項目とも実際は実装済みだった（記載漏れ）**:
- ~~source ごとの SLA + quality report~~ → **VERIFIED_COMPLETE（実装済み、記載漏れを本日訂正）**。
  `console/adapters/system_adapter.py` の `_check_source_sla()`（2026-08-14, R7-v2-A）で
  4項目全て実装済み: broker position/order ≤30秒（`_check_broker_tracker_freshness`）/
  intraday quote market open中 ≤2分（`_evaluate_intraday_quote_sla`）/ daily bar 前営業日
  close確定後（`_evaluate_daily_bar_sla`）/ sector benchmark exit判断時点と同じas-of
  （`_evaluate_sector_benchmark_sla`）。テスト（`test_system_adapter_session_sla.py`他）で
  カバー済み。コード実装は08-14に完了していたが、本セクションの「未実装」記載が
  更新されずに残っていた（R7-B/C WebSocketの記載漏れと同種のドキュメント遅延）
- ~~`event_time` / `available_at` / `ingested_at` / `source` / `revision_id` / `quality_status`
  を canonical schema へ追加~~ → **VERIFIED_COMPLETE（実装済み、記載漏れを本日訂正）**。
  `src/stock_swing/core/types.py` の `RawEnvelope` dataclassに該当フィールド全て定義済みで、
  `collect_data.py` の `_write_raw_snapshot()`（全7ソース: finnhub/broker/broker_bars/
  massive/fred/sec/earnings_calendarが共通利用）経由で書き込む全raw snapshotに反映されている
  ことを実データ（`data/raw/{broker,finnhub}/*.json`）で確認
- ~~Massive client の connection pool 共有（`Connection pool is full` 解消）~~ → **VERIFIED_COMPLETE**（2026-07-23, commit `399fe2f`。本節が長期間 未実装 のまま記載され続けていたのを 2026-08-07 訂正）
- ~~market closed 時は maintenance job 以外早期終了~~ → **VERIFIED_COMPLETE**（2026-08-14）: `market_guard.should_skip_outside_market_hours()` を新規実装し、weekday/holiday判定に加えてET dead zone（after-hours終了20:00〜pre-market開始04:00）中も早期終了するよう拡張。`collect_data.py` に `--require-market-session` フラグを追加し、`stock_swing_news_collection` cron（0 */4 * * *、終日実行）に適用。maintenance job（reconcile_orders等）やhistorical/bulk source（massive）は対象外のまま。テスト13件追加（全39件 pass, 回帰なし）
- ~~macro (FRED) の regime lineup（現在 unknown のまま）~~ → **VERIFIED_COMPLETE**（2026-08-14）: `collect_data.collect_fred()` を not_implemented スタブから実装に変更（CPIAUCSL/UNRATE/T10Y2Y/ICSA を FredClient 経由で取得、`config/sources/fred.yaml` の `not_implemented: false` に変更）。`MacroRegimeFeature` を単一指標（CPI水準 vs 固定閾値320、recession検知不可能だった旧実装）から CPI YoY / UNRATE trend / T10Y2Y yield curve inversion / ICSA claims trend の4指標合成判定に書き換え。`paper_demo.py` に FRED raw snapshot ロード配線を追加（best-effort、失敗時は従来通り price-based regime にフォールバック）。テスト35件追加（macro_regime_feature 16件 + collect_fred 6件 + fred/regime整合性1件、既存 test_collect_data_fix001.py の stub 前提テスト1件を実装後の挙動に更新）
- ~~R7-B/C: WebSocket / ニュース感情評価~~ → **2026-08-14 記載訂正**: この行は
  2026-07時点の記載が2026-08-08のPlan D実装後も更新されずに残っていた（ドキュメント上の
  記載漏れ、実装漏れではない）。ニュース感情評価は Plan D として既に **shadow mode 実装・
  稼働済み**（`src/stock_swing/risk/news_sentiment.py`、2026-08-08、テスト26件、
  shadow log 331件蓄積中、次の中間レビューは2026-08-21予定、上記「Plan D」セクション参照）。
  **WebSocket のみが真に未実装のまま残存**（R6-v2の同項目と重複、H9 state correctness
  確認後に着手予定。ポーリングベースの現行アーキテクチャから配信方式を変更する規模の大きい
  作業のため、専用セッションでの着手が妥当と判断し本日は見送り）

---

### 🔵 R8-v2: Learning and ML

**Status**: BLOCKED_BY_DATA  
**Priority**: P3（R0-v2 完了 + clean labels ≥300 後）  
**統合元**: H7 + 旧R8  
**Target date**: 2026-10 以降

**開始条件**:
- R0-v2〜R4-v2 の acceptance criteria をすべて満たすこと
- clean joinable outcomes ≥300（単純 calibration 開始）
  - **2026-08-14 定義明確化**: 「clean」とは`PnlTracker.get_attribution_
    quality_breakdown()`の`attributable`バケット（起源追跡可能なトレード）
    を指し、生の`total_closed`件数ではない。判定は
    `scripts/check_r8v2_ml_readiness.py`を正式な基準とする（穴4対応、
    2026-08-14時点: attributable=25/300）
- ML training は clean labels ≥1,000 が原則（同様にattributableベース）
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

2026-08-14（金）    👤 リアルトレード開始を 08-20 → **09-15** に再延期（ユーザー指示）
                   理由: R5-v2 promotion gate（beta/cluster/相関/集中度）実装完了直後で
                   閾値の妥当性検証が未実施、Plan B/C/D/E の中間レビュー（08-21予定）後に
                   もう1サイクル観測期間を確保するため。以降のスケジュールは全て 09-15 起点で再編。

2026-09-15以降 🚀（予定）  リアルトレード開始（50%サイズ）

2026-08-05          ✅ R3-v2-Stop  tiered min_hold v2（offset_pct再設計・再有効化、commit 27a8742）

2026-08-05          ✅ R3-v2-Breakeven  staged floor（段階的floor導入）

2026-08-05          ✅ R3-v2  sector_shock historical replay 111件蓄積開始（目標100件達成）

2026-08-19頃          ✅ R3-v2-Stop 中間レビュー: post-exit drift再分析で「正しい止損率」改善確認

2026-09-05          🔲 R3-v2-Breakeven 中間レビュー: staged floorのpaper実測での改善確認（08-05導入から1ヶ月後）

2026-08-03〜08-14  R3-v2    exit replay / sector shock shadow（R0-v2 完了後のみ）
                   R7-v2    data SLA / source lineage
                   ✅ R7-v2  source SLA 完全実装（quote/daily bar/sector benchmark、08-14）
                   ✅ R7-v2  macro (FRED) regime lineup 実装（08-14）
                   ✅ R4-v2  signal strength decile分析 検証・週次cron化（既存実装の発見、08-14）
                   ✅ R5-v2  cluster exposure可視化 + promotion gate（beta/top5/相関/clean PF）実装（08-14）

2026-08-17〜08-28  R4-v2    残: raw/normalized score保存、confidence calibration、feature snapshot保存
                   R5-v2    残: promotion gate 5条件の閾値妥当性検証（paper観測ベース）

2026-08-19（水）    ✅ R3-v2-Stop 中間レビュー: offset_pctベースtiered min_hold v2の
                         post-exit drift再分析（cron登録済み: stock_swing_r3v2_stop_tiered_minhold_review_20260819）

2026-08-21（金）    ✅ R9 Plan B/C/D/E 中間レビュー・昇格判断（手動実施。当初「cron登録済み」
                         と記載していたが実際にはジョブ未登録だったことが判明したため手動で
                         実施し、次回分のcronを新規登録: stock_swing_r9_planbcde_mid_review_20260904）
                         ・ volatility_gate / distance_from_high / news_sentiment / rsi_diagnostic
                           各shadow logをレビューし、shadow継続 / paper_ab昇格 / 見送りを判断

2026-08-24〜09-04  R5-v2    promotion gate 5条件（cluster_cap/top5_concentration/portfolio_beta/
                         clean_cohort_pf/pairwise_correlation）を約2週間 paper 観測し、
                         各閾値が偽陽性/偽陰性を出していないか実トレード結果と突き合わせ
                   R7-v2    残: event_time/available_at等canonical schema拡張（R7-Aの残項目）

2026-09-05（土）    🔲 R3-v2-Breakeven 中間レビュー: staged floorのpaper実測での改善確認
                         （08-05導入から1ヶ月後、cron登録済み: stock_swing_breakeven_staged_floor_review）

2026-08-23         ✅ 監査対応完了: docs/audit_fixes_20260823/ の6パッチ（console_summary鮮度、
                         equity_bridge quarantined_pnl、broker_bars pagination、
                         pairwise_correlation staleness、check_go_no_go 3条件形骸化、
                         f8 expectancy/max_drawdown）をユーザー承認の上12:45 JSTに本番
                         適用。適用後フルテストスイート2065 passed / 2 skippedと
                         --dry-run/check_go_no_go.py実データ動作を確認済み
                         （詳細: docs/audit_fixes_20260823/README.md）。
                         🔲 残課題: equity_bridgeの$168,869.89未説明差分の運用判断
                         （quarantine再分類 vs tolerance引き上げ）はPre-Launch Gate Review
                         までに実施

2026-09-08〜09-12  🔲 Pre-Launch Gate Review（第2弾）
                         ・ R3-v2-Stop/Breakeven/R9 Plan B-E/R5-v2 promotion gate、全レビュー結果を統合
                         ・ 2026-08-23監査の6パッチは適用済み。equity_bridge $168,869.89差分の
                           運用判断（quarantine再分類 or tolerance明示引上げ）をここで行う
                         ・ scripts/check_go_no_go.py --save で Required 7条件 + 補足 promotion gate を再確認
                           （パッチ適用済みなのでconsole_summary_freshness/paper_3day_confirmation/
                           cron_jobs_healthyは実データを反映済み。pairwise_correlationが
                           新規データ蓄積後にavailable=Trueになっているかも確認）
                         ・ 09-15 リアルトレード移行の最終可否判断材料をまとめる

2026-09-12（土）    🔲 Go/No-Go 最終再確認（09-15直前）
                         ・ Required 7条件が引き続き✅か再確認
                         ・ promotion gate（top5_concentration/clean_cohort_pf等）の
                           09-15時点の状態を記録し、リアルトレード開始判断の参考情報とする
                         ・ equity_bridge の unexplained_diff（2026-08-23監査時点$168,874相当の
                           quarantine起因ギャップ）が説明・解消されているか確認

2026-09-15以降 🚀（予定）  リアルトレード開始（50%サイズ）

2026-09以降        R7-v2    WebSocket化（延期で確保できた期間を活用し着手検討。
                         現行ポーリングアーキテクチャからの移行は規模大、専用セッション推奨）

2026-10+           R8-v2    ML（clean labels ≥300/≥1,000到達後、R0-v2〜R4-v2完了が前提）
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
| 🟡 P2 | R4-v2 | IMPLEMENTED_UNVERIFIED | R0-v2 完了推奨後。decile分析は2026-08-14検証・週次cron化済み |
| 🔴 P2 | R5-v2 | REOPENED | 実装は2026-08-14大部分完了（cluster/beta/相関/集中度）。残: 閾値のpaper検証（09-15延期で確保した期間で実施） |
| 🟢 P2 | R7-v2 | IN_PROGRESS | source SLA/FRED/ニュース感情は2026-08-14完了。残: WebSocketのみ（09月以降） |
| 🔵 P3 | R8-v2 | BLOCKED_BY_DATA | 10月以降 |

**2026-08-14 追記**: リアルトレード開始が 08-20 → **09-15** に延期（ユーザー指示）。
延期で確保できた約4週間を R4-v2/R5-v2 残項目の実装検証と R9 Plan B/C/D/E の
中間レビュー・追加観測に充当する。詳細スケジュールは上部「次のアクション（直近）」の
2026-08-14以降の行を参照。

**2026-08-15 追記（ロードマップレビューで発見したリスク、明記のみ・対応は不要）**:
R3-v2のsector_shock A/Bは、活性化条件（forward valid stop-trigger shadow ≥10件）が
**09-15のリアルトレード移行までに達成できない見込み**（2026-08-15時点でshadow log 41件中
有効なショック分類は1件のみ。原因は実際のセクター全体ショック自体が監査期間中ほとんど発生していないことで、
運用側でコントロールできない）。つまり**sector_shock_holdによるstop_loss改善効果は、
09-15時点で未検証のままリアルトレードに持ち込まれる**。Required 7条件には含まれないため
ブロッカーにはならないが、「未完了のまま移行するリスクを許容するか」はこれまで明示的に
文書化されていなかった。09-10のPre-Launch Gate Reviewの判断材料に、この点（sector_shock
保護なしでstop_lossが本番投入されることを認識した上でのご/no-go判断）を明示的に含めること。
対策は存在しない（人工的にショックを促進するべきではないと既に2026-08-05に判断済み）。

---

**2026-08-23 追記（Go/No-Go判定基盤監査、ユーザー依頼）**:
`scripts/check_go_no_go.py`のRequired 7条件中3条件（cron_jobs_healthy /
paper_3day_confirmation / 鮮度チェックの不在）が実質恒久PASS化していたこと、
及び`paper_demo.py`の無アクションrunがconsole_summaryを更新しないバグにより
実際に08-22/08-23の2日間consoleが凍結していたことが判明。加えてequity_bridgeの
`quarantined_pnl`固定値0.0バグにより$168,874の未説明差分が隠されていたことも
判明。詳細と修正パッチ（6件）は上記「2026-08-23 監査」節及び
`docs/audit_fixes_20260823/README.md`を参照。**同日 12:45 JST、ユーザー承認により
全6件を本番適用済み**（フルテストスイート2065 passed / 2 skipped確認済み）。
残るequity_bridge $168,869.89差分の運用判断はPre-Launch Gate Reviewまでに実施。

---

## 2026-08-14 ロードマップ穴分析（客観的レビュー、ユーザー依頼）

**背景**: 「現在の改善計画で改善が見込めない部分や穴になる部分」を客観的に分析
するようユーザーから依頼を受け、既存ロードマップ・実データを再検証した結果、
以下6件の構造的な穴を発見。優先度順に対応する。

**総括（全6件対応完了、2026-08-14）**: 発見した6件全てに実装・実データ検証・
テストで対応完了。新規スクリプト5本（`check_r8v2_ml_readiness.py`、
`capture_promotion_gate_snapshot.py`、`check_quarantine_trend.py`、
既存2本への機能追加）、`PnlTracker`/`PositionSizingResult`/`DecisionRecord`への
新規フィールド追加、テスト63件追加。特に穴1（起源不明トレードがPFを歪めている）
と穴3（confidence_multiplierが未記録だった）は、ロードマップ上の複数の判断
基準（R4-v2/R5-v2/R8-v2）が気づかぬうちに誤った前提で運用されていたことを
明らかにした点で重要度が高い。新規cron4件登録（うち2件は評価完了後に自動削除）。

### 🔴 穴1: 戦略ポートフォリオが実質1本しかなく、起源不明トレードが全体PFを歪めている
**対応状況**: ✅ **VERIFIED_COMPLETE（2026-08-14）**

**発見内容**: closed trade 228件中、`original_strategy_id`別内訳:
```
broker_reconstructed: 197件（意思決定ログとの紐付けなし、ブローカー生履歴からの逆算）
breakout_momentum_v1:  25件（実際に戦略ロジックを通過）
reconciled_from_broker: 6件（reconcile_ordersのstale position復旧、紐付けなし）
```
実データで両者のPFを分離計算すると:
```
attributable（追跡可能）PF=1.317, net +$4,951, n=25
untracked_origin（起源不明）PF=0.882, net -$23,514, n=203
overall（ブレンド） PF=0.914, net -$18,563, n=228
```
**重要な含意**: 従来「overall PF=0.914」として扱ってきた数字は、実際に機能している
戦略（PF 1.317）を、追跡不能な過去ポジション（PF 0.882）が押し下げているだけだった
可能性が高い。R4-v2のdecile分析・R5-v2のclean_cohort_pf基準など、PF/WRベースの
判断は全てこの偏りを踏まえて解釈する必要がある。

**実装内容**:
- `PnlTracker.get_attribution_quality_breakdown()`新規追加
  - `UNTRACKED_ORIGIN_STRATEGY_IDS = {"broker_reconstructed", "reconciled_from_broker"}`
    に該当するトレードを`untracked_origin`、それ以外を`attributable`として分離集計
  - `original_strategy_id`が欠損している場合は`strategy_id`にフォールバック
- `ConsoleSummary` / `console_renderer.py`に`ATTRIBUTION QUALITY`セクション追加
  （`asset_class_breakdown`と同じ表示パターン、ledger INVALID時はNOT_VALID表示）
- `paper_demo.py`の2箇所の`ConsoleSummary.build()`呼び出しに配線
- テスト14件追加（`test_attribution_quality_breakdown.py`）、実データ確認済み
- `--dry-run`でconsole出力に正しく表示されることを確認

**今後の運用**: R4-v2/R5-v2のPF系判断は、今後`attribution_quality_breakdown`の
`attributable`バケットも必ず併読する。ロールバック不要（read-only observability、
既存の`asset_class_breakdown`と並列表示するのみで挙動変更なし）。

### 🔴 穴2: R5-v2 promotion gateの「観測後の分岐条件」が未定義
**対応状況**: ✅ **VERIFIED_COMPLETE（2026-08-14）**

top5_concentration=52.0%（閾値40%超過）、clean_cohort_pf=0.914（閾値1.0未達）は
**08-14計画時点で既に不合格**。08-24〜09-04の2週間paper観測を予定していたが、
「観測して何がどうなったら昇格/見送りか」の判断ルールが未定義だった問題を解消。

**実装内容**:
- `scripts/capture_promotion_gate_snapshot.py`新規作成
  - `check_go_no_go.py`の`check_promotion_readiness()`を再利用し、日次で
    promotion_gate 5条件のスナップショットを`data/audits/promotion_gate_snapshots/`
    に保存
  - `--evaluate`モード: 蓄積したスナップショットから3つの連続指標
    （top5_concentration/clean_cohort_pf/portfolio_beta）のトレンドを分類
    （cluster_cap/pairwise_correlationはbool/リスト型のためトレンド分析対象外）
- **明示的な分岐条件**（`classify_trend()`）:
  - **(a) IMPROVING & ON TRACK**: 閾値方向に改善しており、最終値が閾値の
    10%以内 → 観測継続、gate変更不要
  - **(b) STUCK**: 観測期間中に値がほぼ動いていない（相対変化3%未満）→
    新規BUY集中抑制など能動的対応を検討すべきと明示的に推奨
  - **(c) WORSENING**: 閾値から遠ざかる方向に悪化 → 09-15移行判断前の
    即時介入を推奨
  - 既に閾値内なら**passing**として最初から報告
- 日次スナップショット取得cron新規登録: `stock_swing_promotion_gate_snapshot_daily`
  （08-24〜09-04観測期間、JST 09:30毎日）
- トレンド評価cron新規登録: `stock_swing_promotion_gate_trend_evaluation_20260905`
  （09-05、`--evaluate --since 2026-08-24`実行、評価後に日次取得cronを自動削除）
- テスト22件追加（`test_capture_promotion_gate_snapshot.py`）、実データでの
  スナップショット取得動作確認済み（cluster_cap ✅ / top5_concentration ❌51.9%
  / portfolio_beta ✅0.704 / clean_cohort_pf ❌0.914 / pairwise_correlation ❌6ペア）

### 🟡 穴3: R4-v2「confidence較正」が、confidence自体の利用実態を棚卸しせず着手予定
**対応状況**: ✅ **VERIFIED_COMPLETE（2026-08-14）**

**棚卸し結果**: `confidence`値の生成元は3パターン
（`confidence=signal_strength*0.85`（breakout_momentum）/ `confidence=0.85`固定
（simple_exit v1）/ `confidence=0.90`固定（simple_exit_v2、exit全般））。
実際の利用先は`PositionSizingPolicy.size()`のみで、以下のtier分岐でsizingの
`confidence_multiplier`を決定していた:
```
confidence >= 0.80 → multiplier = 1.2（sizing拡大）
confidence <  0.60 → multiplier = 0.7（sizing縮小）
それ以外           → multiplier = 1.0（変化なし）
```
**重大な発見**: この`confidence_multiplier`は実際にsizingへ影響を与えていた
にもかかわらず、`PositionSizingResult`にも`DecisionRecord.evidence.sizing`にも
**一切記録されていなかった**。つまりR4-v2の「confidence較正」計画は、そもそも
較正対象の値が過去の意思決定ログに残っておらず、着手時点でヒストリカル分析
すら不可能な状態だった。

**実装内容**:
- `PositionSizingResult`（`position_sizing.py`）に`confidence_multiplier`
  フィールドを新規追加、`PositionSizingPolicy.size()`の戻り値に含める
- `DecisionRecord.sizing`（`PositionSizingSnapshot`、`decision_engine.py`）に
  同フィールドを追加
- `PaperExecutor._calculate_position_size()`のevidence dict・sizing snapshot
  両方に配線（`paper_executor.py`）
- テスト7件追加（`test_confidence_multiplier_recording.py`）
  - テスト作成中に実装の仕様を確認: `confidence=None`時は`confidence_multiplier
    =1.0`（中立値）として記録される。「データなし」と「confidence=0.60〜0.80の
    中間tier」は`confidence_multiplier`単体では区別できないため、今後の較正分析
    では`confidence`フィールドと併読する必要がある（テストにコメントで明記）
- 実データ確認: `--dry-run`でエラーなく動作、既存の`before_multiplier_qty`等と
  同じ evidence 経路に正しく記録されることを確認

**今後の運用**: この変更以降に生成される決定ログから、confidence_multiplierの
実際の分布・sizing影響を蓄積できるようになった。R4-v2の「confidence較正」は
**この蓄積が一定量（目安: 100件程度）に達してから着手**するのが妥当。
既存の過去ログ（本変更前）にはこのフィールドがないため、遡及分析は不可。

### 🟡 穴4: R8-v2「clean labels」定義が起源追跡可能性を問うていない
**対応状況**: ✅ **VERIFIED_COMPLETE（2026-08-14）**

「clean joinable outcomes ≥300」「clean labels ≥1,000」は従来、生の`total_closed`
件数で判定していたが、これは「起源追跡可能か」を問うていなかった。穴1で判明した
通り、closed trade 228件中203件が`untracked_origin`（起源不明）であり、単純に
`total_closed`が増えるのを待つだけでは、300件到達時点でも大半がattributable
でない可能性がある。

**実装内容**:
- `scripts/check_r8v2_ml_readiness.py`新規作成
  - `PnlTracker.get_attribution_quality_breakdown()`の`attributable`バケット
    件数で calibration（≥300）/ ML training（≥1,000）の準備状況を判定
  - `--save`で`reports/r8v2_ml_readiness.json`に結果保存、未達時は非0終了
- **実データ確認（2026-08-14時点）**:
  ```
  attributable（起源追跡可能）: 25件
  untracked_origin（起源不明）: 203件
  total_closed:               228件
  attributable比率:            11.0%
  → calibration開始条件（≥300）: ❌ 25/300（total_closed基準の228/300とは
    大きく乖離、実際にはまだ遠い）
  ```
- テスト8件追加（`test_r8v2_ml_readiness.py`）、実データ整合性確認込み

**今後の運用**: R8-v2着手判断は今後この`check_r8v2_ml_readiness.py`の結果を
基準とする（`total_closed`ベースの旧判断基準は廃止）。09-15以降のリアルトレード
移行で新規attributableトレードが蓄積されるスピードを見て、R8-v2着手時期
（現状目安10月以降）を再評価する。

### 🟢 穴5: sector_shock_hold ローリング判定導入後の活性化条件（shadow≥10件）が未再検討
**対応状況**: ✅ **VERIFIED_COMPLETE（2026-08-14、実データ検証込み）**

**検証内容**: `scripts/sector_shock_historical_replay.py`に`--rolling`オプションを
追加し、本日実装したローリング3日判定（sector_shock_hold.py）を過去103件の
stop_lossトレードに再適用して、単日判定版と分類結果を比較した。

**実データ検証結果（意外な結果）**:
```
単日判定版:   有効ショック件数（sector_shock_hold + relative_weakness_exit）= 1件
ローリング版: 有効ショック件数（同上）= 1件
103件中、分類が変化したトレード: 0件
```
**結論**: 本日のローリング判定追加は、実運用（06-08 LRCXケース）では単日判定が
見逃したショックを正しく検知したことを個別に確認済みだが、**この過去103件の
historical replayデータセットには単日判定とローリング判定の差が出るパターンが
たまたま存在しなかった**。つまり「ローリング判定でshadow検知頻度が有意に増える」
という当初の仮説は、少なくともこの過去データでは支持されなかった。

**活性化条件（forward valid stop-trigger shadow≥10件）への含意**: この閾値を
今すぐ変更する根拠はない。ローリング判定の効果は、過去データの再分類ではなく
**今後の実運用（forward）でのshadow蓄積を待って評価すべき**。08-21のR9 Plan
B/C/D/E中間レビュー時に、2026-08-14以降の`data/sector_shock_shadow_log.jsonl`
新規エントリを確認し、ローリング判定が実際に新規検知を増やしているか確認する
（既存レビューの一部として自然に組み込み可能なため、新規cronは追加しない）。

**実装内容**:
- `load_benchmark_rolling_returns_by_date()`をhistorical replayスクリプトに追加
  （`benchmark_returns.csv`の`return_3d`列を読み込み）
- `--rolling`フラグで既存ロジックと並行実行可能に（デフォルト動作は変更なし、
  別ログファイル`sector_shock_historical_replay_log_rolling.jsonl`に出力）
- テスト4件追加（`test_sector_shock_historical_replay_rolling.py`）

### 🟢 穴6: quarantine 102件の増減トレンドが未追跡
**対応状況**: ✅ **VERIFIED_COMPLETE（2026-08-14）**

**実データ確認**: quarantine 101件全ての`entry_time`が2026-07-22以前
（R0-v2-B台帳修復作業の頃）。つまり**08-01以降、新規quarantineは0件**——
現状は完全に過去の一括修復バッチの残存であり、日々のトレードで新規発生し
続けている兆候はない。ただしこれまでは「都度手動確認」でしかこの事実を
確認できておらず、継続的な監視の仕組みがなかった。

**実装内容**:
- `scripts/check_quarantine_trend.py`新規作成
  - quarantine件数 + 最新quarantine対象の`entry_time`をスナップショットとして
    `data/audits/quarantine_trend_history.jsonl`に蓄積
  - 前回スナップショットとの比較で`baseline`/`stable`/`growing`/`decreased`
    を判定。**件数が変わらなくても、新しい`entry_time`のquarantineが1件でも
    追加されれば`growing`として検知**（件数のみの比較では、同時に1件解消・
    1件新規発生してもすり抜けてしまう問題を回避）
  - `growing`判定時は非0終了（cron監視で異常検知可能）
- 週次cron新規登録: `stock_swing_quarantine_trend_weekly`（月曜09:00 JST）
- テスト11件追加（`test_check_quarantine_trend.py`）、実データでベースライン
  スナップショット取得済み（101件、最新entry_time=2026-07-22）

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
| check_go_no_go.py mismatch誤検知 | (未発見) | **修正済み（2026-08-05）**。生のhealth.broker_tracker_mismatch_count（G1-v2-d等のlag除外前）を見ていたため、除外済みmismatch=0でもfalse NO-GOを出していた。broker_tracker_diff.real_mismatch_countを優先使用するよう修正。テスト5件追加（tests/unit/test_check_go_no_go.py） |
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

---

## R9: NBIS 高掴みインシデント follow-up（2026-08-07）

**背景**: 2026-08-04〜06、NBIS（3ヶ月年率換算リターン標準偏差 ~130%、当時
52週高値$299.86から>25%下落済み）に対し、36時間で3回連続BUY（$221〜226
レンジ）が発生。いずれも「5日モメンタム+12〜31%」の強気シグナルで発火した
が、実態はショック後の反発（デッドキャットバウンス）だった可能性が高い。
08-06 19:55 UTC に3ロット一括 stop_loss、合計 **-$7,774**。

ユーザーとの協議で3方向の対策を「全部同時」ではなく **段階的ロールアウト**
（Plan A即時実装 → Plan B/Cは shadow/observability-only で検証してから
昇格判断）で進めることに合意。理由: Plan Aは局所的・低リスクで効果測定が
容易な一方、Plan B（ボラ上限ゲート）・Plan Cは既存の勝ちトレード（同じ
高ボラ・大幅下落プロファイルの NBIS 06-25 クローズ +$5,288 など）を巻き
込むリスクがあり、無検証での即時本番反映は avoid（`やらないこと` 節の
精神と整合）。

### Plan A: 同一銘柄クールダウン（実装完了・有効化済み）

- **モジュール**: `src/stock_swing/risk/same_symbol_cooldown.py`
- **ロジック**: 既存オープンポジションの直近エントリー時刻から
  `cooldown_hours`（デフォルト24h）以内は同一銘柄への追加BUYをブロック
  （複数ロットがある場合は最新ロットの時刻を使用）
- **wiring**: `paper_demo.py` の entry_filter（rolling PF gate）通過後、
  guardrail fail-closed チェックの直前に追加
- **無効化**: `SAME_SYMBOL_COOLDOWN_DISABLED=true`
- **閾値変更**: `SAME_SYMBOL_COOLDOWN_HOURS`（デフォルト24）
- **status**: ✅ **VERIFIED_COMPLETE**（2026-08-07、commit予定）。
  テスト17件（正常系/境界値/複数ロット/欠損データ/disabled/config）

### Plan B: ボラティリティ上限ゲート（shadow mode で稼働開始）

- **モジュール**: `src/stock_swing/risk/volatility_gate.py`
  + `src/stock_swing/risk/finnhub_metric_lookup.py`（共通の Finnhub
  `stock/metric` スナップショット読み込みヘルパー、Plan Cと共用）
- **ロジック**: Finnhub `3MonthADReturnStd`（3ヶ月年率換算リターン標準偏差）
  が閾値超の銘柄BUYを「ブロック相当」として分類・ログするが、
  **shadow モードでは一切ブロックしない**（sector_shock_hold.py と同じ
  ロールアウトパターン）
- **初期閾値**: `VOLATILITY_GATE_MAX_3M_STD_PCT=120.0`（2026-08-07時点の
  ユニバース全44銘柄スキャンで GOOGL ~38% 〜 NBIS ~133% の分布を確認。
  自然な閾値は見えず、まず現状最も極端な1銘柄のみを判定対象とする保守的
  な初期値。要再検証）
- **モード**: `VOLATILITY_GATE_MODE`（shadow=デフォルト / paper_ab / active
  / disabled）。**active への昇格はユーザー承認必須**
- **shadow ログ**: `data/volatility_gate_shadow_log.jsonl`
- **wiring**: `paper_demo.py` の DecisionEngine.process() 直後、BUY
  アクションのみ評価
- **status**: ✅ shadow mode 実装・有効化済み（2026-08-07）。実データで
  NBIS を正しく検知済み（3m_std=132.6% > cap=120.0%）
- **次のマイルストーン**:
  - **2026-08-14〜21 (1週間分shadowログ蓄積)**: `data/volatility_gate_shadow_log.jsonl`
    に十分な件数（目標: would_block=True 少なくとも5件以上）が溜まったら、
    その期間の実トレード結果（勝敗）と突き合わせ、閾値が偽陽性で勝ちトレード
    を潰していないか確認
  - **2026-08-21頃 中間レビュー**: shadowログ集計結果をレビューし、
    (a) 閾値を現状維持/調整、(b) `paper_ab` へ昇格、(c) 見送り、を判断
  - **2026-08-14 追記**: リアルトレード開始が09-15に延期されたため、08-21レビューで
    `paper_ab`昇格判断が出た場合、09-15までに約3.5週間のA/B観測期間を確保できる
    （従来の08-20開始スケジュールでは目標20件のA/B比較を待つ余裕がほぼなかった）
  - **paper_ab 移行後 最低20件のA/B比較後**: `active` への昇格判断（要ユーザー承認）

### Plan C: 52週高値乖離診断（observability-only、戦略には未接続）

- **モジュール**: `src/stock_swing/risk/distance_from_high.py`
  （+ `finnhub_metric_lookup.py` 共用）
- **ロジック**: 52週高値からの下落率が閾値以下（デフォルト-20%以下）かつ
  モメンタムが閾値以上（デフォルト+10%以上）の BUY を「反発バウンス候補」
  として **ログするのみ**（signal_strength・sizing・exit閾値には一切接続しない）
- **接続しない理由**: signal_strength は sizing と exit conviction tier
  （simple_exit_v2_strategy.py の HIGH/LOW 閾値分岐）の両方を駆動している
  ため、ここに直接ペナルティを組み込むと、52週高値付近の正当なブレイク
  アウトまで無検証で巻き込むリスクがある。small_sample_watchlist と同じ
  「まず可視化のみ」パターンを踏襲
- **診断ログ**: `data/distance_from_high_log.jsonl`
- **無効化**: `DISTANCE_FROM_HIGH_DISABLED=true`
- **wiring**: `paper_demo.py` の DecisionEngine.process() 直後、BUYの
  momentum（CandidateSignal.metadata）+ Finnhub 52WeekHigh を突き合わせ
- **status**: ✅ observability実装・有効化済み（2026-08-07）。実データで
  NBIS のインシデントプロファイル（-36.7% below high, momentum +11.9%）を
  正しく検知済み
- **次のマイルストーン**:
  - **2026-08-21頃**: Plan Bの中間レビューと合わせて
    `distance_from_high_log.jsonl` の bounce_candidate 件数とその後の
    値動き（反発 vs さらなる下落）を確認。相関が弱ければこの診断軸は
    見送り、強ければ Plan B 同様の shadow→paper_ab 検討に進める
  - 本モジュールは現時点で **戦略ロジック（signal_strength/exit閾値）へ
    接続する計画なし**。あくまで診断データの蓄積が先

### 実装状況まとめ

| Plan | 内容 | モード | ブロック有無 | 次のレビュー |
|---|---|---|---|---|
| A | 同一銘柄24hクールダウン | active（有効） | ブロックする | 不要（完了） |
| B | ボラ上限ゲート | shadow | ブロックしない | 2026-08-21 |
| C | 52週高値乖離診断 | observability | ブロックしない | 2026-08-21 |

**テスト**: 3モジュール合計 69件追加（same_symbol_cooldown 17件 /
finnhub_metric_lookup 11件 / volatility_gate 19件 / distance_from_high
22件）。フルテストスイート: 1441 passed / 2 skipped（既存の無関係な
2件の失敗のみ、変更前から再現確認済み）。

### 1週間観測結果（2026-08-14, 2026-08-07〜08-13 US）

- **Plan B shadow log**: `data/volatility_gate_shadow_log.jsonl`
  380件中 **would_block=true 21件**（5.5%）。
  内訳は **SMCI 16件 / NBIS 5件**。
- **Plan C observability log**: `data/distance_from_high_log.jsonl`
  380件中 **is_bounce_candidate=true 132件**（34.7%）。
  対象は 12 銘柄（ADBE / CIEN / CRDO / CRM / IBM / INTC / MRVL / NOW /
  ORCL / PATH / PLTR / SMCI）。
- **closed trade 照合（偽陽性チェック）**:
  - Plan Bで would_block=true だった **NBIS / SMCI** は、観測期間中
    （`entry_time >= 2026-08-07`）の closed trade が
    `data/tracking/pnl_state.json` に **0件**。したがって現時点で
    「勝ちトレードをブロックしていた」実例は未観測。
  - Plan Cで bounce_candidate=true だった銘柄のうち、観測期間中に
    実際に closed trade まで到達したのは **ADBE / PATH の2件のみ**。
    いずれも **負けトレード**（ADBE `-47.49`, `-2.58%` /
    PATH `-41.58`, `-2.13%`）で、少なくともこの1週間では
    偽陽性で勝ちを潰した形跡は確認されなかった。
- **暫定判断**:
  - **Plan B**: 初週の would_block 件数は 21件で、最低観測件数の目安
    （5件以上）は充足。だが closed trade との対応サンプルがまだないため、
    予定通り shadow 継続でよい。
  - **Plan C**: 132/380件とヒット率が高く、現状の閾値
    （52週高値から -20% / momentum +10%）は診断としては広め。
    初週の実約定2件はいずれも負けだった一方、即昇格にはまだノイズが多い。
    observability-only 継続、必要なら中間レビュー時に閾値再調整を検討。

### Plan D follow-up: 軸①データ品質改善（否定語ガード + ソース信頼性重み付け）+ 軸②news_shock_hold新規実装（2026-08-21）

ユーザーから「ニュースセンチメント分析やそれに基づくシグナル/サイジング調整という
構造自体は問題ないか」との問いを受け、以下2軸で改善を実施（commit `4f1ca25`）。

**軸①: news_sentiment.py のデータ品質改善**
1. 否定語ガード（`_is_negated`）: "fails to beat estimates"のような否定文で
   ポジティブ語にヒットしても正しくネガティブ側にカウントされるよう修正
   （直前3語の固定ウィンドウで否定語を検出、極性反転。常時有効）
2. ソース信頼性重み付け（`SOURCE_RELIABILITY_WEIGHTS`）: Web console側
   （`dashboard_service.py`）に既にあった`_source_reliability()`の重み付け
   （Reuters/Bloomberg=0.95、SeekingAlpha=0.75、不明ソース=0.6等）をこの
   shadow診断にも移植。デフォルト有効
   （`NEWS_SENTIMENT_SOURCE_WEIGHTING_DISABLED`で無効化可能）

**軸②: news_shock_hold.py 新規実装（保有ポジション向け早期警戒shadow）**

背景: 「エントリー時点のネガティブニュースは既に価格に織り込まれている
可能性が高い（Plan Cの08-14条件付きギャップ分析と同じ効率的市場の壁）」
という構造的懸念に対応。既存Plan D（news_sentiment.py）は新規BUY候補にのみ
適用されており、保有中ポジションに新しく発生したニュースは一切見ていなかった。
`sector_shock_hold.py`（既存のセクター規模ショック検知shadow）と同じ設計
思想で、個別銘柄版の「保有中ポジションのニュースショック検知」を新規実装。
news_sentiment.pyの関連度フィルタ・否定語ガード・ソース信頼性重み付けを
すべて再利用しつつ、保有ポジション向けに調整（lookback 3日→1日、
閾値-0.34→-0.25）。`unrealized_plpc`を結果に含め、含み損状態との相関を
後で確認できるようにした。paper_demo.pyに配線: run毎に1回、現在のopen
positions全件に対して評価。ログ: `data/news_shock_hold_shadow_log.jsonl`
（`NEWS_SHOCK_HOLD_DISABLED`で無効化可能）。

**位置づけ**: いずれもshadow-only（observability-only）。既存のexit判定
ロジック（trailing_stop/breakeven/stop_loss）には一切未接続。将来paper_ab
昇格を検討する場合は、既存Plan B/C/D/Eと同じ承認・検証プロセスを経る。

**テスト**: news_sentiment.py +19件、news_shock_hold.py 新規13件。
フルスイート: 2053 passed / 2 skipped（regressionなし）。

**次のマイルストーン**: **2026-09-04**（cron登録済み:
`stock_swing_news_shock_hold_review_20260904`）に、news_shock_holdの
初回中間レビューを実施し、shadow log蓄積状況とtrue判定後の実際の値動きを
確認する。

### Plan D: ニュースセンチメント診断（shadow mode で稼働開始、2026-08-08）

**2026-08-21 追記（データ品質修正）**: R9 08-21中間レビューでPlan Dのtrue判定
件数が少ない問題を調べたところ、根本原因の一端として**Finnhubのcompany-news
エンドポイント自体が銘柄名を含まない一般市場ニュースを大量に含んでいる**ことが
判明（実データ検証: MSFT記事の91.8%が「Microsoft」を一切含まず、NVDA記事も
45%が無関係）。例えば「Mark Cuban Fires Back At Jensen Huang's AI Warning」
（NVIDIA CEOへの言及、MSFT無関係）が`warning`キーワードにヒットしMSFTの
センチメントを歪めていた。`is_relevant_article()`を新規実装し、銘柄ティッカー
または会社名（symbol_registry.yamlのdescription、企業サフィックス除去済み）が
記事本文に含まれるかで関連度判定、キーワードスコアリング前に適用（デフォルト
有効、`NEWS_SENTIMENT_RELEVANCE_FILTER_DISABLED`で無効化可能、後方互換）。
実データでの効果: MSFT article_count 33件→3件（91%削減）、NVDA 98件→45件
（54%削減）、TSLA 34件→4件（88%削減）。テスト+10件、フルスイート2027 passed
/ 2 skipped（regressionなし）。shadow-onlyの位置づけ自体は変更なし。次回
09-04レビューではこの修正後のデータで再評価する。


- **背景**: R10（2026-08-07）で「既に契約・実装済みだが戦略に一切接続されて
  いないデータ」の筆頭として企業ニュースが挙がった。`stock_swing_news_
  collection` cron（4時間おき）が既に全銘柄の Finnhub company-news を
  `data/raw/finnhub/finnhub_{symbol}_news_*.json` に保存しているが、
  コンソール表示のみでトレード判断には未接続だった。新規契約不要・
  既存データの活用のみでコストゼロという優先度1の項目として着手。
- **モジュール**: `src/stock_swing/risk/news_sentiment.py`
- **ロジック**: 見出し・要約に対する軽量キーワード辞書ベースのセンチメント
  判定（vaderSentiment 等の外部ライブラリは未インストールのため、
  Plan B/C と同じ透明性重視のシンプル実装を踏襲）。直近記事
  （デフォルト3日以内）でネガティブ系キーワード（fraud/investigation/
  downgrade/lawsuit等）とポジティブ系キーワード（beats estimates/
  upgrade/raises guidance等）のヒット数から net_score を算出し、
  閾値以下かつ最低記事数以上の場合に `negative_sentiment_buy` として
  分類・ログするが、**shadow モードでは一切ブロックしない**
  （Plan B/C と同じロールアウトパターン）
- **初期閾値**: `NEWS_SENTIMENT_NEGATIVE_THRESHOLD=-0.34`（net_score
  <= -0.34）、`NEWS_SENTIMENT_MIN_ARTICLES=2`、
  `NEWS_SENTIMENT_MAX_ARTICLE_AGE_DAYS=3`。閾値は保守的な初期値であり
  要再検証（Plan B/C と同様、蓄積データを見て調整予定）
- **無効化**: `NEWS_SENTIMENT_DISABLED=true`
- **shadow ログ**: `data/news_sentiment_shadow_log.jsonl`
- **wiring**: `paper_demo.py` の Plan B/C と同じ箇所（BUY 決定直後、
  `not args.dry_run` ガード内）。--dry-run 実行時はログ汚染しない
  （2026-08-07 の Plan B/C dry-run 汚染修正パターンを最初から踏襲）
- **status**: ✅ shadow mode 実装・有効化済み（2026-08-08）
- **次のマイルストーン**:
  - Plan B/C と同じ 2026-08-21 中間レビュー時に、shadowログの
    `negative_sentiment_buy=true` 件数とその後のトレード結果を突き合わせ、
    (a) 閾値維持/調整、(b) `paper_ab` へ昇格検討、(c) 見送り、を判断
  - signal_strength / sizing / exit閾値への接続は、Plan B/C 同様
    ユーザー承認と paper A/B 検証を経るまで行わない

**テスト**: +26件（news_sentiment.py: classify_news_sentiment 正常系/
境界値/記事鮮度フィルタ/最低記事数閾値/欠損データフォールバック/
disabled/config、load_latest_finnhub_news ファイル検出/鮮度選択/
大文字小文字非依存/不正JSON、log_observation JSONL書き込み）。
フルテストスイート: 1494 passed → **1520 passed** / 2 skipped
（既存の無関係な2件の失敗のみ、変更前から再現確認済み）。

**やらないこと（追加）**:
```
❌ Plan B/C を shadow ログ蓄積・レビュー前に active モードへ昇格しない
❌ signal_strength / sizing / exit閾値に Plan B/C の判定結果を接続しない
  （ユーザー承認と paper A/B 検証を経るまで）
```

---

## R10: 既存契約データの未接続発見 + 決算カレンダー接続（2026-08-07）

**背景**: 「現在の取得失敗・将来必要なデータ」のレビュー依頼で全コードを走査したところ、
**取得自体の失敗は現時点でなかった**（本日初日のFinnhub retry強化でnews/metricは0/44失敗、
Massive barsだ60/60成功、broker quotes/barsと44/44成功）。代わりに、
**既に契約・実装済みなのに戦略ロジックに一切接続されていないデータが複数発見された。

### 発見一覧

| データ | 取得関数 | 状況 |
|---|---|---|
| 決算カレンダー | `FinnhubClient.fetch_earnings_calendar()` | 実装済みだが一度も呼ばれていない。`EventSwingStrategy`（event_swing_v1）は
  `earnings_event`フィーチャを必要とするが一度も来なかったため、2306件の全decisionファイル中
  event_swing_v1の決定は**0件**。リアルトレードで実装されていた戦略が事実上死コードだった |
| 企業ニュース | `collect_finnhub()`内で既に4時間おきに取得中 | コンソールUI表示のみ、トレード判断に一切接続していない |
| インサイダー取引 | `fetch_insider_transactions()` | 実装済みだが一度も呼ばれていない |
| Filing sentiment | `fetch_filing_sentiment()` | 実装済みだが一度も呼ばれていない |
| Massive SMA/RSI | `fetch_sma()`/`fetch_rsi()` | 実装済みだが一度も呼ばれていない（自前ATR近似で代用中） |
| FREDマキロ | `collect_fred()` | `not_implemented`のスタブ。`MacroRegimeFeature.compute([])`に常に空リストを
  渡しているためマクロレジームは常に`unknown`（価格ベースの簡易フォーリフポバックで代用中） |

### 対応完了: 決算カレンダー接続

**実装内容**:
1. `collect_data.py`: `collect_earnings_calendar()` 新規追加
   - Finnhub `/calendar/earnings` はシンボルフィルターなしの日付範囲検索のため、
     シンボルごとのループではなく**1回のAPIコール**でターコスパタ向け全カレンダーを取得し、
     ローカルでユニバースにフィルタリングして保存（実測: 1418件→ガイダンス対象1418件→3件）
   - lookahead 10日（`EarningsEventFeature`の7日windowより広めに取って、収集サイズとズドレを避ける）
   - `config/sources/`に`required: true`としては登録していない（未取得時はevent_swing_v1が
     0件候補となるのみで、cron全体を失敗させない）
2. `paper_demo.py`: earnings_calendarスナップショットを毎回読み込み、`FinnhubNormalizer`で正規化し、
   `EarningsEventFeature`で計算して`daily_features`に合流（ベストエフォート、失敗してもランは失敗させない）
3. `stock_swing_news_collection`クロン（4時間おき）の`--sources`に`earnings_calendar`を追加

**実データでのE2E確認（2026-08-07）**:
- 実 API 呼び出しで直近決算予定3銘柄（AMAT 08-13, NBIS 08-12, SMCI 08-11）を正しく取得
- `paper_demo.py --dry-run` で `event_swing_v1` が実際にBUY信号（NBIS, strength=0.65）を生成することを確認
  （この戦略のパイプライン接続を初めて実確認）
- なお、NBISは本日別途導入したPlan Aのrolling PF gate（PF=0.453 < 0.70）でBUY STOP LISTに入っているため、
  この信号自体は実際にはブロックされる。既存ガードレールとの適切な連携を確認できた

**テスト**: +15件（collect_earnings_calendar 10件 / normalize→feature→strategyのE2E統合 5件）。
フルテストスイート: 1465 passed / 2 skipped（既存の無関係な2件の失敗のみ）。

**今後のフォローアップ**:
- 初回リアルクリハンクトはnews_collection cronの次回実行時（本日中）。event_swing_v1の
  実際の信号生成・ブロッカーとの干渉を数日間観測し、目立った問題がないか確認
- min_signal_strength（現行0.60）でevent_swing_v1が実際にどの頻度で信号を通過するかの実測リフレクションを
  1週間後に一回実施（target: 2026-08-14）

### 初週間観測（2026-08-14）

- `data/decisions/decision_*.json` 実測: `event_swing_v1` の決定は **3件**、すべて `buy`
  （2026-08-07 1件、2026-08-10 2件、全件 `SMCI`）。`deny` / `sell` / `hold` は 0件。
- `data/audits/paper_demo_20260807.log` / `paper_demo_20260811.log` 実測:
  3件とも既存の `entry_filter_blocked_buys` で停止し、実注文には進まなかった。
  08-07 13:35 UTC run は `['SMCI', 'SMCI', 'RBRK']`、08-10 16:00 UTC run は
  `['SMCI', 'SMCI', 'RBRK']`、08-10 19:55 UTC run は
  `['SMCI', 'SMCI', 'RBRK', 'HPE', 'DELL']` が entry filter でブロックされた。
- これはガードレール誤動作ではなく、既存の rolling PF gate と整合的。`SMCI` の closed trade
  実績は **PF=0.310 / n=5** で、`ENTRY_FILTER_ROLLING_PF_GATE` 既定値 0.70 を下回るため、
  `event_swing_v1` の BUY も breakout の BUY も同様に block される状態だった。
  cluster cap / allocation / sizing はその後段で正常に動いているが、`event_swing_v1` の 3件は
  すべて entry filter で止まったため、後段 guardrail の対象にはならなかった。
- `data/audits/earnings_calendar_status.json` 最新値:
  `time=2026-08-13T23:05:08.912899+00:00`, `status=ok`, `symbols_requested=44`,
  `symbols_with_upcoming_earnings=1`, `total_calendar_rows_fetched=536`,
  `from=2026-08-13`, `to=2026-08-23`。ファイル更新時刻は 2026-08-14 08:05 JST。
- `data/raw/finnhub/finnhub_earnings_calendar_*.json` では 2026-08-07 07:05 UTC から
  2026-08-13 23:05 UTC まで概ね 4時間おきの取得が継続している一方、
  **2026-08-08 03:05 UTC → 2026-08-10 05:14 UTC に週末ギャップ**がある。
  週末停止が意図仕様なら問題ないが、`4時間おき` の厳密運用としては確認余地あり。
- 監査上の小さな不整合: status ファイルの主タイムスタンプキーは `updated_at` ではなく `time`。
  データ取得自体は成功しているが、確認 runbook / cron review 側が `updated_at` 前提だと取り違えやすい。
- 08-07〜08-14 の `paper_demo` 監査ログ上、`event_swing_v1` まわりに `ERROR` / `CRITICAL` /
  traceback は見当たらなかった。初週間の実挙動としては
  「信号は出たが、既存の entry filter が fail-closed で止めた」が実態。

### 未対応（2026-08-07時点。優先度1/2は2026-08-08にPlan D/Eとして着手・完了 — 上記参照）

インサイダー取引・Filing sentiment・FREDマクロは、いずれも現在の戦略の
動作を直接阻害していないため引き続き未対応。優先度順：
1. ~~ニュースセンチメントのトレード接続~~ → ✅ 2026-08-08 Plan D として shadow mode 実装完了
2. ~~Massive SMA/RSIの接続~~ → ✅ 2026-08-08 Plan E（RSI診断のみ）として shadow mode 実装完了
3. インサイダー取引・Filing sentiment（新規契約は不要、追加実装のみ）
4. FREDマキロ（R8-v2のMLフェーズまでは優先度低）

### Plan E: Massive RSI 過熱診断（shadow mode で稼働開始、2026-08-08）

- **背景**: `MassiveClient.fetch_sma()` / `fetch_rsi()`
  （`src/stock_swing/sources/massive_client.py`）は Massive API 移行時から
  実装済みだったが一度も呼ばれていなかった。既存の `PriceMomentumFeature`
  は自前の ATR 近似（生の OHLC バーからの True Range 平均）で
  stop_price を算出しており、RSIとは無関係。BreakoutMomentumStrategy は
  純粋に5日モメンタムのみで発火するため、既に「買われすぎ」の水準にある
  銘柄に飛び乗るリスクがある（NBIS の post-drop-bounce パターン＝Plan C
  とは別種の失敗モード）。
- **モジュール**: `src/stock_swing/risk/rsi_diagnostic.py`
- **ロジック**: BUY決定ごとに Massive API から RSI(14) の最新値を取得し、
  閾値（デフォルト75.0）以上なら `is_overbought` として分類・ログするが、
  **shadow モードでは一切ブロックしない**（Plan B/C/D と同じロールアウト
  パターン）。この戦略の実トレード結果に対して RSI(14) は一度も検証されて
  おらず、優良なブレイクアウトの多くは定義上「買われすぎ」水準で発火する
  可能性があるため、閾値を signal_strength やサイジングに直接組み込む前に
  データ蓄積が必要
- **APIコール範囲**: 全銘柄（ユニバース44銘柄）ではなく、**BUY決定が出た
  銘柄のみ**RSIを取得（Plan B/C/D と同じパターン。Massive APIコール量の
  無用な倍増を避けるため）
- **初期閾値**: `RSI_DIAGNOSTIC_OVERBOUGHT_THRESHOLD=75.0`（標準的な
  「買われすぎ」閾値。要再検証）
- **無効化**: `RSI_DIAGNOSTIC_DISABLED=true`
- **shadow ログ**: `data/rsi_diagnostic_shadow_log.jsonl`
- **wiring**: `paper_demo.py` の Plan B/C/D と同じ箇所（BUY 決定直後、
  `not args.dry_run` ガード内）。MassiveClient はラン開始時に1回だけ
  best-effort で構築し、初期化失敗時は当該ランの RSI 診断のみ無効化
  （ランは失敗させない）
- **status**: ✅ shadow mode 実装・有効化済み（2026-08-08）。同日の
  `stock_swing_paper_demo_market_close` 本番cronで実データにより動作確認
  済み（MSFT RSI=78.3 overbought / SNOW RSI=80.5 overbought / 他16銘柄
  not_flagged、エラーなし）
- **次のマイルストーン**:
  - Plan B/C/D と同じ 2026-08-21 中間レビュー時に、shadowログの
    `is_overbought=true` 件数とその後のトレード結果を突き合わせ、
    (a) 閾値維持/調整、(b) `paper_ab` へ昇格検討、(c) 見送り、を判断
  - signal_strength / sizing / exit閾値への接続は、Plan B/C/D 同様
    ユーザー承認と paper A/B 検証を経るまで行わない

**テスト**: +19件（rsi_diagnostic.py: classify_rsi_overbought 正常系/
境界値/欠損データフォールバック/disabled/config、fetch_latest_rsi
クライアント例外耐性/欠損値/型エラー耐性、log_shadow JSONL書き込み）。
フルテストスイート: 1520 passed → **1539 passed** / 2 skipped
（既存の無関係な2件の失敗のみ、変更前から再現確認済み）。

### 2026-08-21 中間レビュー（Plan B/C/D/E）

`data/tracking/pnl_state.json` の **closed trade** を対象に、各shadow/diagnostic
ログで **true 判定が出た同一銘柄について、直後15分以内に entry した実トレード**
のみを紐づけて集計した。単なる「同銘柄が後日売買された」ケースは除外し、
当該判定が実際のBUY判断に同伴していたケースだけを見る方針。

- **Plan B（volatility_gate）**: 2026-08-07〜08-21 の
  `data/volatility_gate_shadow_log.jsonl` は **971件中 would_block=true 41件
  （4.2%）**。対象は **NBIS 25件 / SMCI 16件** のみ。だが、この2銘柄は
  観測期間中に true 判定直後15分以内の closed trade が **0件** で、勝敗率の
  判定に必要なサンプルがまだない。**推奨アクション: shadow継続**。
  false positive（勝ちトレードを潰した）実例も、true positive（負けを防げた）
  実例も未観測のため、**paper_ab昇格はまだ提案しない**。
- **Plan C（distance_from_high）**: 2026-08-07〜08-21 の
  `data/distance_from_high_log.jsonl` は **971件中 is_bounce_candidate=true
  316件（32.5%）**、対象21銘柄。true 判定と紐づいた closed trade は
  **8件**で、**3勝 / 5敗（負け比率62.5%）**、合計PnL **-355.90**。
  負け比率は昇格目安（60%以上）を上回った一方、**サンプル8件で10件未満**の
  ため統計的にはまだ弱い。**推奨アクション: observability継続
  （paper_ab候補寄りだが保留）**。次回レビューで10件以上に達してなお
  60%超の負け比率が続くなら、paper_ab昇格提案の妥当性が高い。
- **Plan D（news_sentiment）**: 2026-08-08〜08-21 の
  `data/news_sentiment_shadow_log.jsonl` は **904件中
  negative_sentiment_buy=true 26件（2.9%）**、対象9銘柄。2026-08-15時点の
  **448件中0件** からは改善し、**閾値 `NEWS_SENTIMENT_NEGATIVE_THRESHOLD=-0.34`
  が厳しすぎて全く発火しない状態は脱した**。ただし、true 判定と紐づいた
  closed trade は **CRDO 1件のみ（1敗、PnL -1682.56）**。**推奨アクション:
  shadow継続**。現時点では trade outcome のサンプルが少なすぎるため、
  **即時の閾値変更も paper_ab昇格も行わない**。
- **Plan E（rsi_diagnostic）**: 2026-08-08〜08-21 の
  `data/rsi_diagnostic_shadow_log.jsonl` は **904件中 is_overbought=true
  77件（8.5%）**、対象7銘柄。true 判定と紐づいた closed trade は **4件**で、
  **1勝 / 3敗（負け比率75.0%）**、合計PnL **+329.40**。負け比率だけ見れば
  フィルタ候補だが、**サンプル4件でまだ少なすぎる**うえ、勝ちトレード
  （SKYY +458.71）も含む。**推奨アクション: shadow継続**。閾値75.0を
  いじる段階ではなく、まず件数蓄積を優先する。

**08-21時点の総合判断**:

- **Plan B**: closed trade 紐づけが 0件のため、昇格判断は保留。shadow継続。
- **Plan C**: 最も有望。負け比率 62.5% だがサンプル不足のため、今回は昇格提案
  ではなく **次回レビュー最優先候補**。
- **Plan D**: 0件問題は解消。ただし trade outcome サンプル不足。shadow継続。
- **Plan E**: 負け比率は高いがサンプル不足。shadow継続。

**ユーザー向け推奨アクション（承認待ち前提）**:

- 今回は **Plan B/C/D/E いずれも active / paper_ab へ自動昇格しない**。
- 次回レビュー時に、**Plan C が first candidate**、**Plan E が second
  candidate** として再評価する。
- 昇格（`paper_ab` / `active`）を行う場合は、従来方針どおり **必ずユーザー承認を
  取得してから** 実施する。

**新規契約が必要な候補（ユーザー判断待ち）**:
- オプションフロー / Put-Call比率
- ショートインタレスト
- セキトー全体の時列列ADR/ボラティリティデータ（Plan Bの単発スナップショットを時列列化）

---

## R11: Strategy Edge Discovery（勝てる戦略の構築・データ蓄積計画、2026-08-15）

**Status**: PLANNED（未着手、本セクションで初めて書き起こし）
**Priority**: P1（R0-v2とは独立して今日から着手可能。R0-v2の完了待ちは不要）
**背景**: ユーザーとの対話（2026-08-15）で、現行ロードマップ（R0〜R10）が専ら「守り」
（リスク管理・データ整合性・可観測性）に偵っており、「そもそも勝てるエントリー・シグナルを
どう作るか」という問いに正面から取り組むフェーズが存在しないことが指摘された。R4-v2（signal
calibration）とR8-v2（ML）は形式上は正面から取り組む項目だが、いずれも「ライブ運用での
自然蓄積を待つ」設計になっており（attributable tradesが現在2026-08-15時点でわずか25件、
R8-v2のcalibration開始基準（≥30）に対し大幅に不足）、進捗が数ヶ月単位で遅い。

**重要な設計思想（既存ロードマップとの違い）**: R0〜R10は全て「ライブ/paper運用の蓄積」を
待つ設計だが、R11は**ヒストリカルデータ（yfinance経由で69銘柄×2年分の日次データが即座に
取得可能と確認済み）**を使うため、市場イベントやデータ蓄積に依存せず自力で完遂できる。
この意味でR0-v2のゲート制約とは無関係に今日から着手可能。

### 依存関係

```
R11-A バックテスト基盤復旧  ← 最優先、他全フェーズの前提
 └→ R11-B 現行シグナルの妥当性再検証（最優先の問い：今のエッジは本物か）
     └→ R11-C 代替シグナル候補の並行バックテスト
         └→ R11-D 有望候補のpaper A/B（既存R9のPlan A-E型と合流）
R11-E ML基盤の並行整備（データ収集のみ先行、R8-v2の待ち時間を無駄にしない目的）
```

**R0-v2との位置づけ**: R11はライブ/paperの実注文・ポジションに一切影響しないread-onlyのヒストリカル
分析のみで構成されるため、R0-v2の「sector_shock paper A/Bやstop閾値本採用変更を開始しない」
という制約とは衝突しない。R11-Dのpaper A/Bのみ、既存の「やらないこと」節と同等の慣重で
扬する（user承認なしにactive化しない）。

### R11-A: バックテスト基盤の復旧（目安 1〜2日）

**Status**: PLANNED

**現状の問題**: `src/stock_swing/backtest/engine_v2.py`（2026-04実装、Week 3当時のまま
放置）は完全には動作していない：
- `engine.py` に TODO 2件が残存（`run_walk_forward()` 未実装、`run_backtest()`
  が一部placeholder結果を返す）
- 利用しているスクリプトは `scripts/run_first_backtest.py` 等の初期検証用のみで、
  2026-04以降更新されていない

**作業内容**:
1. `BacktestEngineV2` / `TradeSimulator` / `MetricsCalculator` を現行の
   `SimpleExitV2Strategy`（tiered min_hold / staged trailing / staged breakeven /
   volatility_adjusted_stopを含む最新版）と接続（現行はbacktest側が古い独自実装の
   ままの可能性が高い。本番 paper_demo.py と同じExitロジックを使うことが必須）
2. `PriceCache`（既存実装済み）をyfinance経由で69銘柄×2年分の日次OHLCVでプレウォーム
3. サニティチェック: 既知の実際のclosed trade（例: DELL 2026-07-28 stop_loss）を
   バックテストエンジンで再現し、実注文結果と一致（または説明可能な差分）であることを確認

**Acceptance criteria**:
- 既知closed tradeの再現テストがパス（許容誤差内）
- 69銘柄×2年分のデータ取得・キャッシュが30分以内で完了

**実施結果（2026-08-15）**: 既存 `backtest/engine_v2.py` は使用しない方針に変更（下記理由）。
代わりに新規2スクリプトを作成:
- `scripts/r11_fetch_historical_data.py`: yfinanceバッチダウンロードで
  `symbol_registry.yaml` 全69銘柄×2年分の日次OHLCVを `data/r11_price_cache/{symbol}.json`
  に取得・キャッシュ。実行時間 <30秒で完了（acceptance criteria達成）
- `scripts/r11_backtest_engine.py`: **既存engine_v2.pyを使わず新規実装**したバックテストハーネス。
  理由: engine_v2.pyは（a）価格シミュレーションが`random.uniform(-0.02, 0.03)`の
  完全なランダムウォーク、（b）Exitロジックが固定stop/take-profit/max_holdの独自実装で
  `SimpleExitV2Strategy`（2026-05以降のtrailing/staged/tiered改良を一切反映）を呼んでいないことが
  判明し、R11-Bの目的（本番同一ロジックの検証）には使えないと判断したため。
  新ハーネスは`PriceMomentumFeature` / `BreakoutMomentumStrategy` / `SimpleExitV2Strategy`
  （本番と完全同一クラス、`config/strategy/simple_exit_v2.yaml`も同一）を直接呼び出し、
  両モジュールが内部でハードコードしている`datetime.now()`をフリーズ（モンキーパッチ）して
  過去日付でのシミュレーションを可能にした
- サニティチェック: AMZNの実際のclosed trade（2026-08-03エントリー、stop_loss -7.0%）を
  ハーネスで再現し、エントリータイミングの差分（本番は日中複数回のcon判定、ハーネスは日次終値で
  1日、1回判定）を除けばexit_reason・return_pctの方向性が一致することを確認済み

### R11-B: 現行シグナル（momentum閾値）の妥当性再検証（目安 2〜3日）

**Status**: ✅ **一次検証完了（2026-08-15）**。結論:（a）**エッジありと確認**。以下詳細。

**発見された問題意識（2026-08-14 R4-C decile分析より）**: `reports/signal_strength_
decile.json`（n=86）でdecile別PFが非単調（decile 5のみPF=2.455で他はすべて
1未満、最高decile 10はPF=0.096で最悪クラス）。本来signal_strengthに予測力があれば
高decileほどPFが向上するはずで、この逆転現象は（a）n=8〜9の小サンプルノイズ、（b）
現行ロジック（5日モメンタム閾値ブレイクアウト）にそもそもエッジがない、のいずれかである。
どちらかに答えを出さない限りR4-v2（calibration）やR5-v2（promotion gateのPF基準）の
投資価値が不明のままになる（ノイズをいくら校正してもエッジのないシグナルは勝てない）。

**作業内容**:
1. R11-Aの基盤で、2026年初〜現在の2年分、69銘柄全銘柄に対し、現行の
   `BreakoutMomentumStrategy._calculate_signal_strength()`ロジック（5日モメンタム、
   飽和閾値20%）をそのまま適用してエントリーシグナルを全期間再現
2. Walk-forward（学習期間/検証期間をローリングで分割）でdecile別PFを再集計し、
   nが数百件規模に増えた場合にも同じ非単調現象が再現するかを確認
3. momentum閾値をグリッドサーチ（例: 3%/5%/8%/12%/20%）し、どの水準で最も
   安定的なエッジ（PF>1がcross-validationで一貫）が得られるかを確認
4. セクター別（半導体/ソフトウェア/内ネット等）に分割してもエッジが存在するか
   （特定セクターの偽のエッジではないか）を確認

**想定される結論の分岐**:
- （a）エッジありと確認 → R4-v2のcalibrationに投資価値あり。R11-Cへ進む
- （b）エッジなしと判明 → 現行エントリーロジック自体の見直しが最優先課題として
  浮上（R4-v2のcalibrationは後回しに）。R11-Cで代替シグナルを探す優先度が上がる

**Acceptance criteria**:
- walk-forwardで少なくとも2つ以上の独立した検証期間で同方向の結果が出ること（以前の
  live PF数値が集計期間をまたぐノイズだった事例（2026-08-05）の同じ過ちを避ける）
- 結論（a/b）を docs/console_improvement_tasks.md の本セクションに追記

**実施結果（2026-08-15、`scripts/r11_backtest_engine.py --save`、
`reports/r11_backtest_results.json`）**:

69銘柄×2年分（2024-08-15〜2026-08-14）、本番と同一の`BreakoutMomentumStrategy`
（min_momentum=0.05, min_signal_strength=0.40）+ `SimpleExitV2Strategy`（現行本番設定、
銘柄あたり固定$10,000ノーショナル）で全期間シミュレーション:

```
n=1,415 trades　(ライブattributableの86件の約16倍のサンプル規模)
WR=59.4%　PF=1.706　net=+$306,704（手数料・slippage $0仮定）

Walk-forward分割（前半2025-10-08以前 / 後半以降）:
  前半: n=700  WR=61.9%  PF=1.775  net=+$154,847
  後半: n=715  WR=56.9%  PF=1.648  net=+$151,857
  → 2つの独立期間で同方向（両方ともPF>1.6）。acceptance criteria達成。

Decile別PF（entry_signal_strength順）:
  decile 1  PF=1.04   decile 6  PF=1.70
  decile 2  PF=0.82   decile 7  PF=1.96
  decile 3  PF=2.27   decile 8  PF=1.98
  decile 4  PF=1.56   decile 9  PF=2.20
  decile 5  PF=1.66   decile 10 PF=2.22
  → 概ね右肩上がり。2026-08-14のライブdecile分析（n=86、decile 10がPF=0.096で最悪）で見られた
  非単調・逆転現象は、この大規模n=1,415では再現しなかった。

コスト感度分析（往復手数料+slippage仮定、リアルトレードの「$0仮定では計算しない」制約を遵守）:
  0bp:  PF=1.706  net=+$306,704
  10bp: PF=1.624  net=+$278,097
  20bp: PF=1.546  net=+$249,491
  30bp: PF=1.471  net=+$220,884（保守的仮定でもPF>1維持）

銘柄集中度: 上位5銘柄（NBIS/MU/CIEN/SNOW/AMD）がnetの26.1%を占めるが、
69銘柄中58銘柄（84%）がPF>1。特定銘柄依存の偽のエッジではないことを確認。
セクター別も半導体（PF=1.95, n=592）を中心に広く分散しており、単一セクターの偏ったエッジではない。

参考: 推定平均同時ポジション数で30.5、実現ベースの簡易equityカーブでmax
drawdownは約6.2%（SPY buy-and-holdの同期間リターン+40.4%とは異なる収益源：
バックテストの純リターンは展開資本当たり約30%で、市場全体に乗っているだけでないことを補強）。
```

**結論**: （a）**エッジありと確認**。現行`BreakoutMomentumStrategy` + `SimpleExitV2Strategy`の
組み合わせは、大規模・walk-forward検証でPF>1.6を一貫して示し、decile別も概ね単調増加。
ライブで見られた非単調現象（n=86）は小サンプルノイズだった可能性が高い。

**不確実性・限界（重要、今後の取り扱いに注意）**:
- ハーネスは**日次終値ベース**の1日、1回のSignal/Exit判定であり、本番（日中複数回のcron、
  最新quote/barを使用）とは完全一致しない。エントリー/エキジットタイミングの精度は項目例AMZNで
  確認済みだが、完全一致ではない
- ポジションサイジング・allocation上限・cluster cap・entry filter（rolling PF gate等）など
  本番R0-v2/R5-v2の安全制約は一切適用していない（意図的に除外: 現行ロジックの純粋なエッジの
  有無を問うため）。実際の本番リターンはこれらの制約によりさらに低くなる可能性がある
- 手数料/slippageは一律仮定の往復ベーシスポイントであり、実際の市場インパクト（純銘柄や時間帯）を
  反映していない
- オーバーフィットリスク: パラメータ（min_momentum=0.05等）は現行本番設定をそのまま使用しており、
  このバックテスト結果に合わせてパラメータを二次探索したものではない

**次のアクション**: R11-Cへ進む（エッジありと確認されたため、R4-v2のcalibrationも投資価値ありと
判断。ただし上記の不確実性を踏まえ、R11-Dでの本番採用はpaper A/Bを必ず経由し、
ヒストリカルの優れた数値だけで直接本番反映しないことを引き続き彻底。

### R11-C: 代替シグナル候補の並行バックテスト（目安 1〜2週間、R11-Bが（a）または（b）のどちらでも着手）

**Status**: ✅ **一次検証完了（2026-08-15）**。結論: **4候補全てがacceptance criteria未達成**（以下詳細）。
R11-D（paper A/Bへの昇格）は見送り。

**背景**: 既にデータ取得・接続済みだがエントリー判断には使われていないターゲットが複数ある
（R10で発見済み）。これらを単体・組み合わせでヒストリカルバックテストし、現行ロジック（またはR11-Bで
見つかった改良版）と同一期間・同一コスト前提で横並び比較する。

**検証候補（既接続済みデータの活用）**:
1. **RSI逆張フィルタ**（Plan Eのrsi_diagnosticを逆方向に使用：「RSI高すぎない時のみ
   エントリー」というフィルタを追加した場合のPF変化）
2. **ニュースセンチメントフィルタ**（Plan Dのnews_sentimentをpositive方向に使用：「ネガ
   ティブのみでなく、positiveニュースフローと同方向のBUYのみ通す」場合のPF変化）
3. **決算カレンダー近接**（event_swing_v1、既存だが実質死コード。決算直前/直後のイベント
   スイングに限定したエントリーの有効性を別途検証）
4. **セクター相対強度**（銘柄vs同セクターベンチマーク（`symbol_registry.yaml`のbenchmark_
   symbols既定）の相対パフォーマンスを新規エントリー条件として追加）
5. （R11-Bが（b）の場合）momentum以外の基礎エントリーロジック（例: 移動平均クロス、
   ボラティリティブレイクアウト等）もゼロから探索

**評価基準**: 各候補を同一期間・walk-forwardでPF/WR/Sharpe/max drawdownを算出し、
現行（またはR11-B改良版）と比較表を作成。単一指標でなくcost考慮済み（手数料・スリッパージ
仮定）で比較すること（既存の「counterfactualを$0仮定で計算しない」制約を継承）。

**Acceptance criteria**:
- 少なくとも1つの代替シグナル候補が、現行（またはR11-B改良版）よりwalk-forwardで
  一貫して優れた数値（PF/Sharpeどちらか）を示すことを確認（なければR11-Dはpaperに進まず
  見送りを提案）

**実施結果（2026-08-15、`scripts/r11c_candidate_backtest.py --candidate all --save`、
`reports/r11c_*_results.json`）**:

全候補をR11-Bと同一の69銘柄・同一baselineに層を重ねる形でバックテスト（baseline: n=1,415、
WR=59.4%、PF=1.706、walk-forward前半PF=1.775/後半PF=1.648）:

```
候補                          n     WR      PF     walk-forward前半  後半        判定
──────────────────────────────────────────────────────────────────────────────────────
RSI逆張（RSI<75のみ）       1,359  58.7%  1.716  1.776           1.663      baselineと実質差なし
セクター相対強度            1,212  59.7%  1.717  1.912           1.568      前半改善・後半悪化で不一貫
決算カレンダー近接（±5日）    242  55.0%  1.503  1.757           1.302      両期間ともbaselineより悪化
ニュースセンチメントpositive*     202  52.0%  1.309  1.833           0.770      期間間で大きくブレ、一貫PF>1不成立
```

\* ニュースセンチメントのみ重要な制約付き: 価格データ（yfinanceで2年分）と異なり、Finnhub企業ニュース
スナップショット（`data/raw/finnhub/finnhub_{symbol}_news_*.json`）は `stock_swing_news_collection`
cron開始後の2026-04-21〜2026-08-14（約4ヶ月分のみ）しか存在しない。過去分のニュース
アーカイブを遡及で取得する手段がないため、他の3候補（2年分）とは検証期間の長さが大きく異なり、
結果の信頼性は低い（サンプルが少ない、特定期間のノイズを拾っている可能性）。

**个別評価**:
- **RSI逆張**: PF/WRともbaselineとほぼ同等（差は誤差範囲内）。nが1,415→1,359に減っただけで
  実質的な改善はない。これはもともとPlan Eのrshi_diagnostic shadowログでも示唆されていた通り
  （優良なブレイクアウトの多くは定義上「買われすぎ」水準で発火する）、RSIでのフィルタリングは
  この戦略には寄与しないと判断
- **セクター相対強度**: 全体PFはbaselineと同等だがwalk-forwardで前半（1.912）・後半（1.568）と
  方向性が一貱していない（acceptance criteriaの「一貫して優れた数値」に未達）。nが1,415→
  1,212に減る代償に見合う改善がない。
- **決算カレンダー近接**: 両walk-forward期間ともbaselineより明確に悪化（1.757/1.302 vs baseline
  1.775/1.648）。ETFはearnings日が存在せず自動除外される仕様も確認（正しい挙動）。
  event_swing_v1が実際に一度も機能してこなかった（R10で発見）経緯を踏まえると、決算近接だけを
  独立のエントリー条件とするアプローチはこのデータでは支持されない
- **ニュースセンチメントpositive**: 4候補中最も悪い。特に後半期間（PF=0.770）で大幅に悪化しており、
  単にサンプルが少ない（n=202）だけでなく方向性も不安定。positiveニュースフローと同方向のBUYのみ
  通すというアイデアは、少なくともこの短期間データでは支持されなかった

**結論**: **acceptance criteriaを満たす候補は0件**。これは有益な否定結果として記録する。
これらのフィルタをR11-Dへ進める根拠はない。R4-v2（calibration）はR11-Bの結果に基づき引き続き
投資価値ありとする一方、R11-Cで探した「別軸のフィルタでさらに上閃せする」アプローチは、少なくとも
今回検証した4候補の範囲では支持されなかった。

**不確実性（この否定結果の限界）**:
- 各候補は単一のパラメータ（RSI閾傄75、決算近接±5日等）でのみ検証。パラメータグリッドサーチは
  未実施（別の閾値では結果が変わる可能性は残る）
- 単一フィルタのみを検証しており、組み合わせ（例: RSI+セクター相対強度の両方を満たす場合）は
  未検証
- momentum以外の基礎エントリーロジック（項目5、移動平均クロス等）はR11-Bが（a）と確認されたため未着手
  （优先度低）

### R11-B付鍘: BreakoutMomentumStrategyパラメータ最適化（目安 1日、ユーザー提案の選択肢）

**Status**: ✅ **完了（2026-08-15）**。結論: **パラメータ最適化では解決しない構造的な発見**
（以下詳細）。現行本番パラメータ（min_momentum=0.05, min_signal_strength=0.40）は変更しない。

**背景**: R11-Cで確認されたR11-B baseline（現行ロジック）のエッジをさらに磨くアプローチとして、
`BreakoutMomentumStrategy`自体のパラメータ（min_momentum/min_signal_strength）をグリッドサーチし、
現行設定より優れた組み合わせがあるかを検証。以前のR11-Cレビューで指摘されたp-hackingリスクを
避けるため、学習（train　60%）/ 検証（validation　20%）/ 最終ホールドアウト（holdout　20%）の
3分割を最初に固定し、holdoutはパラメータ選定に一切使用しない規律を彻底（`scripts/
r11b_param_search.py`）。

**セグメント**: train (2024-08-15〜2025-10-24) / validation (2025-10-27〜2026-03-20) /
holdout (2026-03-23〜2026-08-14)。

**グリッドサーチ結果（16点、min_momentum∈{0.03,0.05,0.08,0.12} × min_signal_strength∈{0.30,0.40,
0.50,0.60}）**:

```
全てのグリッド点でtrain PF=1.69〜2.18（良好）だが、validation PF=0.53〜0.63（全滄）
→ train PF>1 かつ validation PF>1 を同時に満たす生存者: **0/16点**

現行本番デフォルト（mm=0.05, ss=0.40）のセグメント別内訳:
  train:      n=732  WR=62.4%  PF=1.776  net=+$160,953
  validation: n=226  WR=43.4%  PF=0.560  net=-$44,520
  holdout:    n=457  WR=62.4%  PF=2.516  net=+$190,271
```

**根本原因の特定**: パラメータの問題ではなく、**validation期間自体が実際の市場調整局面だった**ことを
ベンチマークリターンで確認:
```
            train              validation          holdout
SPY        +22.5%              -5.4%               +18.5%
QQQ        +30.1%              -7.3%               +24.3%
```
trainとholdoutはどちらも強気相場だが、validationはSPY/QQQが実際に下落した調整局面。
同期間のexit_reason内訳も裏付け: **stop_loss比率が全期間平均25.4%に対しvalidation期間は44.7%**（226件中101件）
と約1.8倍に急橪。モメンタムブレイクアウト戦略が調整局面で早期損切りに集中するという、構造的に
予想される失敗パターンと一致。

**結論**: これはパラメータ最適化で解決できる問題ではない。**BreakoutMomentumStrategyはmomentumの
定義上、市場上昇局面に依存してエッジが発生する性質の戦略であり、市場全体が調整局面に入ると
一時的に機能しなくなる**ことが実証された。パラメータをいくら調整しても、ベンチマーク自体が下落している
局面ではロジックの構造上回避できない。この発見はR11-Bの元々の判定（（a）エッジあり）を
**否定しない**。エッジは確かに存在するが、そのエッジはレジーム依存型（上昇局面限定）であるという
より精密な理解が得られた。

**重要な潜在的含意**: R11-Bの当初の2分割walk-forward（2025-10-08で分割）は、この
後半期間に含まれていた「調整局面→回復」を平均化して隠してしまっていた（後半PF=1.648と
問题なさそうに見えたが、実際は「大きく負けた後、大きく勝った」の合成だった）。これはまさに
2026-08-05の教訓（「集計期間をまたぐノイズ」）と同型の罰であり、新規に3分割にして初めて発見できた。

**今後の方向性（提案、未着手）**:
- 現行のR0-v2ガードレール（guardrail daily/weekly loss halt, circuit breaker）はこのような
  市場全体調整局面での連続損失をどの程度抱え切れるかを別途検証価値がある
  （パラメータではなくガードレールでの防御という方向性）
- 市場レジーム検知（例: SPY/QQQのN日移動平均が下向きの間はBUYを抑制する）を新規
  フィルタとしてR11-C形式で検証する価値はある（R11-Cで未検証の方向性）
- この発見はR9の既存Plan B（ボラティリティ上限ゲート）とは別軸。Plan Bは個別銘柄のボラティリティを
  見ているが、今回の発見は「市場全体の下落局面」というマクロレジーム依存性であり、違う層の問題

**テスト（スクリプト自身の安全性確認）**: `--confirm`は生存者が0件の場合、holdoutを一切参照せず
「No winner found。本番デフォルトは変更しない」と正しく拒否することを確認済み（選定バイアス防止の
規律が機能していることの実証）。

### R11-C付鍘: 市場レジームフィルタの検証（目安 半日、R11-B付鍘の発見を受けた直接のフォローアップ）

**Status**: ✅ **完了（2026-08-15）**。結論: **2バリアントとも効果不十分**。新規フィルタ導入は提案しない。

**背景**: R11-B付鍘（パラメータグリッドサーチ）で、validation期間（2025-10-27〜2026-03-20）の不振はSPY/QQQの
実際の下落局面だったことが判明した。その自然な延長として、SPY/QQQが下降トレンドの間は新規
エントリーを抑制する市場レジームフィルタを検証。以前のR11-C候補（4つ）との違い: 今回は
**今日発見した問題を直接先笒なしに検証する形**で、R11-B付鍘と同じ学習/検証/ホールドアウト
3分割（validation期間を隠さないため、以前の2分割ではなく）で評価。

**検証バリアント（`scripts/r11c2_regime_filter_backtest.py`）**:
- A. `price_below_sma`: SPY終値 ≥ SPY SMA(50)の間のみ新規BUY許可
- B. `sma_declining`: SPY SMA(20)が5営業日前より下でない間のみ新規BUY許可

**結果**:
```
                    train PF        validation PF     holdout PF
baseline（フィルタなし）    1.776           0.560             —
price_below_sma     1.915 (n=698)   0.583 (n=189)     2.505 (n=426)
sma_declining       1.775 (n=691)   0.630 (n=175)     2.555 (n=406)
```
両バリアントともvalidationのPFを0.56→約0.58〜0.63にわずかに改善させたが、**依然として1を大きく
下回るまま**。絵以上の改善はない。

**根本原因**: SPYのvalidation期間の値動きを確認したところ、継続的な下降トレンドではなく
**648〜695のレンジで往ったり来たりするチョップ相場（whipsaw）**だった（実際、SPYがSMA50を
下回っていた日はvalidation期間100日中32日（32%）のみ）。移動平均型トレンドフィルタは
本質的に「持続的な一方向トレンド」を検知するものであり、チョップ相場ではフィルタ自体も
右往左往して機能しにくいことが実証された。事実、SPYがSMA50以上の日にも大きな損失が集中
（entered時SPY≥SMA50はtrade 180件でpnl=-$32,669、SPY<SMA50は46件でpnl=-$11,850）しており、
単純な上回り/下回り判定では損失の大多数を回避できないことを確認。

**結論**: 単純な移動平均トレンドフィルタでは2026-08-15発見のレジーム依存問題は解決しない。
問題の本質は「下降トレンド」ではなく「ボラティリティが高い横ばい相場」であり、これは移動平均では
検知しづらい市場形態。R9の既存Plan B（個別銘柄ボラティリティゲート）とは別軸だが、同じ
「ボラティリティ」という軸で見れば、今回の発見は「市場全体レベルの高ボラティリティ局面」という
予想とは違う形で制約がかかっていたということ。

**今後の方向性（提案、優先度低）**:
- 移動平均以外のボラティリティ指標（例: VIX相当、SPYのN日レンジ幅）を使ったフィルタは
  理論上はより適合している可能性があるが、新規データ取得が必要（現在はSPY/QQQのOHLCVのみ）
- パラメータ付鍘で提案した通り、**フィルタで防ぐのではなくガードレールで吸収する方向性**の方が
  現実的（R0-v2のdaily/weekly loss haltの耐性検証、別途タスクとして実施予定）

### R0-v2/R9付鍘: ガードレール耐性ストレステスト（目安 半日、R11-B/C付鍘で提案された方向性を実施）

**Status**: ✅ **完了（2026-08-15）**。結論: **現行ガードレールはreduce_sizeを頻繁に発動させているが、
今回のcorrection局面自体ではhaltには届かない**。ポジションサイジングの仮定次第で結論が変わる点に
注意が必要。

**背景**: R11-B付鍘・R11-C付鍘で、BreakoutMomentumStrategyのエッジが市場調整局面（validation期間）で
一時的に機能しなくなり、フィルタでは防げないことが判明した。両レビューで提案された通り、
「エントリー側で防ぐのではなくR0-v2ガードレールで吸収できているか」を別角で検証。

**手法（`scripts/r0v2_guardrail_stress_test.py`）**: R11-B baselineの1,415トレードを日次でリプレイし、
実運用と完全同一の`compute_daily_realized_loss_pct` / `compute_weekly_total_loss_pct` /
`compute_consecutive_losing_trades`（`src/stock_swing/guardrails/risk_snapshot.py`）と実際の
`GuardrailEngine`（`config/guardrails/autonomous_stop.yaml`をそのままロード）で日次評価。

**重要な補正**: R11-Bバックテストはシンボル間比較のため$10,000固定ノーショナルだが、実際のライブ平均
ノーショナルは約$29,100（`data/tracking/pnl_state.json`実測、約2.91倍）。$10,000基準のまま
評価すると損失率を過小評価するため、タレードpnlを、2.91倍スケールしたバージョンも併せて実行
（勝ち/負けのパターン自体は変えず、金額のみスケール）。

**結果（全438日、baseline equity $1M）**:
```
                    トリガー日数   reduce_size  block_buys  halt   train内halt  val内halt  holdout内halt
$10,000基準（ノースケール）  43         42           1          0      0            0          0
$29,100基準（2.91倍）      45         40           0          5      5            0          0
```

**スケール後のhalt 5件の詳細**: 全て**train期間内の2025-01-27〜01-31の1つの連続イベント**のみ
（daily_realized=-8.72%が引き金となり`daily_realized_loss_pct`+`weekly_total_loss_pct`の両方が
発火）。**validation期間（今回問題視した実際の市場調整局面）ではhaltは0件のまま**（最大
週次損失-2.74%、閾値-6.0%までは余裕あり）。

**解釈**: validation期間の損失は「1日で大きく掃う」ではなく、複数日・複数ポジションに分散して
累積していたため、既存のhaltルール（単日・5日の集中損失検知）にはひっかからない構造だった。
reduce_size（consecutive_losing_trades≥5でポジションサイズ50%縮小）はvalidation期間で11日発動して
おり、この還が実際の損失を一定程度抱えていた可能性はある（本スクリプトではreduce_size発動後の
サイズ縮小効果はシミュレートしていないため、反事実のPnLは不明）。

**不確実性・限界（重要）**:
- `daily_total_loss_pct`（intradayの含み損益変化も含む指標）はリプレイ不可能（日次終値のみでintraday
  mark-to-marketがないため）。halt発火のもう一つの経路（閾値-3.5%）が未検証のまま
- stale_price/broker_tracker_mismatch/api_error_rate/order_rejection/token_spendの5指標は
  バックテストに相当物がなく、0（完全クリーン）と仮定。実運用ではこれらも同時発火し得る
- $29,100スケールは平均値であり、実際のポジションサイズは銘柄・タイミングごとに幅がある（PortfolioAllocator/
  correlation cluster capは未シミュレート）
- 最大同時ポジション数が本バックテストは66件まで到達するが、実運用はアロケーションルールでより
  制限されている可能性があり、損失の分散/集中度が実際と異なる可能性がある

**実務的な含意**: 現行のR0-v2ガードレールは、今回のような「長期間のチョップ相場で損失が
少しずつ積み重なる」タイプのリスクには、haltではなくreduce_sizeで部分的に対応する設計に
なっている（意図的かは不明，偵然の可能性もある）。完全な停止（halt）は短期集中型の大損失（例:
2025-01の連続イベント）には反応するが、今回のような「広く蔴2った中程度の損失」には反応しない。

**今後の方向性（提案、未着手）**:
- ~~reduce_size発動後の実際のサイズ縮小効果（50%）をシミュレートに組み込み、validation期間の
  実際の損失がどの程度抱えられていたかを定量化~~ → 下記「R0-v2/R9付鍘(2)」で完了
- `weekly_total_loss_pct`の閾値（-6.0%）が今回のような「長期緩慢な損失」に対して適切か
  （現状最大-2.74%で余裕があるが、長期間継続した場合には到達しうる可能性あり）を
  別途検証価値あり（実データ不足のため保留、早期着手は推奨しない。ユーザーとの協議により
  R9の既存レビュー体制（08-19〜09-14）に自然に委ねる方針に）

### R0-v2/R9付鍘(2): reduce_sizeの実効果シミュレーション（目安 半日、付鍘(1)の未着手項目を完了）

**Status**: ✅ **完了（2026-08-15）**。結論: **reduce_sizeはvalidation期間の損失を約10%緩和したが、
根本解決には遠く及ばない**。

**背景**: 前回のガードレールストレステストで、reduce_sizeがvalidation期間中11日発動していたことは
確認済みだったが、実際のサイズ縮小の下流PnL効果は未シミュレートだった。本タスクでは
`config/guardrails/autonomous_stop.yaml`の`consecutive_losing_trades>=5`ルールと`paper_demo.py`の
実際の`_reduce_size_multiplier=0.5`ロジックをそのまま再現し、R11-B baselineを、2.91倍スケール
（実ライブ平均ノーショナル約$29,100基準）で再シミュレート（`scripts/r0v2_reduce_size_effect.py`）。

**結果**:
```
                    baseline（固定サイズ）PF/net    reduce_size適用 PF/net       差分
train               1.776 / +$468,373        1.819 / +$474,013      +$5,639
validation          0.560 / -$129,552        0.578 / -$116,381      +$13,171 (＋10.2%)
holdout             2.516 / +$553,687        2.536 / +$537,215      -$16,472
全期間              1.706 / +$892,509        1.743 / +$894,846      +$2,337
```

**内部整合性確認**: validation期間226件中、reduce_size発動中（consecutive_losing_trades≥25日）に
縮小サイズでエントリーしたのはわずか**24件（11%）**のみ。この24件の損失は-$13,170で、
もし通常サイズだったら約倍の-$26,341相当になっていたはず。差額は上記の改善額+$13,171と
ほぼ一致（シミュレーションの内部整合性確認）。

**解釈**: reduce_sizeはvalidation期間の損失を約10%緩和したが、226件中24件（11%）にしか
適用されていない。`consecutive_losing_trades≥5`という発動条件は「ある程度損失が進行した後でないと
発火しない」設計のため、先行する損失（発火前の5連続損失自体）には何も対応できない構造的制約が
ある。またholdout期間（強気相場）では逆に-$16,472の機会損失（本来勝てたものを縮小）が
発生しており、全期間での純改善は+$2,337に異すぎない。

**不確実性・限界**:
- 同じconsecutive_losing_tradesカウントロジックを使っているが、実運用はPortfolioAllocator/
correlation cluster cap等他のサイジング制約と組み合わされるため、実際の効果は異なる可能性
- $29,100は平均値であり、銘柄・タイミングごとの実際のバラツキは未シミュレート
- holdout期間の機会損失は、強気相場中にたまたま5連続損失が発生した場合にも一律にサイズを
  縮小するというルールの両刃の剑的な性質を示唆（損失を防ぐだけでなく、直後の回復局面での
  収益も削ぐ）

**結論（今日の一連の検証の総括）**: 今日の一連の検証（R11-Bパラメータ探索、R11-Cレジーム
フィルタ、ガードレールストレステスト、本タスク）を通じて、「validation期間の損失を完全に回避する
手段は見つからなかった」というのが正直な結論。パラメータ調整も、エントリーフィルタも、
既存のguardrailも、いずれも部分的な緩和（最大で約10%）に留まる。これはシステムの欠陥ではなく、
**チョップ相場でのモメンタム戦略の本質的な弱点を定量的に確認できた**という意味で価値ある検証だった。
この結論自体は既存ロードマップの方針（R4-v2のcalibrationやR9のshadow diagnosticsによる
エントリー品質向上）と矛盾しない。引き続き既存のR9レビュー体制（08-19〜09-14）に任せ、
新規の候補探しは一旦区切りとする。

### R11 follow-up (1): 体制整備① — 09-10 Pre-Launch Gate Reviewにレジーム依存性確認項目を追加

**Status**: ✅ **完了（2026-08-15）**

**背景**: ユーザーから「今日発見したモメンタム戦略の本質的な弱さに対して、今後十分な体制・見込みを
立てられているか」と問われたことを受け、現状を直視した結果、今日の一連の検証（R11-B付鍘〜
上記まで）はすべて「診断」であり、「今後の見張り番」は何も作られていなかったことが判明。
09-15のレビュースケジュール（08-19,08-21,08-25,08-28,09-05,09-10,09-14）のどれも、
このレジーム依存性を直接問う項目になっていなかった。

**対応内容**: `stock_swing_prelaunch_gate_review_20260910`cron（09-10実施予定）の本文に
新規「6. 新規重点確認項目」を追加。内容:
- 今日の検証結果（パラメータ最適化・レジームフィルタ・ガードレール・reduce_size実効果、全て部分緩和
  （最大約10%）に留まる）を担保者に明示的に提示（対策不要、情報提供のみ）
- 以下の「②チョップ相場検知ダッシュボード」が実装済みであれば、現在のチョップ度合いを合わせて報告

### R11 follow-up (2): 体制整備② — 市場チョップ/レジーム検知ダッシュボードパネル（observability-only）

**Status**: ✅ **実装・本番確認完了（2026-08-15）**

**背景**: 今日の一連の検証はすべてヒストリカルバックテストであり、本番稼働後に同様のチョップ相場が
発生しても気付く仕組みが何もなかった。バックテストを再実行しなくても、コンソールで現在の市場が
どの程度チョップ相場に近づいているかを常時把握できる「見張り番」を新規に実装。
R11-C付鍘で検証したSMAフィルタがエントリーブロックには不向き（validation期間PF 0.56→0.58〜0.63の
軽微な改善のみ）だったことを踏まえ、**ブロックはせず、値を可視化するだけ**に方針を変更
（Plan B-E shadow diagnosticsと同じ「観察して報告するだけ、ブロックやサイズ変更はしない」パターン）。

**実装内容**:
1. `src/stock_swing/risk/market_regime_indicator.py`新規作成: 既存の`data/benchmarks/
   SPY_daily.json`（`stock_swing_update_benchmark_all`cronが日次更新）から、（a）トレンド状態
   （価格 vs SMA(50)、SMA自体の5日間の上下）と（b）レンジ幅（20日間の高安幅）の2つを組み合わせた
   `chop_score`（0〜100）と`regime_label`（trending_bullish/trending_bearish/neutral/
   transitional/choppy）を計算する純関数。閾値は意図的な目安値でありバックテスト最適化されていない
   ことを明記（今日一日見てきたp-hackingリスクを避けるため）。
2. `console/services/dashboard_service.py`に`_get_market_regime_indicator()`新規追加
   （`_get_cluster_exposure()`と同じパターン、例外時は`insufficient_data=True`を返し
   dashboard全体を失敗させない）。`get_dashboard()`のトップレベルキー`market_regime`として
   配線。
3. `console/ui/app.js`の`renderOverviewDiagnostics()`に「🌐 市場レジーム（SPY）」カードを新規
   追加（regime_label/chop_score/終値vsSMA/レンジ幅を表示、「参考情報のみ、自動ブロックなし」と
   明記）。

**テスト**: 純関数のテスト（`tests/unit/test_market_regime_indicator.py`、7件、上昇/下降/
ホイップソーパターンを合成データで検証）+ dashboard配線のテスト（`tests/unit/
test_dashboard_service.py`のTestGetMarketRegimeIndicator、3件、「never_blocks_or_resizes」
テストでobservability-only契約を明示的に担保）。フルスイート: 1844 → **1854 passed** / 2 skipped。

**実運用確認**: コンソールを再起動し、`curl http://127.0.0.1:3335/api/dashboard`で実際に
`market_regime`キーが返ることを確認（2026-08-15時点: `regime_label="trending_bullish"`,
`chop_score=17.7`、現在の強気相場を正しく反映）。

**今後の方向性（提案、優先度低）**:
- このパネルが実際に今後のチョップ相場を事前に検知できたかは、実運用での検証が必要
  （R9の既存レビュー体制で自然に確認可能）
- chop_scoreの閾値を検知した場合に自動通知（cron/heartbeat経由）する仕組みも検討価値あり
  （現状はコンソールを自分から確認しないと気付けない）

### R11-D: 有望候補のpaper A/B（既存R9型と合流、目安 R11-C完了後）

**Status**: PLANNED

**方針**: R11-Cで有望と判明した候補のみ、既存の「shadow→paper_ab→active」の型（Plan
A-Eと同一パターン）に乗せる。ヒストリカルで優れていただけでは本番採用しない（オーバーフィット
リスクを避ける）。

**作業内容**:
1. 有望候補をshadow modeで実装（既存Plan B-Eと同じロールアウトパターン、即座は
   ブロックしない）
2. 一定期間（目安 2週間、最低20件のshadowログ）蓄積後、実トレード結果と照合
3. paper_ab昇格はユーザー承認必須（既存の全プランと同じルール）

**やらないこと**:
```
❌ ヒストリカル検証のみでactive化（paper A/Bを必ず経由）
❌ ユーザー承認なしでsignal_strength/sizing/exit閾値に接続
```

### R11-E: ML基盤の並行整備（データ収集のみ先行、R11-Aと並行可）

**Status**: ✅ **作業内1完了（2026-08-15）**。作業2（ML学習用feature/labelペア保存）は未着手。

**背景**: R8-v2（ML）はclean labels≥30件（calibration）/ ≥1,000件（training）到達を
待つ設計だが、attributable tradesは2026-08-15時点でわずか25件。待ち時間中にもできることを
しておくべき。

**実施内容（作業1、commit済み）**:
- `FeatureSnapshotStore`（`src/stock_swing/experiments/feature_snapshot_store.py`、
  P6実装時から存在したがどこからも呼ばれていなかった）を `paper_demo.py` の decision 生成ループ内
  （`decision_engine.process()`直後）に配線。各decisionごとに`signal.metadata`（momentum/trend/
  bars_used/atr等）+ `decision.evidence`（risk_per_share/stop_price/latest_close等）を
  組み合わせて `data/feature_snapshots/{experiment_id}/{run_id}/{symbol}_{decision_id}.json.gz`
  にimmutable保存。Plan B-Eと同じbest-effortパターン（保存失敗はrunを失敗させない）
- **実装中に発見したバグ（修正済み）**: `FeatureSnapshotStore.__init__`が無条件で`root.mkdir()`を
  実行するため、ストアをループ外で即時構築すると`--dry-run`実行でも空の
  `data/feature_snapshots/`ディレクトリが作成されてしまう（2026-08-07のshadow log汚染バグと
  同種）。ストアの構築を`if not args.dry_run`ブロック内の遅延初期化（lazy construction）に
  変更して修正
- テスト新規2件追加（`test_dry_run_does_not_write_feature_snapshots` /
  `test_real_run_still_writes_feature_snapshots`、既存のPlan B/C shadow logテストと同型）。
  フルスイート: 1842 passed → **1844 passed** / 2 skipped（既知の無関係スキップのみ）

**未着手（作業2）**:
- R11-A/B/Cで使うヒストリカルデータを、将来のML学習用に同一形式（feature/labelペア）で
  保存しておく（300件/1,000件到達時の即時学習開始に備える）

**Learning制約**: recommendation-only。自動本番反映禁止（既存R8-v2と同一）。

### やらないこと（R11全体）

```
❌ ヒストリカル検証結果を直接本番に反映（必ずR11-Dのpaper A/Bを経由）
❌ 基盤復旧（R11-A）を飛ばしてシグナル検証を進めない（既知closed tradeとの一致確認が先）
❌ walk-forwardでの一貫性確認なしに単一期間の結果だけで「エッジあり」と判断しない
❌ R0-v2の安全制約（manual clearのverification run必須等）をR11の作業で回避しない
```

### 優先順位まとめへの追記

| 優先度 | Phase | Status | 備考 |
|--------|-------|--------|------|
| ✅ P1 | **R11-A** | **VERIFIED_COMPLETE**（2026-08-15） | バックテスト基盤新規実装完了、実際のclosed tradeとの方向性一致確認済み |
| ✅ P1 | **R11-B** | **一次検証完了**（2026-08-15） | 結論:（a）エッジあり。n=1,415でPF=1.71、walk-forward両期間PF>1.6 |
| ✅ P1 | **R11-C** | **一次検証完了**（2026-08-15） | 結論: 4候補 + レジームフィルタ2バリアントも含め全てacceptance criteria未達成。R11-Dへの候補なし |
| ⚪ P2 | **R11-D** | **見送り** | R11-Cで昇格対象候補が0件だったため、現時点で進める候補なし |
| ✅ P2 | **R11-E** | **作業1完了（2026-08-15）** | FeatureSnapshotStore配線済み。作業2（ML用feature/labelペア）は未着手 |

---

## 将来検討（バックログ、未着手）— 2026-08-19 追記

### R12（案）: exit判定へのマーケット全体トレンド（market_regime）反映

**発端**: 2026-08-19朝、プレマーケット帯でcurrent_price基準の含み損益が前日終値基準と
約$21,000乖離する場面があり、「マーケット全体が上昇トレンドの時に、ノイズによる一時的な
下げだけで個別ポジションを売ってしまわないか」という懸念から検討。

**現状の保護レイヤー（整理）**:

| 対象 | 状態 |
|---|---|
| プレマーケット/アフターアワーズのノイズ | ✅ `_filter_sells_outside_regular_hours()`で対策済み（-12%以下の壊滅的ケース以外は繰延） |
| 銘柄固有の一時的ノイズ（正規時間中） | ✅ tiered min_hold（2026-08-05）で部分対策済み |
| セクター全体の急落（正規時間中） | 🟡 sector_shock_hold（shadow中、本番未適用） |
| **マーケット全体トレンド方向** | ❌ **未対策**（`market_regime`は新規エントリーのポジションサイジングにのみ使用、exit判定には未接続） |

**改修案**: `decision.evidence["market_regime"]`（bullish/neutral/cautious）をexit判定にも
接続し、bullish regime中はstop_loss閾値を緩める／min_hold期間を延長する。

**メリット**:
- 既存データ（`docs/stop_loss_evaluation_guidelines.md`）で、下落幅-5%未満の止損は
  78%が7日以内、89%が10日以内に回復することが定量的に確認済み。regime連動で
  さらに改善余地がある可能性。
- stop_loss全体の損失は-$146,340（PF=0.113、WR=17.1%）と大きく、tiered min_hold
  実績（-$167K→-$126K、+$41K改善）に続く改善余地の候補になり得る。
- `market_regime`は既に`decision.evidence`に格納済みで、exit側で参照するだけなら
  実装コスト自体は小さい。

**デメリット**:
- `market_regime`はFRED マクロ指標＋価格モメンタムの日次更新合成で、リアルタイム
  反転検知には不向き。bullish判定が甘いと本物の下降トレンドを見逃し、損失拡大
  リスクがある。
- stop_lossの設計思想（「利益を生むためでなく負けトレードを早期に終わらせるための
  機械的リスク管理」）と、regime連動という予測的判断の混入は理念的に矛盾する。
- 2026-08-15のR11-C付鍘検証で、SPY/QQQベースの単純なレジームフィルタ
  （price_below_sma / sma_declining）は**エントリー抑制用途でも効果不十分**と結論済み
  （validation PFが0.56→0.58〜0.63と小幅改善のみ、依然1未満）。同種のレジーム判定を
  exit側に転用しても同様に効果が限定的である可能性が高い。
- regime別のstop_loss挙動を検証するにはサンプル不足（全体でstop_loss 76件、
  bullish限定だとさらに少数）。閾値の妥当性検証に数週間〜数ヶ月を要する見込みで、
  09-15のリアルトレード移行スケジュールには間に合わない。
- 機能的にsector_shock_hold（個別銘柄のセクター逆行判定）と近く、そちらのpaper A/B
  検証が先に完了すべき優先タスク。

**結論（2026-08-19時点）**: 今すぐの実装は見送り。09-15のリアルトレード移行後、
安定稼働を確認してからバックログ候補として再検討する。着手する場合は
先にsector_shock_hold A/Bの結果（近い軸の指標のため参考になる）を確認してから
とする。R11-C付鍘の単純レジームフィルタが効果不十分だった前例があるため、
着手する場合はSPY/QQQの単純な上回り/下回り判定ではなく、別のレジーム定義
（ボラティリティ軸等）を検討する必要がある。

**Status**: 🔵 未着手・将来検討（優先度低）

---

## 2026-08-23 監査: Go/No-Go判定基盤・データ鮮度の実データ精査（ユーザー依頼）

**背景**: ユーザーから「現在の投資システムの現状のパフォーマンスと改善計画の監査」を
依頼され、実運用データ（`reports/console/latest_console_summary.json` /
`data/tracking/pnl_state.json` / `data/raw/broker/*.json` / cron実行履歴等）を
直接精査。**09-15 Go/No-Go判定の根拠データそのものに複数の実バグ**を発見。
いずれも「システムが実際に危険な状態」ではなく「システムの状態を判定する仕組み
自体が正しく機能していない」という、より根本的な問題。修正コード6件を作成し
`docs/audit_fixes_20260823/`にパッチ形式で保存した上で、**2026-08-23 12:45 JST
ユーザー承認により全6件を本番コードに適用済み**。

**総括**: 全6件を適用した状態でフルテストスイートを再実行し
**2065 passed / 2 skipped を確認**。加えて`--dry-run`実行（発注なし、ブローカーの
参照系APIのみ使用）と`check_go_no_go.py`単体実行で実データ上の動作も確認済み。
下表のStatusは全件**APPLIED（適用済み）**に更新。

### 🔴 監査1: paper_demoの無アクションrunがconsole_summaryを更新しない（最重要）

**発見**: `paper_demo.py`の「no_signals」「no actionable decisions」の2箇所が
早期`return`しており、その場合`console_summary.emit()`（`scripts/check_go_no_go.py`
が読む唯一のデータソース）が一切実行されない。実際に2026-08-21 04:50 JSTの run を
最後に**08-22, 08-23の2日間、decisionファイルが1件も生成されておらず、
console summaryが凍結**していたことを確認。

**修正**: 両early-returnを「フォールスルー」に変更し、無アクションrunでも
console_summary / 日次スナップショット / reconciliation / guardrail評価が必ず
実行されるようにした。パッチ: `docs/audit_fixes_20260823/patches/01_*.patch`

**Status**: ✅ APPLIED（2026-08-23 12:45 JST 適用済み）

### 🔴 監査2: equity_bridgeのquarantined_pnl固定値0.0バグ

**発見**: `_build_equity_bridge()`が`quarantined_pnl=0.0`を固定し、コメントで
「quarantined tradesはdata reconstruction errorsで実際のbroker fillではない」と
説明していたが、実データ確認の結果**quarantined_trades 101件全件が実際の
broker約定**（broker_order_id + exit_broker_order_id を保有）だった。その
PnL（約-$156,476）はbroker_equityには反映済みだがtrackerには一切反映されず、
本来$168,874あるはずの`unexplained_diff`が、$100,000という「常にpassするよう
選ばれた」toleranceでマスクされていた。

**修正**: `quarantined_pnl`を`pnl_tracker.get_quarantined_trades()`の実合計に、
`tolerance_usd`を`config/runtime/current_mode.yaml`の
`ledger_quality_gate.acceptance_criteria.broker_equity_bridge_tolerance_usd`
（本来の唯一の正であるべき値）から読み込むよう変更。パッチ: 01番に同梱。

**次のアクション（実装とは別、運用判断）**: 修正適用後に露出する$168,874の
差分について、(a) quarantine 101件の再分類・再統合、または (b) 正当な
許容差として`broker_equity_bridge_tolerance_usd`を実態に合わせて明示的に
引き上げる、のいずれかをユーザー/運用者が判断する必要がある。

**Status**: ✅ APPLIED（2026-08-23 12:45 JST 適用済み）。$168,869.89の
未説明差分が実データで露出することを確認済み。運用判断（quarantine再分類 or
許容差の明示的引き上げ）はまだ未実施

### 🟡 監査3: collect_broker_bars()のページネーション未処理バグ（pairwise_correlationの入力汚染）

**発見**: `fetch_bars(symbol, timeframe, limit=5)`が`start`を明示しないため
デフォルトの30暦日ウィンドウにフォールバックし、Alpaca APIが返す昇順（古い順）
の最初5本＝**そのウィンドウの最古の約5営業日**を常に取得していた。
`data/raw/broker/broker_*.json`の`marketdata/bars`スナップショットを全件確認した
結果、**収集日に関わらず全て2026-07-23〜2026-07-29の同じ1週間が返り続けており、
`next_page_token`は一度も使われていなかった**。このため、R5-v2 promotion gateの
pairwise correlation条件（2026-08-14実装）は何ヶ月も同じ凍結された19営業日の
窓で計算され続けていた。

**修正**: `start`を明示的に「`limit`営業日相当をカバーする暦日数だけ遡った日時」
として渡すよう変更。加えて`pairwise_correlation.py`に`check_data_freshness()`を
新規追加し、`check_go_no_go.py`のpromotion readiness評価に配線（最新bar日付が
5日以上古い場合`available=False`として明示的にstale扱いにする）。
synthetic/不正タイムスタンプ（2026-04-21スナップショットの一部にUnix epoch秒の
生整数が`"t"`フィールドに混入していたバグ）のフィルタも同時に修正。
パッチ: `02_*.patch` + `03_*.patch`（適用済み）

**Status**: ✅ APPLIED（2026-08-23 12:45 JST 適用済み）。既存の
data/raw/broker/スナップショットは古いままのため、次回`stock_swing_news_collection`
cron実行以降、新しい日付のbarが蓄積され次第pairwise correlationが再度
計算可能になる想定（現時点では鮮度チェックにより`available=False`と
正しく表示されることを確認済み）

### 🟡 監査4: check_go_no_go.pyの3条件が実質恒久PASS化していた

Required条件7件のうち3件を実データで精査した結果、**実質的に一度trueになったら
未来永劫trueであり続ける**設計だったことが判明:

1. `cron_jobs_healthy`: 同じ`summary`内の`health.status`をそのまま再読するだけで、
   個々のcronジョブの実行履歴は一切見ていなかった（実質的に無検証）。
2. `paper_3day_confirmation`: `docs/go_no_go_report_20260731.md`という**単一の
   固定ファイル**を`"07-30 ok"`のような固定文字列でgrepしていた。このファイルは
   07-31判定後更新されておらず、一度trueになれば恒久的にtrueであり続ける設計。
3. `console_summary_freshness`という条件自体が**存在しなかった**
   （監査1のバグにより凍結したconsole summaryを検知する手段がなかった）。

**修正**: (1) `console.adapters.system_adapter.SystemAdapter._check_cron_run_history()`
（console自身の`/health`が使う同じロジック）を呼び出す実際のcron実行履歴検証に変更、
(2) `data/tracking/pnl_state.json`の`daily_snapshots`から直近7日間のローリング
ウィンドウで3日以上の実データ確認に変更、(3) `console_summary_freshness`条件を
新規追加（`run.timestamp`が30時間以内であることを要求）。パッチ: `04_*.patch`

**Status**: ✅ APPLIED（2026-08-23 12:45 JST 適用済み）。適用直後の
`check_go_no_go.py`実行で`console_summary_freshness`が実際に❌（46.9時間経過）を
検知し、監査1のバグによる凍結を正しく可視化することを確認済み

### 🟢 監査5: f8_clean_records_analysis.pyの計算式バグ2件

1. **expectancy計算式バグ**: `expected_value`が標準的な期待値定義のどれにも
   一致しない式で計算されており、実データ（252トレード、実際の平均PnL/トレード
   = -$81.64）に対し**-$10,772.71**という2桁以上乖離した値を返していた。
   標準的な`win_rate*avg_win - loss_rate*avg_loss`（`net_pnl/count`と代数的に
   一致するべき値）に修正し、実際に一致することを確認（修正後: -$81.64）。
2. **max_drawdown分母誤り**: `peak`の初期値が0.0（累積PnLの高値）になっており、
   累積PnLがプラスに転じるまでドローダウンが一切記録されず、かつ小さいピーク
   （実データで+$1,443.75）を分母にすると通常規模の損失が無意味に大きい%に
   見えていた。`baseline_equity`（$1,000,000）を初期値・分母にする実装に修正
   （修正後: 11.58% → 9.28%、より正確な値）。

パッチ: `05_*.patch`（適用済み）

**Status**: ✅ APPLIED（2026-08-23 12:45 JST 適用済み）。実データ再実行で
expected_value=-81.64=avg_pnl一致、max_drawdown=9.28%を確認済み

### 監査結果を踏まえた09-15 Go/No-Go判断への影響

上記の修正は**いずれもトレーディングロジック（発注判定・ポジションサイジング・
ガードレール判定）自体は変更しない**。影響は全て「状態の可視化・判定ロジックの
正確性」に限定される。**2026-08-23 12:45 JST、ユーザー承認により全6件を本番
適用済み**。適用直後の`check_go_no_go.py`実行で、意図通り
`console_summary_freshness`が❌（46.9時間経過）を検知し、equity_bridgeの
`unexplained_diff`が$168,869.89・`within_tolerance=false`に変化することを確認。
フルテストスイート2065 passed / 2 skippedも再確認済み。

**残っている運用判断**: 監査2（equity bridge）の$168,869.89の未説明差分に
ついて、(a) quarantine 101件の再分類・再統合、または (b) 正当な許容差として
`broker_equity_bridge_tolerance_usd`を実態に合わせて明示的に引き上げる、の
いずれかは**このロードマップ更新時点では未実施**。09-15移行判断の前提となる
「台帳が正しく資産を反映しているか」に直結するため、Pre-Launch Gate Review
（09-08〜09-12）までにこの判断を行うことを引き続き推奨する。

**やらないこと（本監査の対応方針、引き続き有効）**:
```
❌ 監査2で露出した$168,869.89差分について、勝手にtolerance値を引き上げてpassさせない
   （選択肢(a)/(b)のどちらかの明示的なユーザー判断を待つ）
❌ 発注ロジック・ポジションサイジング・ガードレール閾値には一切手を加えない
   （本監査は「状態の可視化・判定ロジックの正確性」のみが対象）
```

---

## 2026-08-23（第2弾）: 投資戦略レビュー + Claude独立検証パケット + 即日修正6件

**背景**: 上記のシステム監査に続き、ユーザーから「投資戦略の改善計画・改善内容自体を
レビューして改善点を提案」を依頼され、その後「Claudeで検証するための材料準備」
「問題なければすぐに実装すべきものに対応」と依頼が連鎖した。

**戦略レビュー主張（14件、詳細は`docs/strategy_review_claude_validation_20260823/
CLAIMS_MATRIX.md`）**: attributable 49件のedgeはbootstrap 90%区間
0.564】2.125で統計的に未確定、R11バックテストは同日close look-aheadバイアスと
survivorship biasあり、"breakout"の実装は単純な20日リターンしか見ていない、
high-confidence sizing 1.2倍はcapでclipされ実質的にno-op、promotion PFの母集団が
attributableではなく全closed 252件、top5集中度の分母がgross exposure基準なのに
40%閾値はequity基準、dry-runが本番と同じconsole summaryを上書きできる、など。

**Claude独立検証パケット**: `docs/strategy_review_claude_validation_20260823/`新規作成。
匿名化252件tradeスナップショット、bootstrap再計算スクリプト、claims matrix、
実装価値評価案、外部一次資料（賣否両論含む）、SHA-256マニフェストを同梱。
自己検証（source_filesをライブリポジトリとdiff、主張8件を実コードで再検証）中に
**第7のバグを発見**: `SystemAdapter._fetch_one_job_runs()`がJSON解析成功のみを
見て実際の`lastRunStatus`を一切評価していなかった（上記監査の`cf6bc75`修正自体に
残っていたギャップ）。

**即日実装・適用済み（6件、commit `f204336`、全て発注ロジック未変更・状態可視化のみ）**:
1. dry-run証跡の分離（`ConsoleSummary.dry_run`/`invocation_source` +
   `check_go_no_go.py`の`console_summary_not_dry_run`新規条件）
2. cron健全性の実status評価（`system_adapter.py`に`lastRunStatus`/
   `consecutiveErrors`チェック追加）
3. paper 3日gate強化（`decisions_generated>0`のsnapshotのみカウント）
4. promotion PFをattributable 49件限定に変更（PF=1.082を確認）
5. top5集中度をequity/gross/HHIに分離（gross 50.7% vs equity 31.7%）
6. `breakout_momentum_v1.yaml`/`event_swing_v1.yaml`のUNUSEDフラグ注記

**検証**: フルテストスイート2065 passed / 2 skipped。実`--dry-run`で新規4条件が
意図通り動作することを確認済み。

**未実施（Paper A/B先行推奨、IMPLEMENTATION_VALUE.md参照）**: signal_strengthと
exit/sizingの切り離し、high-confidence sizing no-op修正、R11再構築（t+1約定、
point-in-time universe、資金制約再現）、ETFローテーション等の独立戦略はいずれも
未着手のまま。

**スキル化**: 今回のワークフロー（監査→claims matrix→パッチ→テスト→承認後適用→
検証パケット）を`skill_workshop`で`evidence-based-system-audit`としてスキル化。
ユーザー承認済み、プロポーザルID`evidence-based-system-audit-20260823-d6294d652d`
（pending状態）。
