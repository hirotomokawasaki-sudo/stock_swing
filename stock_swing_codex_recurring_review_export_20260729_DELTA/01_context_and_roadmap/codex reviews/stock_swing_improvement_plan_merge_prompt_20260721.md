# 先方AIへ直接送る改善計画マージ指示文

以下をそのまま先方AIへ送ってください。

---

現在のstock_swing repositoryに存在する改善計画を、添付のCodexレビューとマージしてください。

## 入力ファイル

必ず次の3ファイルを最初に全文確認してください。

1. `stock_swing_codex_review_report_20260721.md`
2. `stock_swing_codex_fix_instructions_20260721.md`
3. `stock_swing_improvement_plan_merge_spec_20260721.md`

その後、repository内から最新のcanonical improvement plan、implementation status、Go/No-Go文書、daily log、関連するF/G/R/P計画を検索してください。過去ファイル名を決め打ちせず、`rg`等で現在使用中の計画を特定してください。

## 絶対条件

運用上の正しいasset allocation方針は次です。

```text
Stock 85%
ETF 15%前後
```

ETF-first / Stock 15%は古い前提です。現在のStock 90.9% / ETF 9.1%を今回の重大問題とは扱わないでください。

ただし、添付exportの`portfolio_allocation.yaml`、実装コメント、旧改善計画にはETF 85% / Stock 15%やstock-reducedが残っています。canonical config、allocator、position sizing、console、promotion gate、改善計画のsource of truthをStock 85% / ETF 15%へ統一する計画に修正してください。ユーザー承認なしにETF-firstや恒久的stock shadowへ変更しないでください。

## マージ方法

H0-H9を既存計画の後ろへ単純追加しないでください。既存R0-R8を維持し、内容をR0-v2〜R8-v2へ改訂してください。

統合関係は以下です。

```text
R0-v2 <- H0 + H1 + H2 + H4 + 旧R0
R1-v2 <- H1 + H4 + 旧R1
R2-v2 <- H5 + 旧R2
R3-v2 <- H6 + 旧R3/F7
R4-v2 <- H7 + 旧R4
R5-v2 <- H5 + H7 + 旧R5
R6-v2 <- H3 + H9 + 旧R6
R7-v2 <- H8 + 旧R7
R8-v2 <- H7 + 旧R8
```

F/G/P taskは削除せず、どのR-v2 taskへ統合されたかtraceabilityを残してください。

## Statusの再監査

statusは次だけを使用してください。

- `VERIFIED_COMPLETE`
- `IMPLEMENTED_UNVERIFIED`
- `REOPENED`
- `IN_PROGRESS`
- `BLOCKED_BY_DATA`
- `PLANNED`

moduleやunit testが存在するだけでは`VERIFIED_COMPLETE`にしないでください。最新code、実run、artifact、acceptance criteriaのすべてで確認してください。

特に次を再監査してください。

1. Ledger/PnL
   - closed/quarantine重複41件
   - closed時系列逆転62件
   - closed holding_days欠損245件
   - realized PnL `-$103,309.56`と`-$5,690.07`の不一致
2. P9 Guardrail
   - daily/weekly loss、consecutive loss、API、token metricsの実接続
   - reduce_size、ai_pause、flatten_riskyを含む全actionのE2E接続
3. P6/Experiment
   - decision -> order -> fill -> trade join
   - run_id / experiment_id / config_hash coverage
4. Sector shock
   - days_held/state persistence
   - symbol-specific benchmark
   - signal_strength return proxy廃止
   - 実価格pathによるcounterfactual
5. Console
   - current breaker stateとlast run statusの分離
   - non-dry-run ledger_quality
   - entry/guardrail/allocation blockを含む完全funnel

上記の実データ問題が解消されていない項目は、過去に完了扱いでも`REOPENED`または`IMPLEMENTED_UNVERIFIED`へ変更してください。

## 依存関係

R0-v2のledger/PnL/guardrail/metadata acceptanceが完了するまで、次を開始しないでください。

- R3-v2 sector shock paper A/B
- stop閾値の本採用変更
- R5-v2 promotion/live判定
- R8-v2 MLによるexecution影響

## 今回の作業範囲

今回は改善計画とstatus文書のマージ・再整理まで実施してください。戦略parameter変更、PnL state rebuild、注文処理変更、live移行はまだ実行しないでください。

既存計画ファイルはbackupまたはgit履歴で復元可能な状態にし、差分を小さく保ってください。別の巨大な計画を新設するのではなく、現在運用中のcanonical planを更新してください。

## 必須出力

repositoryの命名規則に合わせて、最低限次を作成・更新してください。

1. canonical improvement plan
   - R0-v2〜R8-v2
   - priority、status、dependencies、acceptance、tests、evidence、target date、rollback
2. `IMPROVEMENT_PLAN_CHANGELOG_20260721.md`
3. `IMPROVEMENT_PLAN_TRACEABILITY_20260721.csv`
4. `IMPROVEMENT_PLAN_MERGE_RESULT_20260721.md`

Merge resultには以下を記載してください。

- 読み込んだcanonical planのpath
- 変更したファイル
- 旧task -> final R-v2の対応
- statusをreopenした項目と根拠
- Stock 85% / ETF 15%訂正を反映した箇所
- 未解決conflict
- 次に実装すべき最初のbatch
- `git diff --stat`

## 完了前セルフチェック

- H0-H9が独立した第二roadmapとして残っていないか
- F/G/P taskの履歴が失われていないか
- ETF-first / Stock 15%が現行方針として残っていないか
- evidenceなしで`VERIFIED_COMPLETE`になっていないか
- R0-v2未完のままR3/R5/R8が開始可能になっていないか
- roadmap、implementation status、Go/No-Goのstatusが矛盾していないか

セルフチェック完了後、変更内容を要約して提出してください。

---

