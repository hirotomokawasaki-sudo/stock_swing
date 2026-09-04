# stock_swing 改善計画（R0-R8 改訂版）

**改訂日**: 2026-07-13（Codex Review G1-G10 対応 + min_hold 実装）  
**旧 P0-P17 体系は廃止。本ファイルのみが正式な改善計画。**

> ⚠️ **別トラック注記（2026-08-19追加）**: ブローカー移行（Alpaca → IBKR）は
> 本ファイルのR0-R9ロードマップ（戦略パフォーマンス評価）とは完全に独立した
> 別トラックとして進行中。9/15 Go/No-Go判定には一切影響しない。
> 計画・進捗は `docs/broker_migration_ibkr_plan.md` を参照（Track A完了済み、
> Track BはD0＝移行開始日確定待ち）。

> 📎 **R15（2026-08-27、同日訂正あり）**: 既存バックテスト（R11-B〜R14）が全て
> 日足OHLCのみで、本番（4回/日cron + intraday 5分足二段階判定）との粒度不一致を
> ユーザーが指摘。本番同一の`broker.fetch_bars(timeframe="5Min")`で既存日足
> キャッシュと同一期間（2024-08-15〜2026-08-14、2年分）の5分足データを全69銘柄
> 取得完了（`data/r15_intraday_5min_cache/`、211MB、21.9分）。intraday対応
> バックテストエンジンを構築・初回検証: intraday boost効果はPF+0.83%/
> net_pnl+1.19%と小さく正方向（v4エンジン=排他制御あり条件）。**同日追記で
> 08-26発見の1銘柄1ポジション排他制御アーティファクトとの交差検証を実施した
> ところ、排他制御なし条件ではPF-0.32%/net_pnl-0.14%と符号が反転**。両条件とも
> |ΔPF|<1%のため「intraday boostは実質PF/net_pnlに中立、効果の大きさは測定誤差
> 相当」に結論を改訂。R11-B〜R14の既存検証が日足のみだったことによる歪みは
> 方向・大きさいずれも無視できる水準という大枠の結論は変わらず。詳細は下部の
> 該当日付エントリ参照。

> 📎 **最新ステータス（2026-08-26時点）**: attribution_coverage_pct=96.2%、
> quarantine=6件（quarantined_pnl=-$44,670）、equity_bridge unexplained_diff=$49,793、
> Go/No-Go残ブロッカーはcircuit_breaker/guardrail_hard_haltのみ（degraded、8連敗
> streak由来）。戦略候補の最新状態: R11-Cは見送り最終確定、R14 dip-buyは
> レジームスイッチ型へ設計修正提案、R13-D sector rotationはheadline設定見直し必要
> （いずれも本日。0226-08-26対応、詳細は下部の該当日付エントリ参照）。

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
paper環境で有効化。

**⚠️ 08-28中間レビュー: cron未登録が発覚（08-21 R9レビューと同型の記載ミス、
2回目）**。当初「cron登録済み: `stock_swing_volatility_adjusted_stop_review_20260828`」
と記載していたが実際にはジョブ未登録だったため、08-29にユーザー確認をきっかけに
発覚・手動でレビュー実施。

**08-29実施レビュー結果（n=6論理トレード、8-14以降のstop_loss exit全件）**:
- 明確な悪化事例（widen調整が損失拡大）: **0件**（最重要リスクは未観測）
- 明確な改善事例: QTUM 1件（tighten判定により早期exit、無調整比で約$650〜700の
  損失回避を反事実分析で確認）
- 残り4件（AVGO/ASML/CHPX/FTXL/NVDA）はギャップ/日中急落が閾値の微調整幅を
  圧倒しており、調整の有無による差はほぼ判別不能
- **判断: n=6は結論を出すには小さすぎるため、閾値レンジ（0.5〜1.75）は現状維持**。
  次回レビューは09-08 Pre-Launch Gate Review（第2弾）に合わせてcron登録
  （`stock_swing_volatility_adjusted_stop_review_20260908`、登録後`cron list`で
  実在確認済み）
- 詳細: `docs/daily_logs/2026-08-29.md`

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

> 📌 **2026-09-08 レビュー5件（volatility_adjusted_stop / R16 lot_level_exit /
> R14 dip-buy / R13-D配線判断 / Plan C昇格）の判断基準は
> [`docs/review_criteria_20260908.md`](review_criteria_20260908.md) に事前固定済み
> （2026-09-05）。当日は同ドキュメントの数値条件との照合から始めること。
> 総論: 経済性ゲート現在値 n=45 / PF 0.530 / expectancy -$551 = NO-GO を全判断の
> 前提とする。JP半導体 spillover（Phase 2.5）は半導体集中を増やす方向のため
> 配線優先度低。**

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
                         までに実施 → **2026-08-26に前倒し実施、下記参照**
2026-08-26         ✅ attribution_coverage_pct回復（ロードマップ監査で発見された
                         未対応Go/No-Goブロッカー、ユーザー承認、xhigh reasoningで実施）。
                         08-24 rebuildの副作用で98.8%→74.6%（現在75.2%）に低下していた
                         attribution_coverage_pctがGo/No-Go Required閘値（95%）をブロック
                         中だったが、既存の`scripts/rf8b_recover_attribution.py`（2026-07に作成済み、
                         trade_events.jsonl/pending_exit_reasons.json/decision JSONとの
                         照合でexit_reasonを復元）を実行したところ72件回復・96.2%まで回復
                         （target≥95%達成）。バックアップ: `pnl_state.backup_rf8b_
                         20260826_122809.json`、手動スナップショット: `pnl_state_manual_
                         snapshot_20260826_2127_before_rf8b.json`。テストスイート**2235
                         passed / 2 skipped**、`verify_rebuild_integrity.py`もPASS。
                         check_go_no_go.py再実行で`attribution_coverage_pct`が✅に変化
                         したことを確認済み（残13件はtrade_events/decision JSONとも照合不可、
                         ルックバック10日でも未発見の古い05-12前後のtrade中心、対応不要）。
2026-08-26         ✅ R11-C（4候補全滅判定、2026-08-15）をR13-C確立の厳密手法（t+1約定/
                         PIT universe/conservative exit/slippage/portfolio cap）で全候補
                         再検証（ロードマップ監査で発見された旧手法問題への対応）。新規
                         `scripts/r11c_v2_rigorous_rerun.py`をv4エンジンをそのままimport
                         して作成（baseline出力がv4本家と完全一致することを確認済み）。
                         **重要発見: RSI逆張りフィルタの旧結論（baselineと実質差なし）が
                         覚された**——厳密手法ではPF+16%改善（1.9251→2.2371）、且つ
                         walk-forward後半期（市場悪化局面）でのPF維持能力がbaselineの約
                         1.8倍（比率0.502 vs 0.281）と、旧手法では検出できなかった優位性が
                         確認された。セクター相対強度・ニュースセンチメントは旧結論（見送り）を
                         支持。決算近接は結論が逆転（改善）したがn=103と最小サンプルのため判断
                         保留。**次アクション推奨**: RSI逆張り候補の閘値グリッドサーチ+rolling
                         walk-forwardでの追加検証。詳細: `docs/r11c_v2_rigorous_rerun_
                         20260826/README.md`
2026-08-26         ✅ attribution_coverage_pct回復（rf8b_recover_attribution.py，
                         xhigh reasoningで実施）。72件回復、75.2%→96.2%達成（target≥95%）。
                         check_go_no_go.pyでattribution_coverage_pct項目が✅に変化した
                         ことを確認。残るGo/No-Goブロッカーはcircuit_breaker/guardrail_hard_halt
                         （degraded、8連敗streak由来）のみに整理。テストスイート**2235 passed /
                         2 skipped**。
2026-08-26         ✅ R11-C逆張り候補を閘値グリッドサーチ(60-85)+rolling walk-forwardで
                         追加検証。自己発見バグ（比較不可能rollの誤判定）修正し全閘値が形式上Supportedと
                         判定されたが、追加検証で効果の真の原因が、1銘柄1ポジション排他制御によるタイミング
                         シフトと判明。本番のRiskValidator/BreakoutMomentumStrategy/paper_demo.pyを
                         実読し同目的の排他制御が存在しないことを確認し、排他制御を除去した本番相当検証で
                         **RSI逆張りの改善効果はほぼ消滅**（PF 2.1246→2.1370、net_pnlはむしゃ23.6%
                         減）。**最終結論: 2026-08-15の旧判定（4候補全滅、見送り）が確定**。新しい
                         アンチパターン（バックテストエンジンの実装詳細が戦略効果と見分けがつかない）を発見。
                         詳細: `docs/r11c_rsi_threshold_grid_rolling_wf_20260826/README.md`,
                         `docs/r11c_rsi_no_symbol_exclusivity_20260826/README.md`
2026-08-26         ⚠️ R14 dip-buyに同種の排他制御アーティファクトチェックを横展開（新規
                         `scripts/r14_no_symbol_exclusivity_check.py`）。結果は混在: (a)
                         全期間比較は逆転（dip-buy優位\u304smomentum優位に、PIT: 1.963→1.530 vs
                         1.854→2.063）でGO判定一部未支持。(b) しかし最重要の発見「チョップ相場での
                         momentum弱点補完」は同条件でも頑健（dip-buy PF=1.1811の黒字 vs
                         momentum PF=0.6414の赤字、Phase1自体の0.646と一致）。修正された価値
                         提案: 常時稼働ではなく「レジーム検知連動型（chop検知時のみ有効化）」として
                         設計し直すべき。09-08本番配線判断レビューでの反映が必要。詳細:
                         `docs/r14_no_symbol_exclusivity_check_20260826/README.md`
2026-08-26         ✅ R13-D `run_rotation()`の`min_members`未実装バグを発見・修正実施。
                         headline設定（top_n=2）でSharpe 1.370→1.230に低下しMIXED判定に
                         転落する一方、top_n=1（1.473）・lookback=126d（1.415）はGO継続——
                         **headline設定固有の脆弱性であり戦略自体は引き続き支持**と判明。
                         `r13d_etf_sector_rotation_phase1.py`に`--enforce-min-members`
                         フラグを新規実装（デフォルトは旧挙動保持、後方互換性確認済み）。テストスイート
                         **2235 passed / 2 skipped**。次アクション: headlineをtop_n=1等に
                         変更し新headlineとして採用するかを09-08レビュー前に決定（未実施）。詳細:
                         `docs/r13d_min_members_check_20260826/README.md`
2026-08-24         ✅ pnl_state.json rebuild実行（見落とされていたブローカー注文履歴84件
                         を復元）+ 安全装置の新規バグ3件を発見・修正。closed 252→335件、
                         equity_bridge unexplained_diff $168,869.89→$160,998.66に
                         改善（部分改善、quarantine再統合自体は未実施、残る運用判断は引き続き
                         Pre-Launch Gate Reviewで実施）。attribution coverage（exit_reason
                         基準）は98.8%→74.6%に低下（新規復元トレードの意思決定ログ自体が
                         存在しないための相対低下であり儸化ではない、Pre-Launch Gate Review資料に
                         明記必要）。詳細: `docs/rebuild_20260824/`
2026-08-26         ✅ equity_bridge $161,026未説明差分の前倒し対応完了（ユーザー承認、
                         xhigh reasoningで実施）。quarantine 102件を全件実ブローカー注文
                         データで一件一件照合した結果、当初の想定（「真の未回収損失の
                         再統合」）は誤りと判明。96件（58 exit_broker_order_id）は
                         08-23のfetch_all_orders() pagination修正以前のバグで生成された
                         **幻の重複**（対応するexit_broker_order_idのブローカー実
                         filled_qtyを`trades`側の正常closedエントリが既に100%カバー
                         していることを個別確認）で、実損失ではなかった。
                         `quarantined_trades`リストから該当96件のみ削除（`trades`
                         リストや`cumulative_realized_pnl`には一切影響なし）。
                         バックアプ: `pnl_state_backup_20260826_041753_before_
                         quarantine_cleanup.json`、削除ログ: `docs/quarantine_
                         cleanup_20260826_removed_96_phantom_dups.json`。
                         結果: quarantine 102→6件、quarantined_pnl -$155,904→-$44,670、
                         **unexplained_diff $161,026→$49,793（69%削減）**。テスト
                         スイート**2235 passed / 2 skipped**、`verify_rebuild_integrity.py`
                         も全件PASS。残も6件（KLAC split anomaly -$39,342 / CRWD
                         reversed chronology -$1,999.9 / CRWD・KLAC部分説明 -$3,657）は
                         真の未回収分として保留、Pre-Launch Gate Reviewで運用判断継続
2026-08-23（夜）    ✅ equity_bridge根本原因の第2のバグを発見・修正。`fetch_all_filled_
                         orders()`が`status=='filled'`のみでフィルタしており、「部分約定後に
                         キャンセルされた注文」（status='canceled'がつfilled_qty>0）を完全に
                         除外していた。実データでADBE/MSFT/CDNS/AVGOの2026-06-01付計402株分の
                         実約定が欠落していたことを確認。修正後`--dry-run`検証で時系列逆転
                         トレードが9件→1件（既知のCRWD分割問題のみ残存）へ大幅改善。
                         テスト新規7件、フルスイート2119 passed/2 skipped。
2026-08-23（夜）    🚨 実際rebuild実行（本番`pnl_state.json`対象、`--backup`付き）で
                         **49件のattribution（strategy_id/decision_id/run_id等）が全消失
                         するインシデント発生**。`test_r8v2_ml_readiness.py`の実データテスト
                         失敗で検知、rebuild直前の自動バックアップから即座復元（diffでバイト
                         単位一致を確認）。根本原因: `rebuild_pnl_state_from_broker.py`の
                         `--preserve-attribution`はexit_reason/entry_signal_strength/
                         quarantined_tradesのみ復元し、strategy_id等の起源メタデータは
                         一切保護していなかった。`load_existing_attribution()`/
                         `apply_attribution()`を拡張しPROVENANCE_FIELDS（strategy_id/
                         original_strategy_id/decision_id/run_id/experiment_id等）も
                         保存・復元するよう根本修正。テスト新規7件、フルスイート2126
                         passed/2 skipped。**本番の実际のrebuild実行は今夜はしていない
                         （別日態重に実施）**。インシデント詳細: `docs/equity_bridge_root_
                         cause_20260823/INCIDENT_rebuild_lost_attribution.md`

2026-08-27         ✅ R13-D新headline選定・walk-forward検証完了。08-26発見の
                         min_membersバグ修正後の代替候補2つ（top_n=1/63d、
                         top_n=2/126d）をfull-period+walk-forward(period1/
                         period2)の3段階で検証。top_n=1はperiod1単独で
                         equal-weightベースラインに負ける（MIXED）ことが判明、
                         **top_n=2/lookback=126d/hold=21dが3段階すべてでGO**
                         と確認し新headline候補として採用推奨。09-08レビューで
                         正式決定待ち。テストスイート`pytest -k r13d`: 10 passed。
                         詳細: `docs/r13d_new_headline_selection_20260827/README.md`
2026-08-27         ⚠️ R15 intraday boost効果の訂正（同日追記）。08-26発見の
                         1銘柄1ポジション排他制御アーティファクトとの交差検証を
                         実施したところ、排他制御なし条件ではPF変化が
                         +0.83%→-0.32%と符号反転（net_pnlも+1.19%→-0.14%）。
                         両条件とも|ΔPF|<1%のため「intraday boostは実質PF/
                         net_pnlに中立」に結論を改訂（当初の「わずかに正」は
                         撤回）。R11-B〜R14の日足のみ検証が歪みを生んでいな
                         かったという大枠の結論は変わらず。テストスイート
                         `pytest -k "r15 or intraday"`: 18 passed。詳細:
                         `docs/r15_intraday_backtest_20260827/README.md`
                         （追記セクション）
2026-08-27         ✅ R13-B sizing側修正を正式実装（デフォルト無効フラグ）。
                         08-26検証済みのconfidence_multiplier no-opバグ修正
                         （リスク予算への事前適用方式）を`SIZING_CONFIDENCE_
                         MULTIPLIER_RISK_BUDGET_FIX`環境変数フラグ（デフォルト
                         false）の下で`position_sizing.py`に実装。フラグ無効時は
                         既存の（バグを含む）本番挙動を完全保持、有効時のみ
                         リスク予算が支配的な場合にconfidenceブーストが機能する。
                         新規テスト5件追加（boost有効/無効、cut側の非回帰、他
                         キャップ支配時のno-op維持を確認）。テストスイート
                         `pytest tests/unit/test_position_sizing_policy.py`:
                         19 passed。フラグ有効化はPnL影響エビデンス
                         （attributable標本≥30〜90件目安）が揃うまで保留。詳細:
                         `docs/r13b_sizing_fix_implementation_20260827/README.md`

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

2026-08-23        ✅ R13-A  ヒストリカル検証完了（simulate_stop_loss_deepening.py新規作成、
                         全252件では明確に悪化、attributable 49件限定では単一トレード
                         （NBIS）依存の不安定な改善のみ）→ **paper A/BはSTOP HOLD**
2026-09中旬頃〜    🔲 R13-A  R13-Cでattributable銘柄数が増えた後、同検証を再実施して頑健性を
                         再確認（R13-Cと並行進行可）
2026-08-23        ✅ R13-B  Option B（exit側切り離し）ヒストリカル検証完了（simulate_signal_
                         strength_exit_decoupling.py新規作成）。全110件-$1,804悪化、
                         attributable 41件+$1,457改善だが両方とも変化トレード数が2〜9件と
                         極めて少なく確証不十分 → **paper A/BはR13-C後に先送り**
2026-09中旬頃〜    🔲 R13-B  R13-Cでattributable銘柄数が増えた後、exit側Option Bを再検証。
sizing側Option A・confidence_multiplierバグ修正は別途検証手法を設計して着手
2026-08-23        ✅ R13-C  最小構成（t+1約定、point-in-time universe）実装・検証完了
                         （r11_backtest_engine_v2.py新規）。v1は全体n=1415中1029件（73%）が
                         実際の銘柄導入日以前に発生していたことを確認。修正後PF=2.069（v1
                         1.733）。修正版の月次PF推移が本番実績と方向性一致（強い外部検証）。
                         go-live以降PF=1.448（90%CI[1.099,1.891]、1.0を上回る）だが
                         exit側look-ahead/slippage未対応（項目3・5）のため楽観側に偏る可能性高し
2026-08-23        ✅ R13-C  項目3（保守的OHLC exit）・項目5（slippage）実装・検証完了
                         （r11_backtest_engine_v3.py新規）。live以降PF=1.453（修正前1.448と
                         ほぼ不変）、90%CI[1.210,1.750]で幅が狭まり下限上昇。往復30bpスリッパージ
                         でもPF=1.426維持。本番との方向性一致も維持
2026-08-24        ✅ R13-C  項目4（exposure/sector/cluster cap）・6（rolling walk-forward+
                         embargo）・7（trial registry）実装・検証完了、R13-C全項目COMPLETE
2026-08-23        ✅ R13-D  ETFセクターローテーション Phase 1（フィージビリティ検証）完了・GO判定
                         （r13d_etf_sector_rotation_phase1.py新規）。top2/63d/21dローテーションが
                         SPY/均等加重両ベースラインをSharpeで上回る（1.370 vs 1.255/0.967）。
                         実行ラグ・レジーム分割・単一ETF除外でも頑健。Phase 2（戦略設計）へ
2026-08-23        ✅ R13-D  ETFローテーションPhase 2（戦略設計コード実装）完了。
                         SectorMomentumFeature/SectorRotationStrategy新規。Phase 1との
                         21チェックポイント全一致を自己検証（2件のオフバイワンを発見・修正）。本番未配線
2026-08-24        ✅ R13-D  ETFローテーションPhase 3（リバランス状態管理実装）完了。本番配線（cron
                         接続）は未実施（要ユーザー承認）。コスト/スリッパージ再検証は引き続き未着手。
                         JP overnight spilloverはIBKR接続確立待ち継続

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
| 🔴 P1 | **R13-A** | **STOP HOLD**（2026-08-23検証完了） | 全252件では明確に悪化、
attributable限定では単一トレード依存の不安定な改善のみ。paper A/Bには進まない |
| 🟡 P1 | **R13-B** | **sizing側修正実装済み・デフォルト無効**（2026-08-27） | exit側
Option Bヒストリカル検証完了。変化トレード数少なく結論保留。sizing側:
confidence_multiplier no-opバグの修正コードを`SIZING_CONFIDENCE_MULTIPLIER_
RISK_BUDGET_FIX`環境変数フラグ（デフォルトfalse）の下で実装、テスト5件追加、
本番挙動は現状維持。PnL影響のエビデンス（attributable標本≥30〜90件目安）が
揃うまでフラグ有効化は保留（`docs/r13b_sizing_fix_implementation_20260827/
README.md`） |
| 🟢 P2 | **R13-C** | **強い肯定的知見（項目1/2/3/5完了）**（2026-08-23） | t+1 fill+
point-in-time universe+保守的OHLC exit+slippage全て実装。live以降PF=1.453
（90%CI[1.210,1.750]、保守的補正後もほぼ不変）。本番と方向性一致も維持。残も4/6/7
項目（exposure/sector cap等）は未実装 |
| ⚠️ P3 | **R13-D** | **新headline選定済み（2026-08-27）**: top_n=2/lookback=126d/
hold=21dがfull-period+walk-forward前半+後半の3段階すべてでGO判定 |
ETFセクターローテーション戦略自体は引き続き支持される。08-26発見のmin_members
バグ修正後、代替候補top_n=1はwalk-forward前半でMIXEDに転落するため不採用、
top_n=2/lookback=126dを新headlineとして採用推奨（`docs/r13d_new_headline_
selection_20260827/README.md`）。09-08レビューで正式決定待ち。Phase 2戦略
コード実装、Phase 3（リバランス状態管理）実装済み。JPspilloverはshadow
継続中、研究段階、本番影響なし |

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

**⚠️ 2026-08-26追記（ロジックバグ発見、未対応）**: `evaluate_trend()`の条件分岐順序に
不具合を発見。件数が大幅に減少しても、残存quarantine中に前回スナップショットより新しい
`entry_time`が1件でもあれば`if count_delta > 0 or new_quarantine_detected:`が優先され
誤って"growing"と判定される（`count_delta < 0`のチェックが後回しになっているため）。
実際08-26のquarantineクリーンアップ（102→6件、実損失ではない重複削除）直後に実際に
発生した（実害は表示上の誤警告のみ）。修正案: `count_delta < 0`の判定を
`new_quarantine_detected`より先に評価するよう順序変更。優先度低（影響は表示のみ）、未対応。

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

### 2026-09-04 第2回中間レビュー（Plan B/C/D/E）

**👤 ユーザー決定（2026-09-04 16:24 JST）**: Plan Cのpaper_ab昇格判断は即日判断せず、
**09-08の他レビュー4件（lot_level_exit診断・volatility_adjusted_stop・R14 dip-buy・
R13-D配線判断）とまとめて判断する**。判断用リマインダーcron登録済み（登録後にAPI getで
実在確認済み: `stock_swing_plan_c_promotion_decision_20260908`、09-08 10:15 JST、
他レビュー完了後に実行）。それまで実装・設定変更は一切行わない。

前回（2026-08-21）と同一の方法論で再集計した。`data/tracking/pnl_state.json` の
**closed trade** を対象に、各shadow/diagnosticログで **true 判定が出た同一銘柄に
ついて、判定直後15分以内に entry した実トレード**のみを紐づけて集計。
観測期間は各ログとも 2026-08-07（Plan D/Eは08-07）〜 2026-09-03。

- **Plan B（volatility_gate）**: `data/volatility_gate_shadow_log.jsonl` は
  **1192件中 would_block=true 53件（4.4%）**、対象は **NBIS 37件 / SMCI 16件**
  のみ。true 判定直後15分以内の closed trade は引き続き **0件**。
  **推奨アクション: shadow継続**。true/false positive の実例が依然ゼロのため
  昇格判断の材料がない。
- **Plan C（distance_from_high）**: `data/distance_from_high_log.jsonl` は
  **1192件中 is_bounce_candidate=true 411件（34.5%）**、対象23銘柄。true 判定と
  紐づいた closed trade は **17件**（前回8件 → +9件）で、**5勝 / 12敗
  （負け比率70.6%）**、合計PnL **-11,015.13**（勝ちトレード計 +9,144.84 /
  負けトレード計 -20,159.97、1件平均 -647.95）。前回設定した昇格条件
  「**サンプル10件以上かつ負け比率60%超**」を**両方満たした**。前回レビュー以降に
  closeした9件だけ見ても 2勝7敗（負け比率77.8%）で悪化傾向が継続。
  **推奨アクション: paper_ab昇格を提案（ユーザー承認待ち）**。このフィルタが
  activeなら過去4週で紐づきトレードの純損失 -11,015 を回避できた計算になる
  （MRVL +3,297 / PATH +2,636 / MRVL +1,944 等の勝ちも同時にブロックされる点は
  トレードオフとして明記）。**昇格作業自体は未実施** — ユーザーの明示的承認を
  得てから paper_ab 化する。
- **Plan D（news_sentiment）**: `data/news_sentiment_shadow_log.jsonl` は
  **1143件中 is_negative_sentiment_buy=true 26件（2.3%）**、対象9銘柄。紐づいた
  closed trade は **2件**（CRDO -1,658.96 / TSLA +1,000.82）で **1勝1敗、合計
  -658.14**。閾値 -0.34 の発火自体は継続しているが outcome サンプルが少なすぎる。
  **推奨アクション: shadow継続**（閾値変更・昇格とも行わない）。
- **Plan E（rsi_diagnostic）**: `data/rsi_diagnostic_shadow_log.jsonl` は
  **1143件中 is_overbought=true 121件（10.6%）**、対象8銘柄。紐づいた closed
  trade は **4件のまま増加なし**（前回と同一の4件: SKYY +463.33 / MSFT -17.25 /
  SNOW -81.80 / PATH -48.47）、**1勝3敗（負け比率75.0%）、合計 +315.81**。
  8/12以降 true 判定直後のエントリーが発生しておらず、サンプルが蓄積されていない。
  **推奨アクション: shadow継続**。第二候補の位置づけは維持するが、判定直後
  エントリーの発生自体が稀な点は次回レビューで「そもそも本フィルタが実トレードと
  交差する頻度が十分か」を含めて評価する。

**09-04時点の総合判断**:

- **Plan C のみ昇格条件を満たした**（n=17 ≥ 10、負け比率70.6% > 60%、累計PnL
  大幅マイナス）。**paper_ab昇格をユーザーに提案し、承認待ち**。承認までは
  observability（shadowログ）のまま変更しない。
- **Plan B/D/E は全て shadow 継続**。実装・設定変更は一切行っていない。
- 留意点: Plan C の true 率が34.5%と広く、フィルタとして採用した場合エントリー
  機会の約1/3をブロックしうる。paper_ab で「ブロックした場合のP&L差分」を
  A/B計測してから active 判断するのが妥当。

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
  ※ **2026-08-27追記**: この限界は既存R11-B〜R14全バックテストに共通する。本番はintraday
  5分足二段階判定も行っており、この機能は一度もバックテストされていない。R11-Cで発見した
  「1銘柄1ポジション排他制御によるタイミングシフト効果」などのアーティファクトは、日足の粒度の
  粗さが一因だった可能性がある。R15（2026-08-27）で2年分の5分足データを全兩69銘柄取得済み
  （`data/r15_intraday_5min_cache/`）。intraday対応バックテストエンジンの構築は未実施。
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

**⚠️ 2026-08-26追記（重要訂正）**: 上記の結論はR13-C確立以前の旧手法（同日終値約定、
slippage/PIT universeなし）に基づく。R13-Cの厳密手法（t+1約定・PIT universe・
conservative exit・slippage・portfolio cap）で全候補を再検証した結果、**RSI逆張り
フィルタのみ結論が覇る**（全体PF+16%改善: 1.9251→2.2371、市場悪化局面での
PF維持力がbaselineの約1.8倍）。セクター相対強度・ニュースセンチメントは旧結論
（見送り）を支持。決算近接は結果が逆転（改善）したがn=103と最小サンプルのため
判断保留。詳細・再現手順: `docs/r11c_v2_rigorous_rerun_20260826/README.md`。
次のアクション: RSI逆張り候補の閘値グリッドサーチ+rolling walk-forwardでの
追加検証 → **2026-08-26実施、下記参照**。

**2026-08-26追加検証（閘値グリッドサーチ+rolling walk-forward）**: 新規
`scripts/r11c_rsi_threshold_grid_rolling_wf.py`で00-90ばで閘値（60/65/70/75/80/85）
を事前登録基準でグリッドサーチ。全閘値が形式上はsupported判定だが、重要な
制約・発見2件:
(1) point-in-time universeのintro_datesが全銘柄2026年設定の既知制約により
    rolling walk-forwardの4分割中2分割が両方で0件取引で比較不可能だった（自己発見した
    判定バグを修正済み）。実効サンプルは2分割のみで当初期待より少ない
(2) 当初「gross/sector/cluster capによる間接的な資金再配分効果」と仮説したが
    `enforce_caps=False`検証で完全に同一の結果となり自己訂正。真の原因は
    「1銘柄1ポジションの排他制御による同一銘柄のエントリータイミングシフト」と判明
    （除外トレード自体の直接PnLは+$1,123.78のみで限定的、全体改善+$3,047.83の
    大半はタイミングシフト由来）。好材料: 閘値カーブは70付近にピークを持つ滑らかな
    山型で〈75ちょうどへの不自然なスパイクなし」（overfittingの強い兆候なし）。
判断: R11-D進出の根拠としてはまだ不十分。PIT universe制約の根本対応と、
本番の排他制御・他ゲートとの相互作用での再現性確認が先決問題。
詳細: `docs/r11c_rsi_threshold_grid_rolling_wf_20260826/README.md`

**⚠️️ 2026-08-26後続追加検証（最終訂正、重要）**: 上記の「タイミングシフト効果」が
本番でも発生するかを確認するため、本番の意思決定パス（`RiskValidator.validate()`,
`BreakoutMomentumStrategy.generate()`, `EntryFilterEngine.filter()`, `paper_demo.py`の
金額上限チェック）を実際に読んだ結果、**どの層にも「既存保有銘柄への新規buyを
ブロックする」ロジックは存在しない**（金額上限までは同一銘柄への追加buyを許可、実際
`pnl_state.json`でLRCX/IBM等がlots複数保有を確認）ことを確認。新規
`scripts/r11c_rsi_no_symbol_exclusivity.py`で、1銘柄1ポジション制限を完全に除去した
本番相当検証を実施したところ、**RSI逆張りの改善効果はほぼ消滅**（PF 2.1246→2.1370、
+0.58%で誤差範囲、net_pnlはむしゃ23.6%減少）。つまり一連の検証（v4厉密化→閘値
グリッドサーチ→排他制御除去）で発見した「RSI逆張りのPF+16%改善」はすべてv4エンジン
固有の実装アーティファクトであり、**本番相当の条件下では成立しない**ことが確定的に
判明した。**2026-08-15の旧結論（見送り）が、より慎重な検証を経てもなお支持される**。
詳細: `docs/r11c_rsi_no_symbol_exclusivity_20260826/README.md`。教訓:
バックテストエンジンの実装詳細（同時保有ポジション数制限等）が戦略効果と見分けが
つかない形で結果に混入しうるという新規アンチパターンを発見。

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

**⚠️ 2026-08-26追記（重大訂正）**: 上記の「reduce_sizeは穏当な効果（11%の候補にのみ影響）」
という結論は、**実際の本番メカニズムを正しく再現していなかったため誤り**だったことが判明。
2026-08-26夜、実際にBUYが完全にゼロになる事象をユーザーが観測し、本番コード（`paper_demo.py`/
`position_sizing.py`）を実読したところ、reduce_sizeは「新規注文のノーショナルを半減」では
なく、**ポートフォリオ全体の露出上限を半減する**ことが判明。既存保有が新上限を超えていれば
新規buyは「縮小」ではなく「完全ブロック」される二値的挙動。実際08-26夜はexposure=47.3%に対し
半減後上限が41.5%となり余裕枠ゼロで全候補ブロックされていた。

新規`scripts/r0v2_reduce_size_portfolio_level_check.py`で、本番同一の`PositionSizingPolicy`を
そのままimportしポートフォリオレベルの建玉追跡を含めて再シミュレートした結果：
**reduce_size発動中の新規候補117件中61件（52.1%）が完全ブロック**されていた（63日中13日は
全候補全滅）。PF自体はやや改善方向（1.4325→1.4970）で方向性は08-15検証と一致するが、
「どの程度・どのようにブロックするか」のメカニズム理解は大きく異なっていた。ユーザーの
直感（「想定よりブロックが強すぎる」）が正しかった。詳細:
`docs/r0v2_reduce_size_portfolio_level_20260826/README.md`

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
| ✅ P1 | **R11-C** | **旧結論（見送り）が最終確定（2026-08-15→ 08-26三段階検証で確認）** | 厳密手法ではRSI
逆張りのみ一時PF+16%改善を示したが、内訳を分解したところv4エンジン固有の〇1銘柄1ポジション
制限のアーティファクトと判明（本番には同目的の排他制御なし、金額上限まで同一銘柄追加buy可）。
排他制御を除去した本番相当検証では改善はほぼ消滅（+0.58%、net_pnlはむしゃ23.6%減）。
結論: 4候補全滅（見送り）の旧判定が最終確定。R11-Dへの候補なし |
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
検証パケット）を`skill_workshop`で`evidence-based-system-audit`としてスキル化・
ユーザー承認によりAPPLIED済み（プロポーザルID`evidence-based-system-audit-
20260823-d6294d652d`）。

---

## 2026-08-23（第3弾）: equity_bridge $168,869.89の根本原因特定 + 修正

**背景**: 監査2（equity_bridge）の未説明差分の処理方釕（(a)quarantine再統合 vs
(b)tolerance引上げ）をユーザーと検討中、quarantine 101件の内訳を実データで調査。

**発見**: 101件中70件（69%）が同一`exit_broker_order_id`を他のquarantine件と共有し、
かつ買いが売りより後の日付というFIFO会計として不可能な状態を確認。根本原因を実口座で
確定: `rebuild_pnl_state_from_broker.py`の`fetch_all_filled_orders()`が
`broker.fetch_orders(status='all', limit=500)`を**単発呼び出し**しており、
Alpaca APIはpaginationなしでは直近500件しか返さない。実口座で確認: 単発`limit=500`
呼び出しは2026-05-21以降の注文しか返さないが、完全ページネーションでは**2026-05-12から
存在**（約9日間・約200件の注文が黙って欠落）。FIFOマッチャーは欠落した古いbuyを検知できず、
手元にある次善（売りより後の日付）のbuyを誤ってマッチさせていた。101件中96件がこの1つの
原因で説明可能（残も1件はklac_split_anomaly、既知・別原因）。

**修正実施済み（commit `adad1db`）**:
- `broker_client.py`に`fetch_all_orders()`新規追加（`direction=asc`+`after`
  ページネーション、`max_pages`安全装置、`truncated`フラグ。既存`fetch_orders()`は
  後方互換のため無変更）
- `rebuild_pnl_state_from_broker.py`を`fetch_all_orders()`使用に変更
- 実口座で`fetch_all_orders()`実行（読み取り専用）→691件（2ページ、
  truncated=False）、2026-05-12〜08-20の完全履歴を取得できることを確認
- テスト8件新規追加。フルテストスイート**2073 passed / 2 skipped**

**残っている作業（未実施、別途承認必要）**: この修正は今後のrebuild実行を正しくするだけで、
既存quarantine 101件自体の再統合（選択肢(a)）は未実施。本番`pnl_state.json`の
書き換えを伴うため、rebuild実行にはユーザーの明示的な承認が必要。Pre-Launch
Gate Review（09-08〜09-12）までに(a)実施可否を判断することを推奨。

---

## R13: 収益性向上ロードマップ（「儲かるシステムにするには」、2026-08-23、ユーザー依頼）

**背景**: 2026-08-23の一連の監査（R0-v2、戦略レビュー、equity_bridge根本原因特定）は
すべて「システムの状態を正しく見せる」・「自滅的な損失を防ぐ」方向の修正で、
**収益を増やす方向の改善は含まれていない**ことをユーザーに指摘された。実データ分析の結果、
以下4件の収益性向上策を提案し、ユーザーが**3番（低勝率銘柄の恒久ブロックリスト化）を除く
全件を進める方向で承認**。除外理由: 既存のrolling PF gateがすでに同等の機能を
果たしており（MU/HPQ/MRVL等の高PF銘柄とINTC/AMZN/NBIS等の低PF銘柄を実際に分けて
いることを実データで確認済み）、恒久ブロック化は優先度が低いと判断。

**重要な区別**: R13の全項目は**発注ロジック・ポジションサイジング・ガードレール判定の
実際の挙動を変える**ものであるため、R0-v2の安全制約（やらないこと節：「R0-v2未完のまま
 stop閾値を本採用変更しない」等）を引き続き遵守する。**すべてpaper A/Bを経由し、
本番反映は別途ユーザー承認を得てから**行う。

### R13-A: trailing_stop比率強化（stop_loss閾値深掘り検証）

**Status**: 🔴 **ヒストリカル検証完了（2026-08-23）→ 検証結果は母集団依存で不確実、paper A/BはSTOP HOLD**
**優先度**: P1（検証自体は完了。次アクションは下記参照）

**根拠（実データ、2026-08-23確認）**: attributable限定のexit_reason別実績で、
trailing_stop（n=36）はWR=72.2%、PF=11.85、純利益+$35,687と非常に良好な一方、
stop_loss（n=11）はWR=0%、PF=0.0、純損失-$24,638と全敗。この非対称性は学術的
仮説ではなく自社実トレードデータで実証済みのため、実行コストが低い。

**他のやらないこと節との整合性確認**: 「やらないこと」節には「R0-v2未完のまま
stop閾値を本採用変更しない」とあるが、R0-v2はVERIFIED_COMPLETE（2026-07-30）済みなので
本項目着手の障害にはならない。ただし「実値パフォーマンスでPF>1、expectancy>0」のpromotion
要件は引き続き有効。

**実施内容（実施済み）**:
1. `scripts/simulate_stop_loss_deepening.py`を新規作成。既存の
   `simulate_daily_path_volatility_stop.py`（2026-08-14、volatility_adjusted_stopの
   検証で使用）と同じ日次パスリプレイ手法（trailing_stop→breakeven_stop→
   stop_loss→time_basedの優先順位を`SimpleExitV2Strategy`自身のメソッドで
   忠実に再現）を流用し、stop_loss閾値を全conviction tier一律-3pp（-5/-7/-9%
   →-8/-10/-12%）深掘りした場合の反実仮想PnLをヒストリカル検証
2. max DD・CVaRも同スクリプトで自動計算

**検証結果（2026-08-23、読み取り専用、本番影響なし）**:

| 対象母集団 | n | 深掘り幅 | Net PnL差 | max DD差 | CVaR差 | 判定 |
|---|---|---|---|---|---|---|
| 全closed 252件 | 252 | -3pp | **-$19,333** | +2.22pp悪化 | -$818悪化 | ❌明確に悪化 |
| 全closed 252件 | 252 | -1pp | -$11,318 | +1.50pp悪化 | -$545悪化 | ❌悪化 |
| attributable限定 | 49 | -3pp | +$7,223 | +0.04pp（軽微） | -$22（誤差範囲） | ✅一見改善 |
| attributable限定 | 49 | -2pp | +（同方向） | 軽微 | 軽微 | ✅一見改善 |

**重大な発見1（母集団依存性）**: 当初の非対称性を発見したattributable限定（49件）では
深掘りがプラスだった一方、全closed 252件（untracked-origin 203件を含む）では
**明確にマイナス**（-1ppですら悪化）であった。つまりこの施策の効果は対象母集団に
強く依存し、普遍的な改善ではない可能性が高い。

**重大な発見2（単一トレード依存性）**: attributable限定での+$7,223の改善はNBIS（
2026-08-05 entry）、1件の+$8,135がほぼ全てであり、**この1件を除くとnet -$912と
逆転する**（attributableの他の全tradeはdiffゼロまたは少額の悪化のみ）。つまり見かけ上
の改善は単一トレードに完全依存しており、統計的な頑健性はない。

**判断（自己検証含む）**: 検証スクリプト実行中に、CVaR判定ロジック自体のバグ
（絶対値$1.0との比較で$22の誤差を「悪化」と誤判定）を自己発見・修正済み（相対%
基準に変更）。修正後も結論は変わらず、**この施策を現時点でpaper A/Bに進める根拠は
不十分**と判断。単一トレード依存で対象母集団を変えると符号が完全に逆転する結果は、
「儀かるシステムにする」という当初の目的に照らして不十分なエビデンス。

**次のアクション（修正）**:
- 現時点でpaper A/Bには**進まない**（以下のいずれかが成立しない限り）
- 代わりにR13-C（R11バックテスト基盤の根本再構築）の一環として、attributable銘柄が
  十分な件数（ロードマップの昇格基準と同じ≥90件目安）に達してから、同じ検証を再実施し、
  単一トレード依存が解消されるかを確認する
- もしくはNBISタイプの事例（高ボラ銘柄での早期損切り→trailingまでの生き延び）を
  パターン別に別途分析し、全銘柄一律の深掘りではなく「高ボラ銘柄のみ深掘り」のような
  銘柄別セグメント化を検討する
- 現行施策（-5/-7/-9%、volatility_adjusted_stop有効）は変更せず維持

**エビデンス保存先**: `docs/r13a_stop_deepening_validation_20260823/`
（full_deepen3pp.txt / full_deepen1pp.txt / attributable_deepen3pp.txt）

**やらないこと**: 検証で確認されたnegative結果を無視してpaper A/Bに進めない。
単一トレード依存の改善を「エッジあり」と訤解しない。

### R13-A2: early weakness cut ヒストリカル検証（2026-09-05）

**Status**: 🔴 **ヒストリカル検証完了（2026-09-05）→ 全closedでは明確に悪化・attributableのみ小幅改善（母集団依存）。paper A/B昇格はユーザー判断待ち**
**優先度**: P1（ユーザー承認済みタスク、2026-09-05実施）

**根拠（実データ、2026-09-05時点）**: ペーパー運用実績（closed 357件）で
stop_loss -$216k（147件）が主力の出血源であり、うち保有5日以上のstopが57件で
-$125.6k。2026-07-16以降のd5+ stopはn=21・-$48.6k・median exit -8.1%
（ギャップ/スリッページで-7%ストップを貫通）。仮説: 「一度も伸びず（最高含み益+2%未満）
かつ既に明確に水面下（-3%以下）」のポジションは trailing_stop 圏まで回復する見込みが
薄く、深いstopを待たず浅い損失で早期カットすれば出血を減らせるのではないか。

**実施内容**: `scripts/simulate_early_weakness_cut.py` を新規作成（読み取り専用、
本番config変更なし）。R13-Aの `simulate_stop_loss_deepening.py` と同一の日次パス
リプレイ手法（`SimpleExitV2Strategy` 自身のメソッドでexit優先順位を再現、価格取得も
同一）。反実仮想ルール「保有K日目以降、最高含み益+2%未満 かつ 現在リターン-3%以下なら
終値でexit（ハードストップより先に判定）」をK∈{3,4,5}×3コホートで検証。

**検証結果（2026-09-05）**:

| コホート | K | n | Net PnL差 | PF 前→後 | カット件数 | 機会損失（件/逸失額） | max DD差 |
|---|---|---|---|---|---|---|---|
| 全closed | 3 | 295 | **-$84,565** | 0.633→0.460 | 122 | 25件/$146,436 | +3.87pp悪化 |
| 全closed | 4 | 295 | **-$65,731** | 0.633→0.487 | 88 | 19件/$122,331 | +2.27pp悪化 |
| 全closed | 5 | 295 | **-$34,159** | 0.633→0.545 | 67 | 11件/$74,492 | +0.51pp悪化 |
| exit≥07-16 | 3 | 86 | +$244 | 0.681→0.622 | 38 | 8件/$24,916 | -0.50pp改善 |
| exit≥07-16 | 4 | 86 | -$1,662 | 0.681→0.609 | 32 | 5件/$22,451 | -0.42pp改善 |
| exit≥07-16 | 5 | 86 | **-$10,046** | 0.681→0.557 | 27 | 4件/$22,803 | +0.45pp悪化 |
| attributable | 3 | 43 | +$1,283 | 1.031→1.072 | 14 | 4件/$3,711 | +0.20pp悪化 |
| attributable | 4 | 43 | **+$1,849** | 1.031→1.091 | 10 | 1件/$1,273 | -0.08pp改善 |
| attributable | 5 | 43 | +$919 | 1.031→1.060 | 8 | 1件/$1,273 | -0.02pp改善 |

**主な発見**:
1. **機会損失が支配的（全closed）**: 「弱いスタート→後に大化け」のトレード
   （AMD 05-12 逸失$25,370、PANW $14,080、FTNT $8,995、PLTR $7,619、HPE $7,344等）を
   構造的に誤爆し、早期カットの節約分を圧倒。K=3で25件$146kの逸失。
2. **母集団依存（R13-Aと同一パターン）**: attributable限定（n=43）では全Kで小幅プラス
   （最良K=4 +$1,849、PF 1.031→1.091、機会損失1件のみ）だが、全closed（n=295）では
   全Kで明確にマイナス。改善原資はAMZN/QTUM等の少数stop回避に依存し、小標本。
3. Kを深くすると機会損失は減るが便益も減り、全closedでは依然マイナス。

**判定**: ヒストリカル検証としては昇格を後押しする頑健なエビデンスなし。
**paper A/B昇格はユーザー判断待ち**（本検証は判断材料の提供のみ。実装・config変更なし）。

**エビデンス保存先**: `docs/r13_early_weakness_cut_validation_20260905/`
（summary.md / full_run_k345.txt / per_trade_results.json / stderr_warnings.txt）

**制約**: 日次終値のみのリプレイ（exit_reason一致率: 全closed 62%・07-16以降 84%・
attributable 91%。旧broker_reconstructed起源トレードは忠実度が低い）。
ATR%エントリー時点固定・universe平均±3日近似（R13-A/volatility検証と同一の制約）。

### R13-B: signal_strengthとexit/sizingの接続見直し

**Status**: 🟡 **ヒストリカル検証完了（Option Bのみ、exit側）、2026-08-23→ 弱い・不確実な結果、次アクション待ち**
**優先度**: P1

**根拠（実データ、2026-08-23確認）**: `reports/signal_strength_decile.json`の
decile別expectancyは完全に非単調（decile 3が+$78で最良、decile 9が-$1,503で最悪、
高scoreほど良いという単純な相関はない）。attributable限定で90件confidence tierでも
同様の非単調性を確認（mid tier n=10 expectancy=-$179が最悪、high tier n=11は
+$155だが勝率36.4%のみ、low tier n=23が+$103で最良）。それにもかかわらず現行
`position_sizing.py`は`confidence`（signal_strength経由）が高いほどstop幅を広げ、
trailing発動を早める設計。根拠のないシグナルでリスクを歪めている可能性が高い。

なお`position_sizing.py`の`confidence_multiplier`はhigh-confidence側（1.2倍）が
既存capでclipされno-op化していることが戦略レビュー（上記第2弾）で判明済み。

**実施内容（2案、どちらかをpaper A/Bで選択）**:
- **(A) 較正案**: 既存`annotate_cross_sectional_percentile()`（2026-08-17実装済みだが
  sizing/exitに未接続）を利用し、単一銘柄の絶対スコアではなく同日候補群内の相対順位
  でsizingを決める設計に変更（sizing変更のため、既存の固定qty履歴に対しては直接
  バックテスト不可。未検証のまま）
- **(B) 切り離し案**: signal_strengthをsizing/exitから完全に切り離し、固定ルールに戻す
  （exit側のみ2026-08-23にヒストリカル検証済み、下記参照）
- confidence_multiplier no-opバグ（high-confidence 1.2倍がcapで打ち消される）の修正は
  **未実施**（sizing側の別途検証を待つ）

**ヒストリカル検証実施（Option B、exit側のみ、2026-08-23）**: `scripts/simulate_signal_
strength_exit_decoupling.py`を新規作成。R13-Aと同じ日次パスリプレイ手法で、
現行のtiered exit閾値（-5/-7/-9%にconviction tier連動） vs 全件uniformの
標準閾値（-7%）を比較。**注意: この検証はexit閾値側のみ。sizing側（(A)案・
confidence_multiplierバグ修正）は既存固定qty履歴では直接バックテスト不可なため
未検証のまま**。

**検証結果（読み取り専用、本番影響なし）**:

| 対象母集団 | n | Net PnL差 | 改善/悪化件数 | max DD差 | 判定 |
|---|---|---|---|---|---|
| 全signal_strength記録済み110件 | 100 | **-$1,804** | 9件改善/7件悪化 | +0.26pp悪化 | ❌弱い悪化 |
| attributable限定 | 41 | +$1,457 | 2件改善/0件悪化 | -0.09pp改善 | ⚠️弱い改善 |

**重要な限界**: 全体・attributableともに**変化したトレード数が極めて少ない**（110件中
9件改善/7件悪化、attributable 41件中わずか2件のみ変化）。全体での悪化は
主にPLTR、1件（-$7,990、現行tieringではtrailing_stopまで生き延びたがuniformでは
stop_lossで早期退場）に依存。R13-AのNBIS 1件依存ほど極端ではないが、
同様に「少数トレードで結果が左右される」頔弱性を持つ。

**判断（自己検証含む）**: スクリプト自体の機械的判定ロジックはattributable限定で
✅を返すが、n=41中2件のみ変化した結果を「支持する証拠」として扱うのは統計的に
不適切。R13-Aほど極端な逆転ではないが、両検証とも「後押しできるほどの十分な検体な
し」という共通の結論に到達。**現時点でOption B（exit側の切り離し）をpaper A/Bに
進める根拠は不十分**と判断。

**次のアクション**:
- exit側Option BはR13-A同様、R13-Cでattributable銘柄数が十分に増えてから再検証
- sizing側（Option A・confidence_multiplierバグ修正）: **2026-08-26に着手・検証完了**
  （ユーザー承認、xhigh reasoning）。実データでバグを完全実証（confidence_multiplier
  記録済み85件のうちcm=1.2ブースト55件は0%発火、cm=0.7カット7件は86%発火 —
  `cap`が`base_final_shares`と同一4値minで再計算されているため`cap==base`が
  常に成立し高確信ブーストを無効化する非対称バグ）。修正案（confidence_multiplierを
  shares_by_riskへ事前適用）をヒストリカルにテスト：メカニズム検証（n=58、qty効果のみ）
  ではブーストが妥当な39件中25件で正しく発火（残14件はnotional/exposure/sector側が
  先にボトルネックのため無変化=正常挙動）、カット側4件全件で既存挙動を保持（regression
  なし）。トレード結果連動検証はn=2のみ（decision_id永続化とconfidence_multiplier
  記録がいずれも08-14開始のため構造的にサンプル僅少）で統計的に無意味、判断不可。
  **本番コード未変更**（`scripts/simulate_confidence_multiplier_sizing_fix.py`による
  読み取り専用分析のみ）。詳細: `docs/r13b_sizing_confidence_multiplier_fix_
  validation_20260826/README.md`
- 現行施策（tiered exit、confidence_multiplier no-opバグを含む）は変更せず維持
  （メカニズムは実証済みだがpaper A/B判断の材料としてはattributable標本が
  R13-A/B基準の≥90件目安に達するまで不十分、R13-Cの進展待ち）

**エビデンス保存先**: `docs/r13b_signal_strength_decoupling_validation_20260823/`
（full_110trades.txt / attributable_49trades.txt）

**推奨比較方法**: control=現行score-linked exit/sizing、variant=uniform、
評価指標はnet PnLだけでなくmax DD、CVaR、stop後5/10/20日regret、turnover、gap loss

#### R13-B1: ss縮小サイジング反実仮想（2026-09-05）

**Status**: ✅ 検証完了（読み取り専用）。**paper A/B昇格はユーザー判断待ち**（実装・config変更なし）

高スコア帯に損失が集中する非単調性（上記R13-B根拠）を受け、「entry_signal_strength
∈ B のエントリーをサイズ f 倍に縮小していたら」を反実仮想で測定
（`scripts/analyze_ss_sizing_counterfactual.py` 新規、PnL×f の一次近似）。
B∈{[0.85,1.00), [0.88,1.00), [0.90,1.00)} × f∈{0.5, 0.0}、**ss==1.00ちょうどは
フルサイズ維持**。対象: entry_signal_strength付きclosed 132件。

結果要約（全期間 n=132、baseline net -$83,465 / PF 0.461）:

| バンド | f | 影響件数 | Net PnL差 | PF 前→後 |
|---|---|---|---|---|
| [0.85,1.00) | 0.5 | 14 | **+$9,484** | 0.461→0.482 |
| [0.85,1.00) | 0.0 | 14 | **+$18,968** | 0.461→0.507 |
| [0.88,1.00) | 0.5/0.0 | 8 | +$2,261 / +$4,523 | 0.461→0.460 / 0.458（悪化） |
| [0.90,1.00) | 0.5/0.0 | 4 | +$893 / +$1,786 | 0.461→0.456 / 0.451（悪化） |

直近コホート（exit>=07-16、n=90）でも同傾向（[0.85,1.00) f=0で PF 0.562→0.643）。

- **[0.85,1.00)のみ実質改善**。ドライバーはFTXL/CHPX（08-24半導体セルオフ
  stop_loss、計-$13.0k）・LRCX・NOW・METAの負け縮小で、**セクター集中問題と交絡**
  （同日実施の`docs/r13_sector_cap_validation_20260905/`と併読）。
- 狭いバンドはHPQ +$4,199（trailing win）の機会損失が拮抗しPF悪化。バンドを
  狭めるほど効果が消える＝0.85付近の少数トレード依存。
- ⚠️ **前提数値の食い違い**: 直前セッション引用の「ちょうど1.00は+$23k」は現データ
  で再現しない（ss==1.00は n=46 / **-$38.8k** と最大の出血源）。「高スコア帯が
  最悪・非単調」の定性は維持。9/8判断時に必ず考慮。
- 限界: PnL線形一次近似（資金再配分・複利・guardrail相互作用は無視）、影響
  n=14以下でR13-A/B基準（attributable 30〜90件以上）に未達。

エビデンス: `docs/r13b_ss_sizing_validation_20260905/`（summary.md + full_run.txt +
per_trade_results.json）

### R13-C: R11バックテスト基盤の根本再構築（look-ahead/survivorship bias解消）

**Status**: ✅ **全項目（1・2・3・4・5・6・7）実装・検証完了（2026-08-24）。強い肯定的知見が保守的補正後も維持**
**優先度**: P2（工数大、本番影響なしの研究基盤作業）

**根拠（戦略レビュー、C02/C03で実コード確認済み）**: 旧`scripts/r11_backtest_engine.py`は
(1) 当日closeをmomentumシグナルの入力とentry価格の両方に使うsame-bar look-aheadバイアス
と、(2) 現在の69銘柄symbol_registry.yamlを過去全期間に適用するsurvivorship biasを抜けていない。
実際に3分割検証でvalidation PF=0.560とtrain（PF=1.78）から大幅に利益が落ちることを確認済み。

**実施内容（IMPLEMENTATION_VALUE.mdの「R11-v2の最低要件候補」を優先度順に選択）**:
1. ✅ signal at t close → fill at t+1 open（最優先、look-ahead解消の本質）— 実装完了
2. ✅ point-in-time universe対応（survivorship bias解消）— 実装完了（下記限界あり）
3. ✅ 保守的OHLC pathでstop/trailingを再生成 — 実装完了（2026-08-23、下記参照）
4. ✅ cash、gross exposure、sector/cluster capの再現 — 実装完了（2026-08-24、下記参照）
5. ✅ spread/slippage/impactの反映 — 実装完了（2026-08-23、下記参照）
6. ✅ rolling walk-forward + embargo — 実装完了（2026-08-24、下記参照）
7. ✅ 全trial registry（パラメータ探索の過適合リスクを評価可能にする）— 実装完了（2026-08-24、下記参照）

**実装（2026-08-23）**: `scripts/r11_backtest_engine_v2.py`新規作成。旧`r11_backtest_
engine.py`のコアロジック（実本番クラスへの委譲、フローズンクロック手法）は継承し、
(1) シグナルはt日closeで計算しentryはt+1日openで約定（pending_entriesキュー）
(2) `scripts/r11_symbol_universe_intro_dates.py`（新規）でpaper_demo.pyのDEFAULT_
SYMBOLS履歴とsymbol_registry.yaml履歴から各銘柄の「実際にシステムにuniverse登録された
日付」をgit履歴から逆算し、その日付以前は当該銘柄のエントリーシグナルを完全に禁止する
というgateを実装。

**重要な限界（自己開示、スクリプトdocstringにも明記）**: 銘柄intro日付はあくまで
「このシステムがcで銘柄を追跡し始めた日」の代理指標であり、「2024年時点の公平な第三者が
選ぶはずの銘柄集合」ではない。銘柄選定自体のバイアス（NVDA/AMDを後から選んだのは
まさに後の好パフォーマンスを知っていたから、という可能性）は修正できない。修正できるのは
「システムの設定が存在しない時期にその銘柄を売買していた」というより機械的なバイアスのみ。

**検証結果（全69銘柄、2024-08-15〜2026-08-14の2年分、実価格）**:

| バージョン | n | WR | PF | Net PnL |
|---|---|---|---|---|
| v1（旧、look-ahead+survivorship入り） | 1,415 | 59.4% | 1.733 | +$312,697 |
| v2 t+1 fillのみ（universe gate無効） | 1,338 | 58.1% | 1.703 | +$292,374 |
| v2 両方修正（t+1 fill + point-in-time universe） | 374 | 58.3% | 2.069 | +$130,438 |

**重要な発見（分解分析）**: t+1 fill修正のみではn/PFの変化は小さい（1415→1338、
PF 1.73→1.70）。**変化の大部分はpoint-in-time universe gateによるもの**で、v1の
1,415件中1,029件（73%）が「実際の銘柄導入日以前」に発生していた（例: NBISはintro=
2026-04-23だが、v1では2024年から取引されて+$17,498を計上）。この1,029件の合計PnLは
+$203,166（ネットではプラス）だが、それを除去してもPFは1.73→2.07へ向上（除去された
集団のWR/PF構成が全体より低かったため）。

**本番実績との外部検証（重要）**: 修正後バックテスト（両方修正）の月次PF推移と、
実際の本番取引（pnl_state.json、2026-05〜08）の月次PF推移を比較：

| 月 | 本番実績 n | 本番実績 PF | 修正版backtest n | 修正版backtest PF |
|---|---|---|---|---|
| 2026-05 | 80 | 4.53 | 98 | 6.19 |
| 2026-06 | 82 | 0.55 | 118 | 0.39 |
| 2026-07 | 41 | 0.28 | 56 | 0.89 |
| 2026-08 | 49 | 1.08 | 40 | 2.81 |

**方向性が一致**（5月好調→6月急落→7月不調→8月回復）しており、修正後のバックテストエンジンが
モデリングアーティファクトではなく、breakout_momentumシグナルの実際のレジーム依存性をある程度
忠実に再現できているという強い外部検証シグナル。

**本番 go-live以降（2026-05-12、実際のDecisionRecordの最早日）のみでPF再計算**:
n=284、WR=50.4%、**PF=1.448**、net=+$49,271。ブートストラップ90%CI=**[1.099,
1.891]**（完全に1.0を上回る）。現在の本番attributable PF=1.082（90%CI
0.564–2.125、中心が1.0をまたぐ）よりも強い。

**このPF=1.448を過大評価しないための重要な前提（未実装の3〜7項目に直結）**:
- exit側はv1同様同日closeを使っており、項目3（保守的OHLC path）の未対応分の
look-aheadが残存
- spread/slippage/impact未反映（項目5）→ 実際の約定価格はもっと不利なはず
- cash/gross exposure/sector cap未反映（項目4）→ 本番はentry filterやセクター集中度上限で
ブロックされるトレードがあり、単純なシグナルバックテストとは一致しない
- パラメータはsimple_exit_v2.yamlの現在値を全期間に適用（実際は段階的に導入された設定）

**判断**: 「修正後バックテストが本番と方向性一致する」はエンジンの信頼性を裏付ける強いシグナルだが、
「PF=1.448は本番で再現できる」とは主張しない（上記前提のため楽観側に偏っている可能性高い）。
breakout_momentumエントリーシグナル自体にはバイアス除去後も一定のエッジが存在する可能性が高い
というデータだが、項目3〜7（特に保守的exit pathとslippage）を実装して再検証するまでは本番パラメータ
変更の根拠にしない。

**エビデンス保存先（v2）**: `docs/r13c_backtest_v2_validation_20260823/`
（v1_vs_v2_full_comparison.txt / t1fill_only_no_universe_gate.txt /
production_vs_backtest_monthly_comparison.md / v2_both_fixes_trades.json /
v2_t1fill_only_no_universe_gate_results.json）。テスト: `tests/unit/
test_r11_backtest_engine_v2.py`（t+1 fillとuniverse gateのメカニズムを合成データで
弄しテスト、5件）。

---

**実装v3（2026-08-23、同日内に継続実施）**: `scripts/r11_backtest_engine_v3.py`新規作成。
v2のt+1 fill + point-in-time universeに加え、項目3・5を実装:

- **項目3（保守的OHLC exit）**: peak_priceを日次closeではなく日次HIGHで更新し、
stop_loss/trailing_stop/breakevenの下限判定を日次LOWでチェック。ブレークした場合は閾値価格で
約定（LOWそのものではなく、ストップ注文がトリガー価格で約定されると仮定）。日次OHLCしか
キャッシュしていない制約上、完全な場内執行タイミング再現ではないが、意図的に保守的（より多く、
より早く退場する方向に偏った）に設計
- **項目5（slippage）**: 本番の実際の発注は全てmarket order（`ProposedOrder.order_type
== "market"`）であることを確認した上で、entry/exit両方にone-way slippage_bpsを不利な方向に
適用（買いは高く、売りは安く）。既存の2026-08-15 R11分析の往復手数料bp規約と一致させ、
往復20bp = 片道のみ10bpとしてデフォルト設定

CLIに`--isolate`（両修正を個別に分解）、`--compare-v2`（v2との側面比較）オプションあり。

**検証結果（全69銘柄、2年分、片道slippage=10bp）**:

| バージョン | n(全体) | PF(全体) | n(live以降) | PF(live以降) | net(live以降) |
|---|---|---|---|---|---|
| v2（t+1 fill+universe gateのみ） | 374 | 2.069 | 284 | 1.448 | +$49,271 |
| v3（+ 保守的OHLC exit + slippage 10bp） | 621 | 1.854 | 471 | 1.453 | +$45,725 |

**分解分析（項目ごとの単独効果）**:

| variant | n(全体) | PF(全体) | n(live) | PF(live) | net(live) |
|---|---|---|---|---|---|
| v2（基準） | 374 | 2.069 | 284 | 1.448 | +$49,271 |
| slippageのみ（保守的exitなし） | 353 | 2.183 | 264 | 1.448 | +$41,328 |
| 保守的exitのみ（slippageなし） | 633 | 1.966 | 481 | 1.550 | +$53,969 |
| v3（両方） | 621 | 1.854 | 471 | 1.453 | +$45,725 |

保守的exit単独では取引数が増える（日次LOWで早期退場するケースが増えるため）が、PFはほとんど
悪化しない（早期退場が損失拡大を防ぐ方向に作用するケースが多いということ）。slippage単独は
予想通りPFを下げるが、live以降PFは1.448でv2とほぼ一致。

**Slippage感度分析（保守的exitは常にTrue）**:

| 往復bp | 片道bp | n(全体) | PF(全体) | n(live) | PF(live) | net(live) |
|---|---|---|---|---|---|---|
| 0 | 0.0 | 633 | 1.966 | 481 | 1.550 | +$53,969 |
| 10 | 5.0 | 633 | 1.925 | 481 | 1.516 | +$50,827 |
| 20 | 10.0 | 621 | 1.854 | 471 | 1.453 | +$45,725 |
| 30 | 15.0 | 619 | 1.822 | 469 | 1.426 | +$43,111 |

往復30bp（既存分析で使っていた最も保守的なシナリオ）でもlive以降PF=1.426で大きく崩れない。

**ブートストラップ（live以降、2000リサンプル）**: n=471、PF=1.453、90%CI=**[1.210,
1.750]**、**リサンプルの100%がPF>1**（v2の90%CI[1.099, 1.891]よりも下限が上がり、幅が狭まった）。

| エンジン | n | PF | 90%CI |
|---|---|---|---|
| 本番（attributable） | 49 | 1.082 | [0.564, 2.125] |
| v2（t+1 fill+universe gateのみ） | 284 | 1.448 | [1.099, 1.891] |
| v3（+保守的exit+slippage） | 471 | 1.453 | **[1.210, 1.750]** |

**本番との外部検証（v3でも継続）**:

| 月 | 本番実績 PF | v3（保守的+slippage）PF |
|---|---|---|
| 2026-05 | 4.53 | 3.39 |
| 2026-06 | 0.55 | 0.93 |
| 2026-07 | 0.28 | 0.88 |
| 2026-08 | 1.08 | 1.87 |

方向性一致はv3でも維持。

**重要な評価**: 当初の想定（項目3・5を入れればPF=1.448はかなり削られるはず）に反し、
**実際にはPF=1.453でほぼ不変だった**。これは（a）breakout_momentumシグナル自体のエッジが
モデリングアーティファクト（楽観的なクローズ仲値やフリクションレス約定）に依存していなかったことを
示す強いシグナルだが、（b）残る項目4（exposure/sector cap）・6（walk-forward+embargo）・
7（trial registry）は依然未実装であり、特に項目4はentry filter層との統合が必要で
本番の実際のBUY拒否パターンと一致しない可能性がある。

**エビデンス保存先（v3）**: `docs/r13c_backtest_v3_validation_20260823/`
（v3_full_isolation_comparison.txt / slippage_sensitivity.md / bootstrap_ci.md /
production_vs_v3_monthly_comparison.md / v3_full_trades.json）。テスト: `tests/unit/
test_r11_backtest_engine_v3.py`（保守的OHLC exitのLOWトリガーとclose-onlyモードとの
挙動分け、slippageのentry/exit両方への不利方向適用、trailing_stop優先順保持を合成データで
検証、5件）。フルスイート2083 passed/2 skipped（regressionなし）。

**次のアクション（当初記載）**: 項目4（exposure/sector cap）はentry filter層との統合が必要で
工数が大きいため後回し → **2026-08-24実装完了、下記参照**。R13-Bの冒頭で記録した通り、
attributable銘柄数が増えたらR13-A/Bの再検証も検討。

**やらないこと**: 本研究の結果を直接本番に反映しない（必ずR11-D型のpaper A/Bを経由）。

---

**実装 項目4・6・7（2026-08-24、R13-C残項目を完了）**: `scripts/r11_backtest_engine_v4.py`
（項目4）、`src/stock_swing/research/rolling_walk_forward.py`（項目6）、
`src/stock_swing/research/trial_registry.py`（項目7）を新規実装。item 6・7は
`src/stock_swing/research/`配下の汎用モジュールとして実装し、今後の他バックテスト
スクリプトからも再利用可能。統合実証として`scripts/r13c_rolling_walk_forward_
validation.py`（新規）でv3エンジンの実トレードに対しrolling walk-forwardを適用し、
結果をtrial registryに記録する一連の流れを実証。

**項目4（exposure/sector/cluster cap）検証結果**: v3をそのまま再利用し、
position_sizing.pyの実`SYMBOL_SECTORS`とcorrelation_cluster.pyの実`CLUSTERS`/
`DEFAULT_CLUSTER_CAPS`をそのままimportしてentry側にgross/sector/cluster capを追加。
本番デフォルト値（gross=75%, sector=55%）ではこの69銘柄・$10,000/trade固定サイズの
設定では全期間通じて一度もbindしない（capacity_dropped=0、n/PF/net全てv3と完全一致）。
意図的にタイトな設定（gross=30%, sector=20%）で動作実証: n=621→468（25%減）、
PF=1.854→1.665、net=$101,272→$63,271と機会損失を定量的に確認。

**項目6（rolling walk-forward + embargo）検証結果**: 4 rollsで実行（embargo_days=20、
SimpleExitV2Strategyのmax_hold_daysと一致）。point-in-time universe無効時（全2年
ヒストリー参考ビュー）: **Roll 1のtest期間（2025-11-26〜2026-03-17）でPF=0.815と
唯一1を割り込み**、これは2026-08-15のR11-B付鍘レビューで単一60/20/20分割から
発見された「validation期間の不振」（2025-10-27〜2026-03-20）と ほぼ重なる。
**全く異なる手法（複数rolling window、embargo付き）で再実行しても同じレジーム依存の
弱点が再現**され、単一分割点のノイズではなく頑健な弱点であることの独立した裏付けとなった。
それ以外の3/4 rollsはtest PF>1（1.142/2.857/1.679）。

**項目7（trial registry）実証**: 上記rolling walk-forward実行を`--record-trials`付きで
実施し、`data/research/trial_registry.jsonl`に8件（4 roll × train/test）を記録。
`count_trials(roadmap_item=...)`で多重比較の開示（何通りのパラメータ/rollを試したか）が
可能になった。

**テスト**: 新規42件（trial_registry 18件、rolling_walk_forward 17件、
r11_backtest_engine_v4 7件）。フルスイート**2168 passed/2 skipped**（regressionなし、
baseline 2126 + 42 = 2168で一致確認）。

**エビデンス保存先**: `docs/r13c_item4_6_7_20260824/`（README.md +
v4_default_caps_vs_v3.txt / v4_tight_caps_vs_v3.txt /
rolling_walk_forward_full_universe.txt / rolling_walk_forward_point_in_time.txt /
test_output.txt）。

**限界（自己開示）**: 項目4は固定notional/trade設計のため部分サイズ約定は未実装
（drop=完全見送りは実際より保守的）。ETF/Stock 85/15配分バンド（PortfolioAllocator）は
対象外。項目6のpoint-in-time universe有効時は全銘柄のintro_dateが2026年（システムの
銘柄追跡開始日プロキシ）のため、trainウィンドウが2026年より前のrollはn=0になる制約が
ある（`--no-point-in-time-universe`で全2年ヒストリーの補完ビューを提供）。

**R13-C総括**: 項目1〜7すべて完了。R13-C全体をCOMPLETEとする。

**次のアクション**: rolling walk-forwardで再確認された「2025-11〜2026-03のレジーム
依存不振」を09-10 Pre-Launch Gate Reviewの「レジーム依存性確認項目」（2026-08-15
追加済み）にこの独立検証結果として追記する価値がある。paper A/Bへの反映は引き続き
見送り（R13全体の「やらないこと」方針を継承）。

### R13-D: 独立収益源の開発（ETFセクターローテーション・JP overnight spillover等）

**Status**: 🟡 ETFセクターローテーション Phase 1はmin_members修正完了（2026-08-26）、
headline設定はMIXEDに低下したが他パラメータ（top_n=1等）でGO継続、新headline選定が次アクション
+ Phase 2（戦略設計コード実装）完了（2026-08-23、本番未配線）
**優先度**: P3（今すぐ収益には直結しないが、momentum一本足打法からの脱却に必要）

**⚠️ 2026-08-26追加検証・修正実施済み（min_members未実装の影響）**: 同日のロードマップ
監査で発見した「`run_rotation()`の`min_members`パラメータ未使用」を実際に測定した
ところ、**headline設定（top_n=2）でmin_membersを正しく適用するとSharpeが1.370→1.230に
低下しequal-weight baseline(1.255)を下回り「MIXED」判定に転落**することを発見。
初回リバランス（2024-11〜2025-03）が`technology_cloud`（SKYY 1銘柄のみ）・
`quantum_computing`（QTUM 1銘柄のみ）を連続選択していたことが原因（docstring自身が懸念
していた「単一ETFノイズ依存」が実際に発生）。

**修正実施済み（`scripts/r13d_etf_sector_rotation_phase1.py`に`min_members`を正式実装，
`--enforce-min-members`フラグで新旧両結果を比較可能にし、デフォルトは旧挙動保持（後方
互換性確認済み））を実施し公式再判定**したところ、**問題はheadline設定（top_n=2,
lookback=63d, hold=21d）固有の脆弱性であり、戦略アイデア自体の妥当性は引き続き支持
される**と判明。min_members適用後のパラメータ感度チェック（top_n=1: Sharpe=1.473でGO継続、
lookback=126d: 1.415でGO、hold=42d: 1.318でGO）では依然として多くの設定がGOを維持。
**NO-GO/MIXEDになるのはheadline設定1点のみ**。教訓: 単一のhealine設定のみに依存した
GO判定は、実装バグ、1つで容易に覇るリスクがある。テストスイート影響なし（関連テスト46件
全件PASS確認済み、本番未配線のresearch scriptのみ変更）。

**次のアクション**: headline設定を`top_n=1`または`lookback=126d`に変更し、
min_members修正込みの数値を新headlineとして採用することを推奨。選択根拠の明文化が必要
（後付けの良い数値選びにならないよう注意）。09-08のR13-D本番配線判断レビューでは
`--enforce-min-members`付き結果を正式な判断材料とすること。詳細:
`docs/r13d_min_members_check_20260826/README.md`

**既存進捗**:
- JP半導体overnight spillover: Phase 1（相関検証、GO判定済み）、Phase 2（戦略設計）、
  Phase 2.5（shadow検証、日次収集中）完了済み。IBKR接続確立後にPhase 3（実配線）へ
- ETFセクターローテーション: **Phase 1完了（本日、下記参照）**

**ETFセクターローテーション Phase 1（2026-08-23実施）**: JP overnight spilloverと同じ
Phase 1パターン（相関/フィージビリティ検証のみ、本番影響ゼロ、承認不要）を踏襲。
`scripts/r13d_etf_sector_rotation_phase1.py`新規作成。

**手法**: symbol_registry.yamlがsector付きでタグ付けする20 ETF（semiconductor n=8 /
software n=7 / robotics_ai n=2 / technology・technology_cloud・quantum_computing・
broad_market各n=1）を均等加重してセクター日次リターンを合成。トレーリング63営業日
（約3ヶ月）リターン上位N（デフォルト2）セクターを21営業日（約1ヶ月）ごとにローテーション
保有する単純な相対モメンタム戦略を、R13-Cと同じ実価格データ（2024-08-15〜2026-08-14、
2年分）でテスト。比較対象: 全セクターETF均等加重buy&hold、SPY buy&hold。

**検証結果**:

| 戦略 | 累積リターン | CAGR | Sharpe | maxDD |
|---|---|---|---|---|
| セクターローテーション（top2/63d/21d） | +100.32% | 49.28% | **1.370** | 29.43% |
| 全セクターETF均等加重buy&hold | +67.23% | 34.52% | 1.255 | 26.38% |
| SPY buy&hold | +30.00% | 16.33% | 0.967 | 19.00% |

ローテーションが両ベースラインをSharpeで上回る。

**頑健性チェック（自己検証、詳細は`docs/r13d_etf_sector_rotation_phase1_20260823/
robustness_checks.md`）**:
- 実行ラグ感度（signal→fill遅延0/1/2日）: Sharpe 1.370/1.372/1.424とほぼ不変
  （月次リバランスのため数日の遅延は無視できるほど小さい、R13-Cの日次シグナルとは対照的）
- Walk-forward分割: period1（24-11〜25-09）Sharpe=1.069、period2（25-10〜26-08）
  Sharpe=1.622。両期間ともSPYベースラインは上回るが、均等加重ベースラインは
  period2でのみ上回る（period1単独ではやや劣後、要注意点）
- 単一ETFのみのセクター（QTUM/QQQ/SKYY/SPY）を除外し、真の複数銘柄セクターのみ
  （robotics_ai/semiconductor/software）でtop_n=1を再テスト: Sharpe=1.473で
  依然両ベースライン上回る（単一ボラティリティETFのノイズ依存ではないことを確認）
- パラメータ感度（グリッドサーチではなくラウンドナンバーの代替4パターン）:
  全て両ベースラインのSharpeを上回る

**限界（自己開示、スクリプトdocstringにも明記）**:
- 均等加重セクター「指数」は簡略化（時価総額加重ではない）
- Phase 1段階のため取引コスト・slippage未反映（生シグナルのフィージビリティ検証、
  取引可能戦略のバックテストではない — JP spillover Phase 1・R11 v1初回と同じ位置づけ）
- 単一の歴史的レジーム（2024-08〜2026-08の強気相場+2回の調整）のみ、レジーム頑健性は未検証
- 現在のETF構成を過去全期間に retroactively 適用（R13-Cのpoint-in-time universe議論と
  同種の限界。ただしETFのユニバース選定は個別株ほど後知恵バイアスを受けにくい）

**判定**: ✅ GO — Phase 2（戦略設計）に進む価値あり。R13-Cで確立したt+1約定・コスト考慮
手法を流用して設計する。

**エビデンス保存先**: `docs/r13d_etf_sector_rotation_phase1_20260823/`
（phase1_output.txt / robustness_checks.md / r13d_etf_sector_rotation_phase1_results.json）。
テスト: `tests/unit/test_r13d_etf_sector_rotation_phase1.py`（trailing_return計算・
top_n選定・リバランス間隔・累積曲線・Sharpe・max_drawdownの各ロジックを合成データで
検証、10件）。フルスイート2093 passed/2 skipped（regressionなし）。

**実施内容（今後）**:
1. Phase 2（戦略設計）: R13-Cのt+1 fill・conservative exit・slippageモデリングを流用し、
   月次リバランスをtradeableな戦略として設計（既存momentum戦略とは別ID・別台帳）
2. JP overnight spilloverはIBKR接続確立後にshadow→paper A/Bの次ステップへ
3. 各戦略は別ID・別台帳・別リスク予算で管理（既存方針と一致）

**ETFセクターローテーション Phase 2（戦略設計、2026-08-23実施）**: Phase 1で検証した
ロジックを、本コードベースの既存アーキテクチャパターン（`BaseFeature`/`FeatureResult`,
`BaseStrategy`/`CandidateSignal`）に沿って実装。JP overnight spilloverの
`UsOvernightBenchmarkFeature`と同じ「新規独立モジュール、本番未配線」方針を踏襲。

**新規実装**:
- `src/stock_swing/feature_engine/sector_momentum_feature.py`
  （`SectorMomentumFeature`）: symbol_registry.yamlの`sector`タグからセクター別
  トレーリングリターンを計算するグローバルfeature（`MacroRegimeFeature`と同型）
- `src/stock_swing/strategy_engine/sector_rotation_strategy.py`
  （`SectorRotationStrategy`、`strategy_id="sector_rotation_v1"`）: 上位N セクターの
  構成ETFに買いシグナルを生成する新規独立戦略。既存momentum戦略とは別strategy_idで
  PF/WR属性分析を汚染しない設計（JP spilloverのPhase 2設計セクション1-Aと同じ判断）

**重要な限界（設計時点で未実装、Phase 3の課題として明記）**: このクラス自体は
**ステートレス**（呼び出すたびに「現在の」上位Nセクターのシグナルを出すだけで、
前回いつリバランスしたかの記憶を持たない）。Phase 1のバックテストでは
`hold_days`ごとにのみ保有を再評価していたが、これをpaper_demo.pyの日次/複数回cronに
配線するには、`PaperExecutor`のポジション管理と同様の永続的な「前回リバランス日＋
現保有」状態管理が別途必要。この状態機械の構築はPhase 3（本設計・バックテスト検証の後）
に明示的に先送り。

**Feature/Strategyの整合性検証（2026-08-23）**: `scripts/r13d_sector_rotation_feature_
strategy_validation.py`（新規）で、Phase 1のプレーン関数版ロジックと、新規実装した
本番パターンのfeature/strategyクラスが同じ結果を出すかを21回のリバランス日全てで
突き合わせ検証。**初回実行で3〜5件の不一致を検出**（自己発見・自己修正、詳細下記）。
修正後、**全21チェックポイントで完全一致**を確認。

**発見・修正した2つのオフバイワン問題（自己検証で発見）**:
1. `SectorMomentumFeature`はリターンを終値から内部計算するため、`lookback_days`日分の
   リターンウィンドウには`lookback_days + 1`日分の終値が必要（初日のリターン計算に前日終値が
   要る）。この呼び出し規約を`SectorMomentumFeature.compute()`のdocstringに明記
2. Phase 1の`trailing_return()`はリバランス評価日**当日**のリターンを含まない排他的
   スライスを使用しており、検証スクリプト側の終値ウィンドウ切り出しをこれに合わせる必要が
   あった（本番`SectorMomentumFeature`自体のバグではなく、検証スクリプトの整合ミス）

**判定**: ✅ Phase 2設計・実装は整合性確認済み。Phase 3（実配線、リバランス状態管理の
実装、コスト・スリッページ込みの再検証）へ進む前提が整った。

**テスト**: `tests/unit/test_sector_momentum_feature.py`（10件、うちオフバイワンの
リグレッションガード1件）、`tests/unit/test_sector_rotation_strategy.py`（9件）。
フルスイート2112 passed/2 skipped（regressionなし）。

**エビデンス保存先**: `docs/r13d_phase2_design_20260823/`
（consistency_check_output.txt）

**やらないこと**: 既存momentum戦略と同一台帳で混合して集計しない。Phase 1の生シグナル
結果を直接paper/liveに反映しない（必ずPhase 2設計→shadow→paper A/Bを経由）。

---

**Phase 3（リバランス状態管理実装、2026-08-24実施）**: `src/stock_swing/
strategy_engine/sector_rotation_state.py`新規作成。Phase 2が明示的に先送りにしていた
「永続的な「前回リバランス日+現保有」状態管理」を実装。`CircuitBreakerStore`/
`day_start_snapshot.py`と同じatomic write+os.replaceパターンを踏襲。
`RebalanceState`（last_rebalance_date/current_sectors/current_holdings/
rebalance_count）+ `is_rebalance_due()` / `compute_rebalance_diff()` /
`advance_rebalance_state()`の純粋関数群で構成。

**検証（`scripts/r13d_phase3_state_machine_validation.py`、実データ2年分）**:
Phase 2の自己検証は21営業日おきのチェックポイントでのみ呼んでおり、「毎日呼ばれたら
どうなるか」（実際のcronケーデンス）は未検証だった。436営業日全てを日次呼び出しで
シミュレートし、**stability violation（非リバランス日に保有が変化）0件**を確認
（Phase 2が明示していた「テートレスなら毎回ポジション入れ替えてしまう」問題を回避できていることを
実証）。リバランス回数（31件）もhold_days=21スペーシングの素朴な期待値（約20.8件）と
概ね一致。

**重要な発見（自己開示）**: 実際のリバランス回数（31件）は素朴な期待値（約20.8件）より
約49%多い。原因は`is_rebalance_due()`が**暦日**ベースでゲートしており、Phase 1の
バックテストが使っていた**営業日**ベースの21日カウントとは異なるため（週末・休日を挿むと
暦日カウントの方が早く閾値に達する）。失敗方向は「リバランスがやや多めになる」という
保守的側（リバランス漏れではない）であり、モジュールdocstringに限界として明記済み。

**テスト**: `tests/unit/test_sector_rotation_state.py`（22件）。

**判定**: ✅ 状態管理の実装・検証完了。**本番配線（cron/paper_demo.py接続）は
未実施**（Phase 2から引き継いだスコープ境界を維持、実配線は別途ユーザー承認と昇格プロセスを
経由）。

**エビデンス保存先**: `docs/r13d_phase3_20260824/`
（README.md + phase3_state_machine_validation_output.txt + test_output.txt）

**残る次のアクション（未着手）**: (1) 本番配線（ユーザー承認待ち）
(2) 暦日→営業日カウントの精密化（優先度低） (3) コスト・スリッパージ込みの再検証（R13-Cで確立した
t+1約定・conservative exit・slippageモデリングをsector rotationにも適用）

**Phase 2.5相当（Shadow検証、2026-08-25/26実施、ユーザー「Shadow相当ないしは適当な現状戦略の
レビュー後に配線スケジューリングして」指示）**:

**背景**: ユーザーから本番配線の「メリット・デメリット」を問われ、以下を回答:
- メリット: 検証完了済み・分散効果（今回の半導体集中インシデントの対極的設計）・
  Sharpe1.370の頑健性チェック複数通過
- デメリット: コスト/slippage未反映・暦日カウントで想定より約49%多いリバランス・
  資金プール共有未解決（Circuit Breaker/cluster cap/PortfolioAllocatorが戦略非依存）・
  **実発注ありのpaper A/Bを意味する**（dip-buyのようなshadow-onlyの中間ステップが
  Phase 2/3のコードには存在しなかった）
- ユーザーはこれを受け、dip-buy（R14）と同じ「shadow相当の検証を経てから配線判断」の
  順番を明示的に指示

**実装**: `scripts/log_sector_rotation_shadow.py`新規（JP overnight spilloverの
`log_jp_overnight_spillover_shadow.py`と同型のスタンドアロンcronスクリプト、yfinance
経由でブローカー接続不要）。**Phase 2/3で実装済みの本番クラス（`SectorMomentumFeature`/
`SectorRotationStrategy`/`SectorRotationStateStore`）をそのまま呼び出し、初めてend-to-end
動作確認**（実データで動作確認済み: technology_cloud/broad_marketが上位、SKYY/SPYが候補）。
発注なし・ブローカー接続不要・**本番state file（`data/sector_rotation_state.json`）には
一切触れない設計**（別ファイル`data/sector_rotation_shadow_state.json`を使用、
`--state-path`に本番ファイル名を渡すと明示的にエラーで拒否するガード付き）。

テスト5件追加（`tests/unit/test_log_sector_rotation_shadow.py`、本番state file誤指定
ガードのsubprocessテスト含む）。

**cron登録**:
- `stock_swing_sector_rotation_shadow`（平日9:30 JST、日次shadow蓄積、delivery=none）
- `stock_swing_sector_rotation_wiring_decision_review_20260908`（09-08、R14 dip-buyの
  09-08レビューと同日。2週間分のshadow蓄積を見て本番配線を進めるか判断。**配線の最終判断
  自体はユーザー承認必須のため、このcronは提言までで自動進行しない**）

**未実施（09-08レビュー待ち）**: 本番配線（発注ありpaper A/B開始）の可否判断そのもの。

### セクター集中上限 反実仮想検証（2026-09-05）

**Status**: ✅ 検証完了（読み取り専用、`scripts/analyze_sector_cap_counterfactual.py` 新規）。
本番のcap/config変更なし。**09-08 R13-D配線判断の材料**

直近コホートの出血が8/14以降の新規半導体エントリーに集中している診断を受け、
「エントリー実行後の同一セクター保有notional/equity が cap ∈ {30%,40%,50%} を
超えるならエントリー自体をブロック」を逐次シミュレーション+PnL一次近似で検証。
セクター分類は symbol_registry.yaml の `sector`（G6 canonical、全58取引銘柄
カバー、`semis`→`semiconductor` 正規化）+ 補助として `is_semiconductor_related`
フラグ連結ビュー（ETF+個別株を跨ぐクラスタ露出）。

結果要約（registry sector版、全期間 n=357 / baseline PF 0.888）:

| cap | ブロック | Net PnL差 | PF後 | 直近（exit>=07-16、PF 0.634）|
|---|---|---|---|---|
| 30% | 62件（勝ち30 +$39.3k / 負け32 -$70.6k）| **+$31,526** | 0.975 | 3件ブロック **+$12,934**、PF→0.733 |
| 40% | 35件（勝ち20 +$26.7k / 負け15 -$22.1k）| **-$4,636** | 0.865 | 0件 |
| 50% | 8件 | +$11,228 | 0.917 | 0件 |

- cap 30%が直近コホートでブロックするのは **FTXL/CHPX（08-17エントリー→08-24
  半導体セルオフ stop_loss、計-$12.8k）** で既知の出血診断と正確に一致。
- **capはNet PnLに対して非単調**（40%では勝ちを負けより多く消して悪化）＝
  「上限＝常に改善」ではない。ブロックは勝ちも消す（cap 30%でも機会損失+$39.3k）。
- 半導体集中の実測ピークは equity比 **78.2%**（06-04）で現行sizing側cap 55%を
  超過歴あり。現在のopenポジションは半導体関連 equity比3.7%でどのcapにも非抵触。
- **R5-v2 cluster capとの接続**: 本番実装済みの `_filter_buys_by_cluster_cap()`
  （6クラスタBUYブロック、top5_concentration 40%）の閾値妥当性検証（R5-v2残項目）
  に本結果を直接使える。09-08のR13-D ETFセクターローテ配線判断でも判断材料に
  含めること（配線は半導体ETF比重を増やし得るため）。
- 限界: 一次近似（資金再配分・複利無視）、直近の改善実体はFTXL/CHPX 2件依存。

エビデンス: `docs/r13_sector_cap_validation_20260905/`（summary.md + full_run.txt +
cap_results.json）

### R13全体のやらないこと

```
❌ R13-A/Bをpaper A/BでのDD/CVaR悪化確認なしに本番反映しない
❌ R13-Aの2026-08-23検証で確認された「全銘柄では悪化」「単一トレード依存」の制限を
   解消せずにpaper A/Bに進めない（STOP HOLD中）
❌ R13-Cのバックテスト結果をpaper A/Bなしで直接本番に反映しない
❌ 低勝率銘柄の恒久ブロックリスト化（先の候補3番）は今回のスコープ外（既存rolling PF gateで
   代替可と判断）
❌ R0-v2の安全制約（manual clear後のverification run必須等）をR13の作業で回避しない
```

### R13優先順位・工数目安

| 優先度 | Phase | 内容 | 工数目安 | リスク | 進捗 |
|---|---|---|---|---|---|
| P1 | R13-A | stop_loss閾値深掘り検証 | 中 | 低 | **STOP HOLD**（検証完了、2026-08-23） |
| P1 | R13-B | signal_strength exit切り離し検証 | 低〜中 | 中 | **弱い結果**（検証完了、2026-08-23）、sizing側（confidence_multiplierバグ）実証済み、2026-08-26）、paper A/Bには未十分 |
| P2 | R13-C | R11バックテスト再構築（項目1〜7全完了） | 大 | 低（研究のみ、本番影響なし） | **✅ COMPLETE**（2026-08-24）、live以降PF=1.453（90%CI[1.210,1.750]）、rolling walk-forwardでレジーム依存不振を独立再確認 |
| ⚠️ P3 | R13-D | ETFセクターローテーション、JP spilloverはIBKR待ち継続 | 大 | 低（shadowのみ） | Phase 1/2/3実装完了（2026-08-24）だが**headline設定はmin_membersバグ修正でMIXEDに低下**（2026-08-26）、top_n=1等別パラメータはGO継続、新headline選定が09-08レビュー前の次アクション、本番配線は未着手（要承認） |

**09-15 Go/No-Goとの関係**: R13はすべてpaper A/B・研究段階であり、09-15までに
本番反映されるものは別途ユーザー承認がない限りない見込み。つまり09-15判断の前提となる
現在のPF/expectancy水準はR13着手だけでは即座には向上しないことを明示的に認識する。

## R14: Dip-buy / Mean-reversion戦略（2026-08-25、ユーザー発案）

**背景**: 08-24の半導体セルオフでcircuit breakerがdegraded/block_buysに突入したことを
受け、ユーザーから「Circuit BreakerはBuyのみ止めているのか、下げ相場は買い時では」との
質問。コード確認により`pre_trade_check.py`の実装で「Circuit BreakerはBuyのみブロックし
Sellには一切影響しない」ことを確認。続けて「下げたら買う」逆張り戦略のfeasibilityと
既存`breakout_momentum_v1`との同時実行可否について「進めて」との指示を受けた。

**Phase 1（フィージビリティ検証、2026-08-25完了）**:
R13-Dと同じPhase 1パターン（研究のみ、本番影響ゼロ）で実施。新規
`scripts/r14_dip_buy_meanreversion_phase1.py`（既存`r11_backtest_engine_v3`の
conservative-OHLC-exit/t+1-fill/slippage機構と本番`SimpleExitV2Strategy`設定を
そのまま再利用、エントリールールのみ`BreakoutMomentumStrategy`の鏡像＝トレーリング
20日モメンタム≤-5%かつtrend=="bearish"で買い、を新規実装）。

結果（2年分、2024-08-15〜2026-08-14、69銘柄、既存momentumと同一コストモデル）:
- Point-in-time universe: dip-buy PF=1.963(n=359) vs momentum PF=1.854(n=621)
- Universe制限なし（全期間）: dip-buy PF=1.710(n=1938) vs momentum PF=1.575(n=1997)
- **チョップ相場（2025-11〜2026-03、R13-Cが独立にmomentumの弱点と特定済みの期間）**:
  dip-buy PF=1.170（+$14,339） vs momentum PF=0.646（-$23,094）— momentumが
  独立して弱点と確認した局面でdip-buyは黒字、これが最重要の発見
- overlap（同一銘柄をmomentumも同時保有し得たケース）: 18.5%（全期間版）。
  エントリー条件がtrend bullish/bearishで相互排他のため構造的に同時発火は
  起きにくいが、時間差での交差は一定数あり

判定: ✅ **GO** — Phase 2へ。詳細: `docs/r14_dip_buy_meanreversion_phase1_20260825/README.md`

**⚠️ 2026-08-26追記（R11-Cと同型の自己検証、重要・混在結果）**: 同日のR11-C検証で
発見した「1銘柄1ポジション排他制御が戦略効果と混同する」アンチパターンをR14にも適用して
検証（`scripts/r14_no_symbol_exclusivity_check.py`、本番のRiskValidator/
BreakoutMomentumStrategy/paper_demo.pyに同目的の排他制御が存在しないことを
確認済み）。結果は混在: (a) **全期間比較は逆転**（PIT: dip-buy 1.963→1.530 vs
momentum 1.854→2.063、full-history: 1.710→1.456 vs 1.575→1.787、dip-buy取引件数
は3〜4倍に急增）でGO判定の一部は未支持。(b) しかし**最重要の発見「チョップ相場での
momentum弱点補完」は同条件でも頑健に残存**（dip-buy PF=1.1811の黒字 vs momentum
PF=0.6414の赤字、Phase1自体の0.646とほぼ一致）。修正された価値提案: dip-buyを
「常時稼働でmomentumを上回る独立戦略」ではなく「レジーム検知連動型（chop検知時のみ
有効化）」として設計し直すべき。09-08本番配線判断レビューではこの修正前提を反映する
こと。詳細: `docs/r14_no_symbol_exclusivity_check_20260826/README.md`

**Phase 2（SHADOW-ONLY本番配線、2026-08-25実施、ユーザー「進めて」指示）**:
- `src/stock_swing/strategy_engine/dip_buy_meanreversion_strategy.py`新規
  （`DipBuyMeanReversionStrategy` + `DipBuySignalConfig` + `log_shadow()`。
  strategy_id=`dip_buy_meanreversion_v1_shadow`とサフィックスして誤って本番
  昇格しても即座に判別可能にする命名規約）
- `paper_demo.py`に配線（`daily_features`生成直後、Plan B/C/D/Eと同じ
  best-effort try/except パターン）。**signalsは`entry_signals`/
  `all_signals`に一切追加されず、DecisionEngine/EntryFilterEngine/
  broker発注経路に到達しない**。`data/dip_buy_meanreversion_shadow_log.jsonl`
  へのログのみ
- `--dry-run`時はログ書き込みしない（既存Plan B-Eと同じdry-run汚染防止パターン）
- テスト32件追加（`tests/unit/test_dip_buy_meanreversion_strategy.py` 18件 +
  `test_paper_demo_mutation_regression.py`にwiring regression 2件、
  「shadow-onlyで実際の注文に一切影響しない」ことをcron-summary
  `decisions_buy=0`/`orders_submitted=0`で直接検証）
- フルテストスイート: **2230 passed / 2 skipped**（baseline 2210+20で一致、regressionなし）

**Gate 3（rolling PF gate）干渉分析（2026-08-25、コード変更なし）**: 新規
`scripts/r14_gate3_cross_strategy_interference_check.py`で、`entry_filter.py`の
実`compute_rolling_pf()`関数をそのまま再利用し、Phase 1の両バックテスト結果に対して
point-in-time（lookaheadなし）で「もし共有EntryFilterEngineで両戦略が動いたら」を
定量検証。結果は**強い非対称性**を確認:

| 方向 | 検証対象 | ブロックされる件数 | うちwinだったもの | 機会損失 |
|---|---|---|---|---|
| A: momentumの履歴がdip-buyをブロック | 359件 | **29件(8.1%)** | **21件(72.4%)** | **+$5,844（機会損失）** |
| B: dip-buyの履歴がmomentumをブロック | 621件 | 2件(0.3%) | 1件(50%) | -$15（無視できる規模） |

方向Aが実質的な問題: PTF/TSLA/NOW/FICOなど、momentumが同一銘柄でチョップ相場中に
連敗した結果rolling PFが悪化し、方向性が真逆のdip-buyエントリー（72%がwinだったはず）
まで巻き込んでブロックしてしまう。「この銘柄はmomentumにとって今調子が悪い」を
「この銘柄自体が悪い」と誤って一般化してしまう、銘柄単位ゲートの典型的な失敗モード。
方向Bはほぼ無視できる規模のため、**全面的な再設計ではなく的を絞った対応
（dip-buyをmomentumのrolling PF計算対象から除外する、または逆）で十分な可能性が高い**。

**未実装のまま残る項目（本番配線＝実発注前の必須設計課題）**:
1. ✅ 分析完了（上記）。**結論: Gate 3は現状のまま昇格させると実害あり**。
   strategy-scoping（またはdip-buyのみ除外する的を絞った対応）が本番配線の前提条件
2. Circuit Breaker/correlation cluster cap/PortfolioAllocatorは全て
   ポートフォリオ横断・strategy非依存の共有プール。実配線には資本配分の分離設計
   （IBKR移行・JP半導体拡張と同じenvironment_idスタイルの分離）が必要
3. shadowログ蓄積後のレビュー（初回1〜2週間後の件数チェック、3〜4週間後の
   promotion判断）— Plan B/Cと同じレビューケイデンスを踏襲予定、レビュースケジュール
   （cron登録済み、09-08 `stock_swing_r14_dip_buy_shadow_review_20260908`）

**やらないこと（現時点で明示的にスコープ外）**:
```
❌ dip-buyシグナルをDecisionEngine/EntryFilterEngine/発注経路に接続する
   （shadow log蓄積のみ、Phase 3として上記1〜2の設計完了後に検討）
❌ パラメータのグリッドサーチ（drop深さ・lookback窓の最適化）—
   意図的に鏡像の単一ルールのみ検証、R13-Cのoverfitting回避方針を踏襲
```

---

## R16: 複数ロット希釈exitシャドー診断（lot_level_exit_diagnostic、2026-09-01）

**背景**: ユーザーから「長期間含み益が出ているのに売られていないポジションが
あるが、ロジック通りか」との定常確認を受け実データ検証した結果、NOW銘柄で
構造的な問題を発見。旧ロット（08-12エントリー、15株@$125.00、単独peak_return
=+18.75%）が同日08-31にguardrail degraded下で追加された新ロット（385株@
$148.84）と加重平均され、合成peak_returnが+0.6%まで希釈された。
`SimpleExitV2Strategy.generate()`はsymbol単位で集約評価するため、旧ロット単体
なら発火するはずのtrailing stop保護が完全に不可視化される構造的ギャップ。

**実装（ユーザー「今すぐ着手して」指示、同日実装完了）**:
- 新規 `src/stock_swing/risk/lot_level_exit_diagnostic.py`:
  `SimpleExitV2Strategy`の`_resolve_thresholds()` / `_resolve_trailing_rule()` /
  `_resolve_breakeven_floor()` / `_effective_min_hold_days()`を**そのまま再利用**
  してロット単位で独立にexit判定を再評価し、symbol単位の集約判定（実際に
  generate()が出したsell signal）と比較。不一致（discrepancy）のみログ。
  一致するケースはログしない（ノイズ回避）。
- `SimpleExitV2Strategy`に`build_atr_pct_map()` / `compute_universe_avg_atr_pct()`
  を純粋リファクタリングとして追加（generate()内部の既存インライン計算を
  static methodとして切り出し、動作変更なし）。診断側がgenerate()と同じ
  volatility-adjusted stop基準を再計算ドリフトなしで再利用するため。
- `paper_demo.py`へ配線: `exit_strat.generate()`呼び出し直後、`news_shock_hold`と
  同じtry/except非致命化パターン。**shadow-only、observability-only**——
  一切のexit判定・発注ロジックに影響しない（他の全shadow診断と同じ設計思想）。
- config: `LOT_LEVEL_EXIT_DIAGNOSTIC_DISABLED`（デフォルト有効）、
  `LOT_LEVEL_EXIT_DIAGNOSTIC_MIN_LOTS`（デフォルト2）
- ログ: `data/lot_level_exit_shadow_log.jsonl`

**検証**:
- 新規テスト25件（`test_lot_level_exit_diagnostic.py` 16件 +
  `test_simple_exit_v2_volatility_adjusted_stop.py`への追加9件）。
  NOWインシデントの実データ形状再現テスト含む
- フルテストスイート: **2264 passed, 2 skipped**（実装前2239件、regressionなし）
- 実データ検証（現在のopen_position_details使用）: 現在価格（peak同値）では
  discrepancy 0件（正しい動作）。price=144.0（peakから-3.0%押し目を
  シミュレート）で**NOWの旧ロットのみtrailing_stop would_exit=True、新ロット
  はFalse**を正しく検知することを確認

**現状の判断**: shadow-onlyのため本番売買判断には無影響。今夜以降のpaper_demo
run（cronスケジュール変更なし）から`data/lot_level_exit_shadow_log.jsonl`への
蓄積が自動開始。ロット単位判定への昇格（symbol単位判定の置き換え）は
position tracking/FIFO決済ロジック/exit strategyを跨ぐ統合設計に該当し、
MEMORY.md標準手順上xhigh reasoning必須のため、今回はshadow実装までに留めた。

**次のマイルストーン**: **2026-09-08**（cron登録済み、`cron list`で実在確認済み:
`stock_swing_lot_level_exit_diagnostic_review_20260908`）に、shadow log蓄積
件数・discrepancy内訳・実損益への影響を評価する初回レビューを実施。

**やらないこと（現時点で明示的にスコープ外）**:
```
❌ ロット単位のexit判定を本番のgenerate()に組み込む（shadow検証のみ、
   promotion判断は09-08レビュー以降）
❌ FIFO決済順序の変更（別課題。ロット単位exitが本番化されない限り、
   「判定基準と実際に売られるロットの不一致」問題も未解決のまま残る——
   09-08レビューで合わせて評価対象とする）
❌ MSFT/ORCLの「peak_return +5%未満デッドゾーン」問題への対応（同日発見
   したが実害限定的と判断し今回は記録のみ、次回roadmapレビューで再検討）
```

詳細: `docs/daily_logs/2026-09-01.md`

### ⚠️ 2026-09-02 追記: 警告対象の構造問題が実害化 → per-lot time_based exitをdefault-offで実装

shadow診断稼働初日（2026-09-01T19:55Z market_close run）に、警告対象の構造問題が
そのまま実損として顕在化した。max_hold判定（最古ロットの時計）による全量売却で:

- **NOW**: 新ロット385株（保有**1日**、degraded下の08-31 BUY）が旧ロット15株（20日）の
  時計に巻き込まれ **-$2,333** で強制決済
- **ORCL**: 340株（15日）が13株（20日）に巻き込まれ **-$2,768**
- PLTR: 同構造だが巻き込まれ側が黒字（+$1,334）で実害なし

shadow logは3件全てを`aggregate_exit_lot_disagreement`として正しく記録（診断自体の
有効性も同時に実証）。ユーザー指示により同日対応:

- 新規 `src/stock_swing/risk/per_lot_time_based_exit.py`（time_based分岐限定の
  per-lot部分売却計画。FIFO決済との組み合わせで期限到達ロット群だけが正確に閉じる）
- `per_lot_time_based_exit_enabled: false`（**default OFF、R13-Bと同じ本番挙動
  完全保持パターン**。有効化は09-08レビュー承認後）
- テスト+26件（インシデント実データ形状再現含む）、フラグON時の動作をインシデント
  当日データで検証（NOW 15/400・ORCL 13/353・PLTR 11/292の部分売却になっていた）

なお同runのPATH +$6,296（trailing_stop）等の勝ちでguardrailは`degraded`→`ok`に
自動復帰済み。詳細: `docs/daily_logs/2026-09-02.md`

---

## R17: reduce_size設計見直し検証（見送り、、2026-09-01）

**背景**: R16の対応中、ユーザーから「degraded状態で現金が長期間遷ぶのは機会損失では？」
との問いを受け、既存調査（08-15/08-26）で判明済みの「reduce_sizeは露光上限を
丸ごと半減させる二値的ブロック機構」を前提に4つの設計代替案（案A：最低確保枠フロア、
案B：new注文サイズのみ半減、案C：連敗数に応じた段階的縮小、案D：時間ベース回復）を提案し、
案Bと案C+Aの検証をユーザー承認で実施。

**検証（3段階）**:
1. **Part 1**（全期間検証）: 新規 `scripts/r0v2_reduce_size_design_alternatives_20260901.py`。
   08-26検証基盤（本番同一クラス`PositionSizingPolicy`、R11-Bユニバース）69銘柄）で
   baseline/現行/案B/案C+A(v1)を検証。案Bが全指標で現行を上回る（PF 1.497→1.5093）
2. **Part 2**（チューニング）: 新規 `scripts/r0v2_reduce_size_design_alternatives_v2_20260901.py`。
   C+Aのtier閘値/乗数/floor幅を振っ5バリエーション + B+Cブレンド2種を追加検証。
   `plan_c_plus_a_v2_strict_mild`（mild tierを現行と同な0.5xに戻し、moderate/severeを
   さらに厳格化）が全期間合算で最良（PF 1.5372, net_pnl $508,292）
3. **Part 3**（過学習検証）: 新規 `scripts/r0v2_reduce_size_segment_robustness_20260901.py`。
   ユーザーが「狭い探索は過学習ではないか」と指摘したことを受け、既存の
   `scripts/r11b_param_search.py`と同一のtrain(60%)/validation(20%)/holdout(20%)
   日付分割で各メカニズムを再集計。
   **重要な発見**: validation期間（既知の市場調整局面）だけを見ると、**現行メカニズム
   が全候補中で最も高いPF（0.6455）**で、全期間合算で「圧勝」に見えたv2もvalidationでは
   現行を下回る（0.6406 < 0.6455）。頃健性判定（validation・holdout両方で現行以上を要求）
   で全候補が「ROBUST」をクリアできず。

**最終結論（ユーザー判断、2026-09-01）**: **見送り**。reduce_sizeメカニズム自体は変更せず現行
維持。「防御的な仕組みはまさに防御が必要な局面でこそコストに見合う」という、当初の仮説
（「reduce_sizeは強すぎるのでは」）とは逆方向の構造的洞察が得られた。余剰資金の活用は
**reduce_sizeの再設計ではなく、別の新規戦略（既存ポジションと独立した資本配分先）を検討する
方向で対応**する。

**本番コードへの影響**: なし。全て`scripts/`配下の検証スクリプト3本とドキュメントのみ。

詳細: `docs/r0v2_reduce_size_design_alternatives_20260901/README.md`

### news_shock_hold 初回中間レビュー（2026-09-04、shadow継続判断）

2026-08-21実装（commit `4f1ca25`、shadow-only）のnews_shock_hold.pyについて、
予定どおり初回中間レビューを実施（automation:
`stock_swing_news_shock_hold_review_20260904`）。分析・記録のみで実装変更なし。

**蓄積状況**（`data/news_shock_hold_shadow_log.jsonl`、08-21〜09-03の約9営業日）:
- 総306行 / ユニーク14銘柄 / 4チェック/日
- reason内訳: insufficient_signal 257（84%）、not_flagged 25、no_data 13、
  **news_shock（true）11**
- net_scoreが算出できた行は48行（16%）のみ。**実質的なカバレッジは
  ニュース量の多い大型株（MU/ORCL/MSFT/TSLA等）に限定**され、小型株・ETF
  （CHPX/FTXL等）は常時no_data/insufficient_signal。カバレッジ限界として記録。

**true判定イベント（重複排除後5イベント / 4銘柄）とその後の実値動き**
（R9レビューと同方法論: true判定直後のunrealized_plpc推移と実trade結果で検証）:

| イベント | 発火時plpc | その後 | early warning評価 |
|---|---|---|---|
| MU 08-24（4行連続） | -9.3%→-11.7% | 09-03時点-6.9%まで**回復**（未決済） | ❌ 偽警報（発火が底値圏、既に織り込み済み） |
| ORCL 08-27（2行） | +1.4% | 09-01 time_based決済時-5.5%（実損-141/-2,768） | ✅ 有効（発火後約-6.9pp。発火時決済なら合算-$2,909の損失を小幅黒字に転換できた） |
| MSFT 08-28（1行） | +4.3% | 09-02 time_based決済時+0.8%（+$575） | ✅ 中程度有効（発火後約-3.5pp） |
| MSFT 09-02（1行） | +1.1% | 20分後にtime_based決済（同上trade） | ➖ 中立（既定exit直前で増分価値なし、方向は整合） |
| TSLA 09-02（3行） | +3.7%→+1.8% | 16:15 trailing_stop決済（+$1,001） | ✅ 弱い有効（発火後約-1.9pp、初回発火時決済なら約+2pp改善） |

集計: **明確に有効3 / 中立1 / 偽警報1**。仮に全イベントで発火時即決済した場合の
pp改善は ORCL+6.9 / MSFT+3.5 / TSLA+1.9 / MU-2.4〜-4.8 で**ネット正**だが、
評価可能イベントはわずか4-5件。

**unrealized_plpcとの相関**:
- true行の平均plpc -2.4% vs false行 -0.6%（ただしtrue側はMUの4行に引きずられた値）
- true 11行中7行は**含み益状態で発火**。イベント単位では5件中4件が含み益〜
  ほぼフラットで発火 → **「既に含み損が大きい銘柄で発火しやすいだけ」ではない**。
  含み益銘柄の新規ネガティブニュースを価格反映前に検知するという設計意図どおりの
  挙動を確認（Plan Dの「織り込み済み」構造懸念への応答として良好）
- 唯一の深い含み損での発火（MU -9〜-12%）が唯一の偽警報だった点は示唆的:
  「plpcが既に大きくマイナスの場合は悪材料が織り込み済みでshockの増分価値が低い」
  可能性。将来の閾値設計の候補メモとしてのみ記録（現時点で変更なし）

**判断: shadow継続（昇格判断は見送り）**。5イベント/9営業日はpaper_ab昇格可否を
論じるには明確にサンプル不足。方向性は良好（有効3:偽警報1、含み益銘柄でも発火）
だが、偶然の域を出ない。

**次のマイルストーン**: 累計true判定イベントが15件に達するか、4週間経過
（**2026-10-02目安**）のいずれか早い方で第2回レビューを実施し、有効/偽警報比と
発火時plpc分布を再評価。その時点でサンプルが揃えばpaper_ab昇格提案を検討
（提案のみ、実行はユーザー承認後）。

## P0: Go/No-Go 経済性ゲート追加（economic_viability、2026-09-05、ユーザー承認済み）

**背景**: 従来のRequired条件（鮮度・ledger・circuit breaker・mismatch・attribution・
guardrail・cron・paper 3日確認）はすべて「システムが壊れていないか」の検査であり、
「そのシステムが経済的に儲かっているか」を問う条件が1つも存在しなかった。ペーパー
運用実績（pnl_state.json、5/12〜09-05、closed 357件）は実現PnL -$38,253 / PF 0.888 /
勝率47.3%であり、この状態でRequired全緑=GOと報告するのは「壊れていないが儲からない
システム」へのGOである。

**実装（2026-09-05）**: `scripts/check_go_no_go.py` に必須チェック
**economic_viability** を追加。

- コホート: `data/tracking/pnl_state.json` の closed トレードで
  **exit_time >= 2026-08-14**（CLIフラグ `--econ-cohort-start` で上書き可能）
- 算出: n / PF（粗利益/|粗損失|）/ expectancy（1トレード平均PnL）
- 合格条件: **n>=30 かつ PF>1.0 かつ expectancy>0**
- **n<30 は insufficient_sample として fail-closed（NO-GO）**
- レポート統合: Required条件テーブルに1行追加 + 「経済性ゲート詳細」セクション
  （「補足: R5-v2 Promotion Gate」と同形式のテーブル）を追加。Required判定に
  含まれるため、この条件が❌の間は他が全緑でも最終判定はNO-GO・exit code 1。

**初回実行結果（2026-09-05 04:18 JST、--save → `docs/go_no_go_result_20260905.md`）**:

| 項目 | 値 |
|---|---|
| 最終判定 | 🔴 NO-GO（economic_viabilityのみ❌、他Required 9条件は✅） |
| n | 45（>=30 で十分） |
| PF | **0.530**（必要: >1.0）— 粗利益 +$28,001 / 粗損失 -$52,811 |
| expectancy | **-$551.33**（必要: >0） |

**意図の明文化（重要）**: 現状PF 0.888（全期間）/ 0.530（直近コホート）のため、
このゲートは**意図的にNO-GOを出す**。これはユーザー承認済み（2026-09-05）の
fail-closed設計であり、**GOを出すために閾値を緩めることは許可されていない**。
GOに戻る唯一の道は、戦略側の改善（R13群等）によって直近コホートの実測PF/expectancyが
実際に合格域へ回復することである。

**テスト**: `tests/unit/test_check_go_no_go_economic.py` 新規（15件: 合格/PF<1/
insufficient_sample fail-closed/コホート境界/open・pnl欠損除外/PF=inf/check()統合/
--econ-cohort-startパース/レポート出力/exit code）。既存 all-green fixture
（`test_check_go_no_go.py`）に経済ゲート合格分のtrades追加。go_no_go関連+promotion_gate
の計65テスト全緑を確認。

---

## 日本市場拡張ロードマップ(総合版)策定(2026-09-05、ユーザー指示)

`docs/jp_market_expansion_roadmap.md` を新設。IBKR移行後の日本市場拡張を3トラックで優先順位付け:

1. 🥇 **JPセクターETFローテーション**(R13-D日本版) — 実装再利用度最大・購入禁止リスト制約を構造回避・JPY建て分散
2. 🥈 **US→JPオーバーナイト・スピルオーバーの一般化** — 半導体特化版(Phase 2.5 shadow稼働中)の実配線優先度は集中リスクにより「低」へ変更。金融/エネルギー/ディフェンス等の非半導体ペアへ一般化(Go基準: 相関0.4以上 or 方向一致60%以上)
3. 🥉 **JP決算PEADスイング** — event_swing_v1骨格・R10決算カレンダー流用。データ整備が律速で3番手

大原則: 「勝てていない戦略を新市場に輸出しない」(経済性ゲートNO-GO中は米国側改善が優先)/ 全トラック同一規律(Phase1検証→shadow→paper A/B→経済性ゲート→ユーザー承認)/ 半導体連結エクスポージャ30%予算にJP半導体分も合算。Track 1/2のPhase 1着手は9/8レビュー・9/14 Go/No-Go後にユーザー承認を得てから。

---

## R18: エントリー環境ゲートとリスク定額化（2026-09-05、ギャップ分析より）

**背景**: paper実績（closed 357件、実現-$38,253、PF 0.888、直近コホートexit>=08-14
n=45/PF 0.530）のギャップ分析で、実地確認済みの構造的不足が3点判明:
(1) エントリーのレジームフィルタなし（market_regimeはレポート表示のみで常時unknown）
(2) 決算ブラックアウトなし（entry_filters.yamlは出来高/ADR/銘柄PFゲートのみ。
event_swing_v1は逆に決算前に買う設計のため適用スコープ分離が必要）
(3) ATR定額リスクサイジングなし。stop_loss合計-$216k/147件、うちexit return<=-9%の
ギャップ貫通が29件/-$111k（スクリプトによる直接カウント。起票時概算「約20件」を更新）。
月次PnLは5月-22k/6月+87k/7月-86k/8月-22kとムラが大きい。

**規律（全項目共通）**: shadow/検証 → paper A/B → ユーザー承認。経済性ゲート
（PF>1.0/expectancy>0、fail-closed）NO-GO中の実弾昇格はなし。同一357件への
反実仮想の重ね掛けによる多重検定リスクがあるため、昇格判断はR13-C完了後の
out-of-sample再確認（R18-D）を必須とする。

### R18-A: 市場レジームフィルタ（2026-09-05検証済み → ❌ 否定的、クローズ）

`scripts/analyze_regime_filter_counterfactual.py`（look-ahead回避: エントリー日の
前営業日closeで判定）。エビデンス: `docs/r18a_regime_filter_validation_20260905/`。

全期間コホート（n=357、Net -$38,253、PF 0.888）:

| バリアント | ブロック | 勝ち/負け | Net PnL差 | PF 前→後 |
|---|---:|---:|---:|---:|
| (a) SPY < 50日SMA | 9 | 7 / 2 | **-$1,316** | 0.888 → 0.883 |
| (b) SPY < 200日SMA | 0 | — | ±$0 | 変化なし |
| (c) VIX > 20 | 0 | — | ±$0 | 変化なし |
| (d) VIX > 25 | 0 | — | ±$0 | 変化なし |
| (e) SPY<50SMA または VIX>25 | 9 | 7 / 2 | **-$1,316** | 0.888 → 0.883 |

直近コホート（exit>=07-16、n=97、PF 0.634）: (a)(e)でブロック4件・+$293のみ、他は0件。

**結論**: 2026-04以降リスクオフ該当日が少なく（VIX>20は8日でほぼ4月=運用開始前、
VIX最大25.78）、**7月の出血-$85.6kはリスクオン相場の中で発生**（ブロック9件の
7月exit分PnLはむしろ+$1,316の勝ち越し）。指数レジームでは説明・回避不能で、
セクター集中（cap30%: +$31.5k）の方が有望。paper A/B昇格は提案しない。
深いベア相場（VIX>25持続等）での保険価値のみ未検証として保留（棄却ではなく判定保留）。

### R18-B: 決算ブラックアウト（2026-09-05検証済み → △ 中規模プラスだが単独昇格なし）

`scripts/analyze_earnings_blackout_counterfactual.py`。決算日は
`data/r11_earnings_cache/`（R11-C、yfinance由来）を採用（finnhubカレンダーは
2026-08-07以降のみで過去カバレッジ不足）。**カバレッジ100%**（個別株264/264、
ETF93件は決算なしで対象外）。event_swing系closedトレードは0件（除外ロジックは実装済み）。
エビデンス: `docs/r18b_earnings_blackout_validation_20260905/`。

ルール: エントリー日から次回決算までNカレンダー日以内ならブロック。

| N | 全期間: ブロック(勝/負) | 全期間PnL差 | 全期間PF | 直近(exit>=07-16)PnL差 | 直近PF |
|---|---:|---:|---:|---:|---:|
| 3日 | 9 (5/4) | +$3,587 | 0.888→0.892 | -$1,121 | 0.634→0.622 |
| 5日 | 10 (6/4) | +$3,368 | 0.888→0.892 | -$1,121 | 0.634→0.622 |
| 7日 | 20 (10/10) | **+$9,125** | 0.888→**0.907** | **+$4,324** | 0.634→**0.660** |

**決算×ギャップ貫通の直接カウント**: ギャップ貫通ストップ29件/-$111,018のうち
保有期間内に決算日を含むのは**わずか1件**（AVGO 06-02→06-04、-$8,619/-16.3%）。
→ ギャップ貫通の主因は決算ではない（当初仮説は棄却）。N=7の効果も4件の大負けに
依存しサンプル依存性が高い。**単独昇格は提案せず**、R18-C設計時に
「決算前N=5〜7日ブラックアウト」をオプション束として含め、out-of-sample再検証後に
昇格判断。event_swing_v1とはフィルタ適用スコープを分離すること。

### R18-C: ATR定額リスクサイジング（起票のみ、検証は後日）

設計スケッチ: 1トレードのサイズ = リスク予算（例: equityの0.3〜0.5%）÷（ATR×株価
ベースの想定損失幅）。狙いは「被弾額の定額化」= ギャップ貫通29件/-$111kのような
テール損失の1件あたり上限管理（R18-Bの結果、ギャップの主因が決算以外である以上、
イベント回避よりも被弾額管理が構造的に有効）。R13-Bのsizing接続と統合して設計する
（PositionSizingPolicyへの接続点を共有）。検証は反実仮想（実績トレードをATR定額で
サイズし直した場合のPnL再計算）を後日実施。

### R18-D: 多重検定/オーバーフィット管理（起票のみ）

同一closed 357件に対する反実仮想の重ね掛け（セクター上限・ss帯除外・early weakness
cut・R18-A・R18-B、以後も増える）は多重検定であり、最良に見える施策は過大評価
されている前提で扱う。対応:
- **holdout期間の設定**: 以後の反実仮想は「検証に使ってよい期間」と「触らない
  holdout期間」を分ける（例: 直近1ヶ月をholdoutとして温存）。
- **R13-C完了後のout-of-sample再検証をpaper昇格の必須条件化**: 反実仮想でプラスを
  示した施策（セクターcap30%、ss帯除外、R18-B N=7等）は、R13-C完了後の新規データ
  期間で同符号の効果を再確認できるまで昇格提案を凍結する。

### R18-E: コストモデル実装確認（起票のみ）

経済性ゲート（check_go_no_go.py economic_viability）および各反実仮想のPnLに
スリッページ/手数料の控除が入っているかをコードレベルで確認する（pnl_state.jsonの
pnlはbroker fill価格ベース=paperのシミュレート済みスリッページのみの可能性）。
確認結果をdocs化し、実弾移行前に「実弾スリッページの実測計画」（小サイズでの
市場注文/指値のfill品質測定）を策定する。

### 備考

- **米国内非ITユニバース拡張**: 現ユニバースはIT/半導体偏重。Alpacaのまま
  金融/ヘルスケア/エネルギー等へ拡張可能（新規契約不要）。セクター集中の構造是正
  として有望だが、ユーザー判断待ち。
- **下落局面ヘッジ（中期）**: R18-Aの結果、指数レジームでのエントリー抑制は効果薄。
  ヘッジ（インバースETF/プット等）は別設計として中期課題に置く（IBKR移行後の
  商品アクセスも関係）。
