# Stock Swing Implementation Instructions - H0 to H9

## 0. この指示書の目的

`stock_swing_codex_review_report_20260721.md`の指摘を、既存repository上で検証・実装するための指示です。

重要ルール:

- Runtime modeはPAPERのままにする。live credential / live endpointへ接続しない。
- H1〜H3完了前にstop閾値拡大、sector_shock paper_ab、ML、自動parameter更新を行わない。
- 各batchを独立commitにし、変更前後のartifactを残す。
- 既存データを上書きせずbackupし、rebuildはidempotentにする。
- 「テストが通る」だけでなく、添付20260721 exportをregression fixtureとして不変条件を確認する。
- 完了報告では変更ファイル、テスト結果、実データ結果、残リスク、rollback方法を記載する。

## H0: Safety containment

### 実装

1. `config/runtime/current_mode.yaml`をpaperに固定する。
2. `INVALID_LEDGER`時はpromotion/live readinessを強制NO-GOにする。
3. 現行方針をStock 85% / ETF 15%前後に固定し、ETF-firstへ反転させない。台帳修復中に新規BUYを抑える場合はasset class別ではなく全体risk capで一時制限する。SELLと既存risk管理は維持する。
4. `SECTOR_SHOCK_HOLD_MODE=shadow`を維持する。
5. breaker manual clear後は`recovery_pending`へ遷移し、clean scheduled run完了後だけ`ok`にする。

### 受入条件

- invalid ledgerでもlive-ready表示にならない。
- config、console、実行policyがStock 85% / ETF 15%を同じsourceから参照する。
- manual clearだけではcurrent statusがOKにならない。

## H1: Ledger integrity and deterministic rebuild

### 対象候補

- `src/stock_swing/tracking/pnl_tracker.py`
- rebuild/migration scripts（repository内を検索して特定）
- `src/stock_swing/cli/reconcile_orders.py`
- performance/export generation scripts

### 実装

1. closed tradeのcanonical validatorを作る。
   - entry_time / exit_timeがparse可能
   - exit_time >= entry_time
   - holding_daysはtimestampsから必ず再計算
   - qty > 0、prices > 0、pnl arithmetic許容差内
   - status=closedとquarantinedは排他
2. `holding_days is None`をcleanとして許可しない。closedでNoneならrepairまたはquarantineする。
3. quarantine IDをtombstoneとしてrebuildへ渡し、同じlogical executionがclosedへ再生成されないようにする。
4. `trade_id`をposition/lot IDとし、partial fillには一意な`execution_leg_id`を追加する。
5. broker order/fillを`executed_at`順で安定sortし、FIFO matchingを決定的にする。
6. corporate actionは通常tradeと分離し、split-adjusted qty/priceとadjustment recordを残す。
7. 一つの`PerformanceSnapshot`を生成し、state/report/console/exportはそのsnapshotだけを参照する。
8. broker equity bridgeを実装する。
   - starting_equity + deposits - withdrawals + realized + unrealized - fees + adjustments
   - broker current equityとの差分を表示

### 必須regression

20260721 fixtureに対し、修正前に以下を再現し、修正後ゼロを確認する。

- closed/quarantine trade_id overlap = 41
- closed entry_time > exit_time = 62
- closed holding_days missing = 245
- duplicate closed trade_id = 1（partial fillはexecution_leg_idで一意化）

### テスト

- `test_closed_trade_requires_computed_holding_days`
- `test_quarantine_and_closed_are_mutually_exclusive`
- `test_rebuild_is_idempotent`
- `test_rebuild_preserves_attribution_and_metadata`
- `test_partial_fill_has_unique_execution_leg_id`
- `test_broker_equity_bridge`
- `test_20260721_export_regression_fixture`

### 受入条件

- invalid chronology=0、missing holding_days=0、closed/quarantine overlap=0
- rebuildを2回実行してhash/count/PnLが不変
- closed sum = state = performance snapshot = console
- broker equity bridge差分 <= $1または1bpの大きい方

## H2: Guardrail end-to-end wiring

### 対象候補

- `src/stock_swing/guardrails/rule_engine.py`
- `src/stock_swing/guardrails/pre_trade_check.py`
- `src/stock_swing/guardrails/circuit_breaker.py`
- `src/stock_swing/cli/paper_demo.py`
- `config/guardrails/autonomous_stop.yaml`

### 実装

1. typed `RiskSnapshot`を作り、startup / pre-order / post-runで同じ生成器を使う。
2. 以下を実測して渡す。
   - stale_price_event_count
   - broker_tracker_raw_mismatch_count
   - broker_tracker_pending_sync_count
   - broker_tracker_unexplained_mismatch_count
   - daily_realized_loss_pct
   - daily_total_loss_pct
   - weekly_total_loss_pct
   - consecutive_losing_trades
   - api_error_rate_pct
   - order_rejection_rate_pct
   - actual_token_spend_spike_pct
3. G1-v2のsymbol減算をpending reconciliation state machineへ置換する。
   - order_id、side、expected qty delta、submitted_at、deadline、last observed state
   - 2/5/10/20秒poll、最大60秒
   - deadline超過でunexplained mismatchとしてhalt
   - 次run startupでもpendingを再検証
4. 全actionを実際の処理へ接続する。
   - reduce_size: DecisionRecord/sizingへ倍率反映
   - block_buys: 新規BUY停止
   - ai_pause: provider callをskipしskip_reason記録
   - flatten_risky: operator approval付きplan生成。自動成行flattenはしない
   - halt: BUY停止、SELL/risk exitのみ許可
5. guardrail setup/evaluation例外はpaperでDEGRADED、将来liveでfail-closedにする。

### テスト

- `test_all_configured_guardrail_metrics_are_supplied`
- `test_reduce_size_changes_final_order_qty`
- `test_ai_pause_skips_provider_call`
- `test_pending_sync_converges_without_halt`
- `test_pending_sync_timeout_halts`
- `test_true_qty_mismatch_is_not_excused`
- `test_manual_clear_requires_verification_run`

### 受入条件

- config上enabledのruleに未供給metricがない。
- 5 actionすべてにend-to-end testがある。
- 10 scheduled paper runs連続でunexplained mismatch=0、false HALT=0。

## H3: PnL, status and console data contract

### 実装

1. statusを分離する。
   - `control.current_status`
   - `last_run.status`
   - `reconciliation.status`
   - `data_quality.status`
   - `strategy_readiness.status`
2. 各statusに`as_of`、`source`、`freshness_seconds`を付ける。
3. manual clear後にlast runが古い場合は`RECOVERY_PENDING`または`STALE`とする。
4. non-dry-runのConsoleSummaryにも必ず渡す。
   - ledger_quality
   - entry_filter_stats
   - guardrail blocked detail
   - allocation blocked detail
   - sector shock valid/invalid counts
5. funnelを次のstageで保存する。
   - generated, risk_denied, entry_blocked, allocation_blocked, guardrail_blocked, qty_zero, submitted, accepted, filled, reconciled
6. data_qualityがREDならPF/WRを`not_valid`として表示し、数値をpromotion gateへ渡さない。

### テスト

- `test_current_control_state_is_separate_from_last_run`
- `test_stale_last_run_after_manual_clear_is_recovery_pending`
- `test_non_dry_run_console_includes_ledger_quality`
- `test_funnel_counts_all_block_stages`
- `test_invalid_cohort_cannot_promote`

## H4: Durable metadata and experiment join

### 対象候補

- DecisionRecord / run context / experiment context
- `paper_demo.py::_save_decisions`
- `pnl_tracker.record_submission`
- order/fill/trade event schemas
- export scripts

### 実装

1. run contextをfieldとしてDecisionRecordへ設定する。evidence内だけに置かない。
2. `record_submission()`へ以下を渡す。
   - run_id
   - experiment_id
   - prompt_version
   - config_hash
   - decision_id
   - canonical asset_class / sector
3. order、fill、closed trade、outcomeへ同じIDを伝播する。
4. historical exporterで`deny_reasons` listをJSONまたは`|`区切りで保持する。
5. `decisions_all.csv`はallを意味するなら上限500を廃止する。上限を使う場合は`decisions_latest_500.csv`へ改名する。
6. join coverage reportを毎run生成する。

### 受入条件

- deployment後のdecision -> order -> fill -> trade join >=99%
- run_id / experiment_id / config_hash coverage >=99%
- deny actionのdeny_reason coverage=100%
- latest 60d exportでtrade decision_id join=100%（broker reconstructed legacyを除く）

## H5: Canonical classification and Stock 85 / ETF 15 allocation

### 実装

1. symbol registryを唯一のclassification sourceにする。
2. missing/blank/`unknown`は同じ扱いとし、registry lookupで補完する。未登録symbolはBUYをblockしてalertする。
3. historical backfillをidempotentに実行する。
4. portfolioの唯一のtargetをStock 85% / ETF 15%前後にする。旧ETF-first / stock-reduced記述と逆向きconfigを削除またはmigrationする。
5. targetをpriorityだけでなく許容bandにする。
   - market value / equityベース
   - 推奨初期bandはStock 80-92% / ETF 8-20%
   - stock、ETF、sector、correlated clusterごとに上限
   - order後のprojected allocationで判定
6. `stock_new_buy_multiplier`やETF multiplierを残す場合は、戦略配分ではなく一時的risk adjustmentとして意味を明確化し、final qtyへ実際に適用する。consoleへbefore/after qtyを出す。
7. ユーザー承認なしにStock 85% / ETF 15%自体を変更しない。

### テスト

- `test_unknown_symbol_is_blocked`
- `test_historical_asset_class_backfill_is_idempotent`
- `test_stock_85_etf_15_is_single_policy_source`
- `test_target_band_blocks_projected_overweight`
- `test_stock_multiplier_changes_final_qty`
- `test_correlated_positions_share_cluster_cap`

### 受入条件

- audited trade asset_class/sector unknown=0
- config / allocator / sizing / console / improvement planのtargetがStock 85% / ETF 15%で一致
- target band超過の新規order=0
- console target/actual/projectedが同じdenominatorを使用
## H6: Unified exit policy and sector shock validation

### 先に決めるprecedence

1. invalid price / corporate action handling
2. emergency hard loss cap
3. thesis break / portfolio risk
4. market-open shock cooldown
5. sector shock recovery state
6. relative weakness exit
7. breakeven / trailing / time-based exit

`simple_exit_v2`、`min_hold`、`open_shock_cooldown`、`sector_shock_hold`でhard capとtimeoutを重複定義しないでください。

### 実装

1. hard capを一つに統一し、初期候補は-12%。変更はA/Bでのみ行う。
2. symbol registryのbenchmark_symbolsをsymbolごとに使用する。
3. shock判定にはcurrent sessionの1/5/15/60分returnとbreadthを使う。daily fallbackにはmarket date SLAを付ける。
4. feature欠損時にsignal_strengthをreturnとして使用しない。分類を`insufficient_data`にする。
5. days_held、thesis break、portfolio riskを実値で渡す。
6. recovery stateをtrade_id単位でatomic persistする。
7. `soft_stop`は通常stopを無期限monitorにしない。confirmation window、最大猶予、partial de-riskを明示する。
8. `paper_ab`ではentry時または最初のstop trigger時にdeterministic bucketを固定する。
9. counterfactualは実価格pathで再生する。
   - exit now
   - hold 1/3/5/10 trading days
   - hard cap / timeout / relative weakness適用
   - MFE、MAE、realized outcome、slippage、gap loss
10. historical event replayとforward shadowを分ける。

### テスト

- `test_symbol_specific_benchmark_routing`
- `test_missing_return_never_uses_signal_strength_proxy`
- `test_days_held_drives_partial_and_timeout`
- `test_hard_cap_precedes_recovery_hold`
- `test_recovery_state_survives_restart`
- `test_paper_ab_changes_exit_only_for_treatment_bucket`
- `test_counterfactual_uses_future_price_path_without_runtime_lookahead`

### 昇格条件

- invalid shadow=0
- historical shock replay >=100 events
- forward valid stop-trigger shadow >=10
- treatmentがbaselineよりcosts込みexpectancy、CVaR、max drawdownのうち少なくとも2指標で改善
- hard-cap loss、gap loss、timeout lossが悪化しない

## H7: Entry strategy and learning foundation

### 実装

1. signal_strength saturationを修正し、raw score、normalized score、cross-sectional percentileを保存する。
2. confidenceをoutcome calibration可能なprobabilityとして定義する。固定0.85多発を解消する。
3. feature snapshotをdecision時点のas-ofデータでimmutable保存する。
4. outcome labelを1/3/5/10d return、MFE、MAE、exit outcomeで作る。
5. decile別PF/expectancy/coverageとcalibration curveを生成する。
6. learningはrecommendation-onlyとし、自動本番反映を禁止する。
7. champion/challenger、model/config registry、drift detection、rollbackを用意する。

### 開始条件

- H1〜H4 PASS
- clean joinable outcomes >=300で単純calibration開始
- ML trainingは原則>=1,000 clean labels

## H8: Data collection reliability

### 実装

1. sourceごとのSLAとquality reportを実装する。
   - broker position/order: <=30秒
   - intraday quote/bar: market open中 <=2分
   - daily bar: 前営業日close確定後の期待時刻
   - sector benchmark: exit判断時点と同じas-of
2. `event_time`, `available_at`, `ingested_at`, `source`, `source_id`, `revision_id`, `quality_status`をcanonical schemaへ追加する。
3. Massive clientのconnection poolを共有し、max connections/pool sizeをconcurrencyへ合わせる。
4. batch/cacheを使用し、同run内の重複fetchを除去する。
5. market closed時は必要なmaintenance job以外を早期終了する。
6. FRED/SEC/Finnhub/news/earningsごとにcoverage、freshness、errors、fallbackをconsoleへ出す。
7. macroがunknownの場合は原因とsizing fallbackを明示する。
8. priceはbroker/primary/secondaryの差分を監視し、splitやstaleを自動検知する。

### 受入条件

- 20 scheduled runsでrequired source coverage >=99.5%
- stale benchmarkを使ったexit classification=0
- connection pool warning=0
- duplicate external fetchを現状比50%以上削減

## H9: Console performance and operator usability

### 実装

1. H3のstatus contractをconsole最上部へ表示する。
2. 四つのviewに整理する。
   - Operations
   - Portfolio & Risk
   - Strategy & Experiments
   - Data & Cost
3. audited_clean / legacy_reconstructed / post_change cohort selectorを追加する。
4. invalid dataを赤帯表示し、無効なPFを通常値として表示しない。
5. target/actual/projected allocation、risk concentration、exit state、data ageを表示する。
6. run完了時にpre-aggregated snapshotをatomic生成する。
7. dashboardはmtime/config hash cacheを使い、CSV全読込を毎rerunで行わない。
8. 15-30秒pollで開始し、WebSocketはstate correctness確認後に追加する。

### Performance SLO

- initial render p95 <=2秒
- cached rerun p95 <=500ms
- latest status ageを常時表示
- JSON parse/read error時はstale last-known-goodとerror bannerを表示

## 実装順序と停止条件

| 日程 | Batch | 次へ進む条件 |
|---|---|---|
| 07-21〜07-22 | H0 | PAPER固定、invalid performance非表示 |
| 07-23〜07-27 | H1 | ledger/broker equity invariants PASS |
| 07-23〜07-28 | H2 | 全guard action E2E PASS |
| 07-28〜07-31 | H3-H4 | join>=99%、status contract PASS |
| 08-03〜08-14 | H6-H8 shadow/replay | valid replay/shadow dataset完成 |
| 08-17〜08-28 | H5-H7 paper A/B | promotion criteria達成 |
| 08-31以降 | H9 final + gate review | micro-live可否を別途判定 |

どのbatchでもPnL不一致、unexplained mismatch、invalid chronology、test failureが発生したら後続戦略変更を停止し、そのbatch内で修復してください。

## 先方AIの完了報告フォーマット

各batchごとに以下を出力してください。

1. `BATCH_RESULT.md`
   - status: PASS / PARTIAL / FAIL
   - changed files
   - behavior changes
   - before/after metrics
   - tests and exact result
   - migration/rollback
   - remaining risks
2. `VALIDATION.json`
   - invariant名、expected、actual、pass、evidence path
3. `git diff --stat`と対象差分
4. secretsを除いた最新review export


