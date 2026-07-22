# Stock Swing Codex Full Review Report - 2026-07-21

## 1. 結論

現時点の判定は **PAPER継続 / LIVE移行NO-GO** です。

前回から、console false-OKの修正、benchmark収集、exit attribution、token CSV、テスト拡充には進歩があります。ただし、公式成績の母集団に隔離済み・時系列不正な取引が再混入しており、guardrailの多くも設定だけで実行系に接続されていません。したがって、overall PF=0.62、ETF/Stock比較、Exit別PF、counterfactual PF=1.60を昇格判断やパラメータ最適化に使うことはできません。

優先順位は次のとおりです。

1. 台帳・PnL・broker equityの整合性を回復する。
2. guardrailの全ルールと全アクションを実行系へ接続する。
3. run/experiment/decisionの追跡を実データで成立させる。
4. sector shock、stop、portfolio allocationを実測可能なA/Bへ直す。
5. consoleとデータ収集を、上記の正しい状態を表示・監視できる形へ改修する。

## 2. 評価サマリー

| 領域 | 判定 | 要点 |
|---|---|---|
| 安定稼働 | RED | 最新runはHALTED、その後manual clear。G1-v2適用後の正常runが未提示 |
| 台帳・PnL | RED | closed/quarantine重複、時系列逆転、holding_days未計算、PnLソース不一致 |
| 投資戦略 | RED | 信頼できるpost-change標本は14件のみ。Exit反実仮想は方式が無効 |
| Guardrail | RED | 損失・API・token系metricsが未接続。reduce_size/ai_pause等も未接続 |
| データ収集 | YELLOW | Massive日足・5分足は取得。一方macroはunknown、source SLAとlineageがない |
| 実験・学習 | RED | decision/tradeのrun_id・experiment_idが欠落し、outcome joinが0件 |
| Console | YELLOW-RED | 表示機能は増えたが、current stateとlast run、品質と成績が混在 |
| テスト | YELLOW | 763 passed。ただし本番エクスポートに対する不変条件テストが不足 |
| セキュリティ | YELLOW | secret本体は見当たらないが、account numberがexportされている |

## 3. 独立再計算結果

### 3.1 公式値と評価可能性

| Cohort | n | PF | WR | Net PnL | 判定 |
|---|---:|---:|---:|---:|---|
| export上のofficial closed | 259 | 0.624 | 40.9% | -$103,309.56 | 台帳汚染のため利用不可 |
| 2026-07-14以降 | 14 | 0.278 | 35.7% | -$11,433.59 | 時系列は追えるが標本不足 |
| 2026-07-17以降 | 4 | 1.697 | 75.0% | +$832.28 | 少なすぎて判断不可 |

2026-07-14以降14件のExit別内訳は以下です。

| Exit | n | PF | Net PnL |
|---|---:|---:|---:|
| trailing_stop | 6 | 1.694 | +$1,646.79 |
| stop_loss | 5 | 0.000 | -$12,114.48 |
| breakeven_stop | 3 | 0.286 | -$965.90 |

stop_loss改善の必要性は明確ですが、5件だけで閾値を広げる根拠にはなりません。sector shock、個別悪材料、gap、相対弱さ、MFE/MAEを分けたうえで検証すべきです。

### 3.2 現在ポートフォリオ

`trades_open.csv`のentry notional再計算では、14 lot中13 lotがstock、1 lotがETFです。

| Asset class | Lot | Entry notional | 比率 |
|---|---:|---:|---:|
| Stock | 13 | $300,210.22 | 90.9% |
| ETF | 1 | $30,101.40 | 9.1% |

ユーザー確認済みの現行方針は **Stock 85% / ETF 15%前後** です。したがって、実ポートフォリオのStock 90.9% / ETF 9.1%は概ね方針に沿っており、今回の重大問題とは扱いません。

一方、添付された`configs/strategy/portfolio_allocation.yaml`にはETF 85% / Stock 15%と記載され、実装コメントや旧計画にもETF-first / stock-reducedが残っています。実ポートフォリオではなく、設定・文書・コードがどの方針を参照しているかが不統一です。正しいsource of truthをStock 85% / ETF 15%へ統一する必要があります。

## 4. 重大な指摘

### P0-1: quarantineがofficial closedへ再混入している

事実:

- `trades_closed.csv` 259件と`trades_quarantined.csv` 54件で、trade_idが41件重複しています。
- official closed内に`entry_time > exit_time`が62件あり、合計PnLは-$45,209.49です。
- closed 259件中245件で`holding_days`が空欄です。この245件のPnLは-$91,875.97です。
- stop_loss 112件中107件はholding_days=0ではなく空欄です。`EXIT_ANALYSIS.md`の「pre-min_hold (hd=0): 107件」は誤集計です。

原因根拠:

- `source/pnl_tracker.py:746-752`はclosedかつ`holding_days is None`をcleanとして許可しています。
- rebuild後のbroker_match行でholding_daysが再計算されず、過去にquarantineしたtrade_idもclosedへ再生成されています。

影響:

- PF、WR、Exit別成績、ETF/Stock別成績、symbol別成績、rolling PF gate、promotion gateが汚染されています。
- 「quarantinedは公式成績から除外済み」という`PNL_RECONCILIATION.md`と`DATA_QUALITY_REPORT.md`の判定は誤りです。

### P0-2: PnL source-of-truthは未統一

`PNL_RECONCILIATION.json`には次の3値が同時に存在します。

- clean closed sum: -$103,309.56
- state.cumulative_realized_pnl: -$103,309.56
- performance_summary realized_pnl: -$5,690.07

さらに、broker equity $999,672.45とtracker total PnL -$101,833.77をつなぐinitial equity / cash flow / fee / adjustment bridgeがありません。stateとclosedの一致だけでは、brokerに対する財務的な照合になりません。

### P0-3: Autonomous guardrailの大半が動作していない

設定にはdaily/weekly loss、consecutive losses、API error、order rejection、token spikeがありますが、`source/paper_demo.py:1927-1939`でpost-runに渡す値はstale、mismatch、API=0固定、order rejectionだけです。

追加の問題:

- `daily_realized_loss_pct`、`daily_total_loss_pct`、`weekly_total_loss_pct`、`consecutive_losing_trades`、`token_spend_spike_pct`はコード内でmetrics生成されていません。
- `api_error_rate_pct`は実測せず0.0固定です。
- `should_skip_ai`はimportされるだけで呼ばれていません。
- `reduce_size`はcandidate dictへsize_multiplierを設定しますが、元のDecisionRecordへ反映せず破棄されます。
- `ai_pause`と`flatten_risky`の実行経路がありません。
- guardrail初期化例外時はwarning_onlyへ落ちて処理継続します。将来liveではfail-closedが必要です。

P9は「設定・判定器あり」ですが、「全ルールと全アクションが運用接続済み」とは評価できません。

### P0-4: sector_shock_holdはA/B開始可能な状態ではない

コード根拠:

- `source/paper_demo.py:1180-1185`は`days_held`、`is_thesis_broken`、`exceeds_portfolio_risk_limit`を渡していません。timeout、partial de-risk、thesis break、portfolio riskが実運用入力を受けません。
- `SectorShockHoldState`は定義されていますが、状態の保存・復元に使われていません。
- 全銘柄をSMH/SOXXと比較し、`symbol_registry.yaml`の銘柄別benchmark_symbolsを使っていません。GOOGL/PANW等も半導体benchmarkで分類されます。
- feature欠損時に`signal_strength * -1`を日次returnの代用にしています。FRWDはこれにより-100%と判定されました。
- `paper_ab`に切り替えても、paper_demo側は分類結果でexit_signalsを変更しません。
- no sector shock時の`soft_stop -> monitor`は、接続すると通常のstopを広範囲に抑止し得ます。

shadowログの3件は、FRWDが不正proxy、GOOGL/PANWはsoft_stopであり、実際の`sector_shock_hold`観測は0件です。「3/10」はA/B readinessとして数えられません。

counterfactualも無効です。sector shock stop 22件を損益0と置き換えただけで、保有後の1/3/5/10日価格、MFE、MAE、timeout、hard stop、slippageを再生していません。また22件中20件はholding_days空欄107件と重複し、129件を単純加算して除外する計算も重複を無視しています。

### P1-1: G1-v2は改善方向だが、根治と検証が未完了

`source/paper_demo.py:1880-1929`は3秒待機後、同runで送ったBUY/SELL symbolをmismatchから減算します。これはfalse HALTを減らしますが、注文status、expected quantity delta、期限、再照合完了を状態として管理しません。真の未反映・未約定も当該run中は一時的に除外できます。

さらに、最新提示runはHALTEDで、その後manual clearされています。G1-v2 commit後の正常なscheduled runがexportにありません。現在は「breaker current=OK」「last run=HALTED」であり、正常復帰確認済みではありません。

### P1-2: Stock 85% / ETF 15%方針のsource of truthが不統一

- ユーザー確認済みの正しい方針はStock 85% / ETF 15%前後です。
- 添付`configs/strategy/portfolio_allocation.yaml`はETF 85% / Stock 15%で逆転しています。
- `source/portfolio_allocation/portfolio_allocator.py`と`paper_demo.py`にはETF-first / stock-reduced時代の説明と挙動が残っています。
- `stock_new_buy_multiplier`等の設定キーは、提示されたPython source内で参照されていません。
- allocation計算でaccount equityを渡す経路とlegacy fallbackが混在しています。

現在の実配分自体を問題とはしません。改善対象は、Stock 85% / ETF 15%を唯一のpolicyとしてconfig、allocator、position sizing、console、promotion gate、既存改善計画へ反映し、target bandとprojected allocationを同じdenominatorで判定することです。

### P1-3: 実験・学習用joinが成立していない

実データ:

- closed trade: decision_id 4/259、run_id 0/259、experiment_id 0/259
- decisions_all: run_id 0/500、experiment_id 0/500
- decision_idを持つclosed/open tradeと`decisions_all.csv`のjoin成功は0件
- deny action 57件に対し、CSVのdeny_reasonは全件空欄

`source/paper_demo.py:1770-1783`では`record_submission()`へrun_id、experiment_id、prompt_version、config_hashを渡していません。F4/R0はschema追加まで進んでいますが、outcome analysis、A/B、promotion gateに必要なend-to-end traceは未完成です。

### P1-4: AI/token telemetryは実コスト計測ではない

- token_usage 1,951行中1,939行が`estimated_rule_based`です。
- model列は`rule_based:breakout_momentum_v1`等のstrategy名で、LLM modelではありません。
- estimated_costは全体で$0です。
- 最新実行の1,371 tokensも実API usageか推計かをconsole上で区別できません。

推計値は容量設計には使えますが、GPT/Claudeの実ランニングコストやskip効果の測定には使えません。`actual_provider_usage`と`estimated_local_tokens`を別指標にしてください。

### P1-5: Consoleがcurrent state、last run、data validityを混在させる

現在のcircuit breakerはmanual clear後OKですが、latest consoleはclear前runのHALTEDです。`SYSTEM_HEALTH.md`はこの2状態を一つのStatusとして表示し、critical alertも残しています。

また、non-dry-runの最終`ConsoleSummary.build()`で`ledger_quality`と`entry_filter_stats`を渡していません（`source/paper_demo.py:1967-1998`）。そのため最新consoleでは:

- ledger_quality `{}`
- attribution coverage `null`
- quarantined trades `0`
- stock_reduced_blocked `0`

となります。実ログではentry filter 1件、guardrail 5件をblockしていますが、decision_funnel.blockedは0です。

### P1-6: Data collectionは価格系に偏り、品質契約がない

良い点:

- 60 symbolsの日足はMassiveで60/60取得。
- 7候補に5分足700 recordsを取得。
- SMH/SOXX/SOXQ/QQQ/SPYの61営業日benchmarkが存在。

不足:

- macro regimeは毎回unknownで、FRED enabled設定が戦略入力へ到達していません。
- SEC/Finnhub/event/earnings/newsのcoverage、freshness、取得件数、失敗率がありません。
- benchmark fallbackにas-of freshness検証がなく、最新行を日付maxではなくCSVの最終出現で採用します。
- Massiveへの並列取得で`Connection pool is full`が多数発生しています。
- weekendでも全symbol取得と特徴量計算を続けています。
- raw data hash、source timestamp、ingested_at、feature as_of、fallback reasonがoutcomeへ紐づきません。

### P1-7: リスク集中を抑える設計が弱い

現在のStock 90.9%は、Stock 85% / ETF 15%前後という方針上は許容されます。ただし、銘柄がtechnology/growthへ集中している点はasset-class配分とは別のリスクです。`paper_demo.py:1209`のsector cap 80%は安定運用向けの集中制約として緩く、個別株同士も同じfactor exposureを持ち得ます。

市場beta、sector/factor exposure、pairwise correlation、top-5 concentration、gap-at-riskを同時に制約する必要があります。

## 5. Console改善提案

WebSocket化より先に、表示契約とデータ品質を直すべきです。推奨構成は以下です。

### Operations header

- Current control state: breaker、kill switch、mode、manual clear時刻、verification pending
- Last run: run_id、started/finished、status、duration、commit/config hash
- Reconciliation: raw mismatch、pending sync、excused、TTL、final mismatch
- Data freshness: broker、daily bars、intraday bars、benchmarks、macro、news

### Portfolio / risk

- equity bridge: starting equity + cash flow + realized + unrealized + fees = broker equity
- target vs actual allocationをmarket valueで表示
- gross/net exposure、beta、sector/factor concentration、risk budget、gap-at-risk
- positionごとのhard stop、soft stop、trailing、MFE/MAE、benchmark-relative return

### Strategy / experiment

- `audited_clean`、`legacy_reconstructed`、`post_change`を明示選択
- invalid cohortではPF/WRを非表示にし、品質エラーを表示
- entry/exit理由、signal decile、confidence calibration、regime、asset class別outcome
- control/testのn、PF、expectancy、drawdown、95% CI、promotion status

### Funnel / data pipeline

- generated -> risk denied -> entry filtered -> allocation blocked -> guardrail blocked -> qty zero -> submitted -> accepted -> filled -> reconciled
- source別coverage、freshness、fallback、error、p50/p95、connection pool saturation
- AI actual usageとestimated local tokensを分離

### 性能面

- 大容量JSON/CSVを画面rerunごとに全読込せず、run完了時に集計snapshotをatomic生成する。
- file mtime/config hashをcache keyにする。
- live statusは15-30秒pollで十分。WebSocketは正しいstate model完成後に追加する。

## 6. データ収集体制の優先順位

| 優先 | データ | 改善内容 | 目的 |
|---|---|---|---|
| 1 | broker orders/fills/account | immutable fill ledger、cash flow、fee、corporate action | PnLと実行の真実 |
| 1 | price/quote | source timestamp、as-of、stale SLA、dual-source差分 | stopとsizingの誤作動防止 |
| 1 | sector/index intraday | sector別benchmark、1/5/15/60分return、breadth | shock判定 |
| 2 | corporate actions/earnings | split/dividend/earnings calendar、point-in-time | 異常価格とevent risk |
| 2 | macro | FRED値・release timestamp・surprise・regime lineage | regime sizing |
| 2 | news | symbol/sector event、source time、sentiment、novelty、severity | thesis break判定 |
| 3 | fundamentals/SEC | filing as-of、revision禁止、quality/growth features | entry quality |
| 3 | market microstructure | spread、volume shock、gap、liquidity | slippageとstop設計 |

各recordには最低でも`event_time`、`available_at`、`ingested_at`、`source`、`source_id`、`revision_id`、`quality_status`を持たせ、future leakageを防いでください。

## 7. 推奨改善ロードマップ

### H0: 即時封じ込め（2026-07-21〜07-22）

- PAPERを維持し、live移行判定を凍結する。
- official performanceを`INVALID_LEDGER`表示にする。
- Stock 85% / ETF 15%方針は維持し、ETF-firstへ反転させない。台帳修復中に新規BUYを制限する場合もasset classではなく全体risk capとして扱う。
- sector_shock paper_abを開始しない。
- manual clear後にclean verification runが終わるまで`RECOVERY_PENDING`とする。

### H1: Ledger/PnL再構築（07-23〜07-27）

- fill/orderを基にimmutable ledgerを再構築する。
- closed時刻、holding_days、quarantine排他、execution leg IDを必須化する。
- broker equity bridgeを追加し、全report/console/exportを同じsnapshotから生成する。

### H2: Guardrail end-to-end化（07-23〜07-28、H1と並行）

- 全metricを一つのRiskSnapshotで生成する。
- pending reconciliation TTLを実装する。
- reduce_size、block_buys、ai_pause、flatten_risky、haltを実行・検証する。

### H3: Traceability / Console contract（07-28〜07-31）

- run/experiment/decision/config hashをdecision -> order -> fill -> trade -> outcomeへ伝播する。
- current control stateとlast runを分離する。
- data validity gateと完全なfunnelを実装する。

### H4: Exit replay / shadow（08-03〜08-14）

- sector別benchmark、intraday as-of、days_held、hard cap、thesis breakを接続する。
- 過去shock日のevent replayとforward shadowを行う。
- 実価格pathで1/3/5/10日MFE/MAEとnet outcomeを比較する。

### H5: Portfolio / Entry A-B（08-17〜08-28）

- Stock 85% / ETF 15%前後をsource of truthとし、allocationをpriorityだけでなく許容bandで実装する。
- signal saturationを修正し、decile別outcomeを測定する。
- fixed stop、ATR stop、sector recovery holdをchampion/challengerで比較する。

### H6: 再判定（08-31以降）

最低条件:

- ledger invariant全件PASS、broker equity bridge差分<=1bp
- metadata join >=99%、asset/sector unknown=0
- 10 scheduled runs連続でunexplained mismatch=0、false HALT=0
- post-change clean closed >=60（推奨100）
- costs込みPF >=1.15、expectancy > 0、max drawdown <=5%
- shock replay >=100 eventsかつforward valid shadow >=10 triggers
- 特定1銘柄・1日・1 exit classだけで利益が成立していない

これを満たすまではPAPERを継続します。満たした場合も最初は通常サイズの10-25%でmicro-liveし、20営業日後に再判定します。

## 8. 今回確認できなかった範囲

exportにはdashboard本体、position sizing本体、simple exit strategy本体、open shock cooldown本体、Massive/hybrid fetcher、rebuild/export scripts、G1-v2 test sourceが含まれていません。したがってConsole描画性能、stock multiplier、Exit precedence、データ取得clientの完全なコードレビューは未完です。

次回exportではこれらを追加し、account numberはredactしてください。`EXPORT_MANIFEST.json`にはsizeだけでなくSHA-256も追加してください。


