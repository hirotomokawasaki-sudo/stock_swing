# Stock Swing Improvement Plan Merge Specification - 2026-07-21

## 1. 目的

今回のCodexレビューで作成したH0-H9を、既存のF/G/R/P計画へ単純追記せず、現在のcanonical roadmapへ重複なく統合するための仕様です。

統合後は、既存のR0-R8を維持しつつ内容を`R0-v2`から`R8-v2`として改訂してください。H0-H9はレビュー上の作業分類であり、最終roadmapの新しい並行番号体系として残しません。

## 2. 最重要の方針訂正

運用上の正しいasset allocation方針は次のとおりです。

```text
Stock: 85%
ETF:   15%前後
```

`stock_swing_codex_full_review_export_20260721`に含まれる`portfolio_allocation.yaml`、実装コメント、旧改善計画のETF-first / stock-reduced記述は古い前提です。

現在のopen entry notionalはStock 90.9% / ETF 9.1%で、方針から大きく外れているとは扱いません。今回の改善対象はallocationの反転ではなく、config、allocator、position sizing、console、promotion gate、改善計画のsource of truthをStock 85% / ETF 15%へ統一することです。

ユーザー承認なしにETF-first、Stock縮小、Stock shadowを恒久方針へ変更しないでください。

## 3. 統合時の入力資料

優先順位は以下です。

1. ユーザーが明示した運用方針。本書のStock 85% / ETF 15%訂正を含む。
2. 実repositoryの最新code/config/dataから得られる事実。
3. `stock_swing_codex_review_report_20260721.md`
4. `stock_swing_codex_fix_instructions_20260721.md`
5. repository内の最新canonical improvement plan / implementation status。
6. `stock_swing_revised_improvement_plan_for_external_review_20260625.md`等の旧計画。これは履歴として使用する。

旧計画の数値や完了判定が最新実データと矛盾する場合、旧計画を優先しないでください。ただし履歴は削除せずchange logへ残します。

## 4. Status定義

全phase/taskで次のstatusだけを使用してください。

| Status | 定義 |
|---|---|
| `VERIFIED_COMPLETE` | code、実run、artifact、acceptance testのすべてで確認済み |
| `IMPLEMENTED_UNVERIFIED` | codeまたはmoduleはあるが、実runまたはacceptance未確認 |
| `REOPENED` | 過去に完了扱いだったが、回帰・未接続・データ矛盾が判明 |
| `IN_PROGRESS` | 実装中で、依存関係を満たしている |
| `BLOCKED_BY_DATA` | 実装より先にclean data/sampleが必要 |
| `PLANNED` | 未着手で開始条件を満たしていない |

「moduleが存在する」「unit testがある」だけでは`VERIFIED_COMPLETE`にしません。

## 5. H0-H9からR0-R8への統合表

| Final roadmap | 統合元 | 改訂内容 | 初期status候補 |
|---|---|---|---|
| R0-v2 Safety, Ledger and Integration Gate | H0, H1, H2, H4 / 旧R0 | ledger/PnL、P6 metadata、P9全metric/action、pending reconciliation、recovery pending | `REOPENED` |
| R1-v2 Trade Lifecycle and Attribution | H1, H4 / 旧R1 | immutable fill ledger、execution leg、exit attribution、rebuild idempotency | `REOPENED` |
| R2-v2 Stock/ETF Classification and Policy Separation | H5 / 旧R2 | Stock 85 / ETF 15を維持し、分類・成績・risk budgetを分離。Stock縮小は目的にしない | `REOPENED` |
| R3-v2 Exit Counterfactual and Sector Shock | H6 / 旧R3, F7 | 実価格path、MFE/MAE、sector別benchmark、stateful recovery、paper A/B | `BLOCKED_BY_DATA` |
| R4-v2 Signal and Confidence Calibration | H7 / 旧R4 | saturation修正、decile、calibration、point-in-time feature snapshot | `IMPLEMENTED_UNVERIFIED` |
| R5-v2 Portfolio Risk and Promotion Gates | H5, H7 / 旧R5 | Stock 85 / ETF 15 band、factor/cluster risk、cost込みpromotion gate | `REOPENED` |
| R6-v2 Console and Operational Observability | H3, H9 / 旧R6 | current state/last run分離、quality gate、完全funnel、cache/SLO | `IMPLEMENTED_UNVERIFIED` |
| R7-v2 Data Reliability and Operational Edge Cases | H8 / 旧R7 | source SLA、lineage、macro/news/earnings、pool/cache、corporate action | `IN_PROGRESS` |
| R8-v2 Learning and ML | H7 / 旧R8 | clean joinable labels後のみ。champion/challenger、drift、rollback | `BLOCKED_BY_DATA` |

初期statusは候補です。最新repositoryでacceptance evidenceを確認して確定してください。

## 6. 既存「完了」項目の再評価

以下は削除せず、完了状態を再監査します。

### P6 / R0 experiment management

Schema/moduleの存在は認めます。ただしdecision -> order -> fill -> trade joinとrun_id / experiment_id / config_hash coverageが99%以上になるまでは`VERIFIED_COMPLETE`にしません。

### P9 / R0 guardrail

GuardrailEngineとCircuitBreakerの存在は認めます。ただし全configured metrics供給、reduce_size / block_buys / ai_pause / flatten_risky / haltのE2E test、clean scheduled runが揃うまでは`REOPENED`または`IMPLEMENTED_UNVERIFIED`です。

### F1 / G3 ledger and PnL

closed/quarantine重複、時系列逆転、holding_days欠損、performance summary不一致がゼロになるまで`REOPENED`です。

### F7 sector shock

shadow moduleの存在は認めます。ただしvalid sector_shock_hold trigger、days_held/state、symbol-specific benchmark、実価格counterfactualが揃うまではA/Bを開始しません。

### G8 / R2 / R5 allocation

ETF-first / stock-reduced前提は廃止し、Stock 85% / ETF 15%前後へ訂正します。過去の変更履歴は残します。

## 7. 依存関係

```text
R0-v2 Ledger/PnL/Guardrail/Metadata
  -> R1-v2 Lifecycle/Attribution
  -> R2-v2 Classification/Policy
  -> R6-v2 Correct Console Contract
  -> R3-v2 Exit Replay/Shadow/A-B
  -> R4-v2 Signal Calibration
  -> R5-v2 Promotion/Risk Gates
  -> R8-v2 ML

R7-v2 Data ReliabilityはR0-v2完了後、R3/R4/R6と並行可能
```

R0-v2 acceptance未達の間、R3-v2のpaper A/B、R5-v2の昇格、R8-v2のML execution影響を開始しません。

## 8. 改訂後の実日程

| 期間 | Phase | Gate |
|---|---|---|
| 2026-07-21〜07-22 | R0-v2 containment | PAPER固定、invalid performanceを昇格判定から除外 |
| 2026-07-23〜07-27 | R0-v2 ledger/PnL | chronology/quarantine/PnL/equity bridge PASS |
| 2026-07-23〜07-28 | R0-v2 guardrail | 全metric/action E2E PASS |
| 2026-07-28〜07-31 | R1-v2, R2-v2, R6-v2 core | metadata join>=99%、Stock85/ETF15統一、status contract PASS |
| 2026-08-03〜08-14 | R3-v2, R7-v2 | historical replayとvalid forward shadow |
| 2026-08-17〜08-28 | R4-v2, R5-v2 paper A/B | costs込みpromotion gate評価 |
| 2026-08-31以降 | gate review | micro-live可否を別途判定 |

日程よりacceptance gateを優先します。未達時は後続phaseを自動延期してください。

## 9. Canonical roadmapに必須の列

各taskに次を持たせます。

- ID
- objective
- status
- priority
- dependencies
- source files
- implementation summary
- evidence path
- acceptance criteria
- test names
- data/sample requirement
- rollback
- owner
- target date
- last verified at
- blocking reason

## 10. 必須出力

先方AIは以下を作成または更新してください。repositoryの既存命名規則があればそれを優先します。

1. canonical improvement plan
   - R0-v2〜R8-v2を一つのroadmapとして記載
2. `IMPROVEMENT_PLAN_CHANGELOG_20260721.md`
   - 旧statusから新statusへの変更理由
   - Stock 85 / ETF 15訂正
   - reopenした項目とevidence
3. `IMPROVEMENT_PLAN_TRACEABILITY_20260721.csv`
   - old task ID, H task ID, final R task ID, status, evidence, acceptance
4. `IMPROVEMENT_PLAN_MERGE_RESULT_20260721.md`
   - merge結果、未解決conflict、変更ファイル、次に実装するbatch

## 11. マージ完了条件

- H0-H9が独立した並行roadmapとして残っていない。
- 既存F/G/P taskが消えず、final R taskへtraceできる。
- Stock 85% / ETF 15%が全計画の唯一のallocation方針になっている。
- 過去のETF-first / stock-reducedはhistorical noteとしてのみ残る。
- 完了判定がacceptance evidenceと一致する。
- R0-v2未完のままR3 A/B、R5 promotion、R8 MLへ進めない。
- roadmap、implementation status、console readiness、Go/No-Go文書でstatusが一致する。

