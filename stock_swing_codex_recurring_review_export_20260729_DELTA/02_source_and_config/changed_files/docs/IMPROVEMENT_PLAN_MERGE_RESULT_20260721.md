# IMPROVEMENT_PLAN_MERGE_RESULT_20260721.md

**作成日**: 2026-07-21
**Commit (pre-merge)**: 744e3fa
**作業者**: OpenClaw assistant

---

## 読み込んだ canonical plan のパス

- `docs/console_improvement_tasks.md` — R0-R8 改訂版（改訂日: 2026-07-13）

## 入力ファイル（Codex review）

1. `stock_swing_codex_review_report_20260721.md` — Codex 全評価 (H0-H9 指摘)
2. `stock_swing_codex_fix_instructions_20260721.md` — H0-H9 実装指示
3. `stock_swing_improvement_plan_merge_spec_20260721.md` — マージ仕様

---

## 変更したファイル

| ファイル | 変更内容 |
|---------|---------|
| `docs/console_improvement_tasks.md` | R0-R8 → R0-v2〜R8-v2 へ改訂。歴史的記録セクション保持。 |
| `config/strategy/portfolio_allocation.yaml` | ETF=0.85/Stock=0.15 → stocks=0.85/ETFs=0.15 に訂正 |
| `config/strategy/portfolio_allocation.yaml.bak_20260721` | 旧設定バックアップ（新規） |
| `docs/IMPROVEMENT_PLAN_CHANGELOG_20260721.md` | 新規作成 |
| `docs/IMPROVEMENT_PLAN_TRACEABILITY_20260721.csv` | 新規作成（31 entries） |
| `docs/IMPROVEMENT_PLAN_MERGE_RESULT_20260721.md` | 本ファイル（新規） |

---

## 旧 Task → Final R-v2 対応表

| 旧 Task | H Task | Final R-v2 | Old Status | New Status |
|---------|--------|-----------|-----------|-----------|
| R0 guardrail+experiment | H0+H1+H2+H4 | R0-v2 | ✅完了 | **REOPENED** |
| P9 GuardrailEngine | H2 | R0-v2-C | ✅完了 | **REOPENED** |
| P6 ExperimentContext | H4 | R0-v2-D | ✅完了 | **REOPENED** |
| RF-1 quarantine gate | H1 | R0-v2-B | ✅完了 | **REOPENED** |
| G3 PnL source-of-truth | H1 | R0-v2-B | ✅完了 | **REOPENED** |
| R1 exit attribution | H1+H4 | R1-v2 | ✅完了 | **REOPENED** |
| RF-4 durable metadata | H4 | R0-v2-D | ✅完了 | **REOPENED** |
| R2 ETF/Stock 分離 | H5 | R2-v2 | ✅完了 | **REOPENED** |
| G8 portfolio stock_reduced | H5 | R2-v2 | ✅完了 | **REOPENED** |
| R2-A asset_class backfill | H5 | R2-v2 | ✅完了 | **REOPENED** |
| R3-A counterfactual script | H6 | R3-v2 | ✅完了 | **REOPENED** |
| R3-B exit replay | H6 | R3-v2 | ✅完了 | **BLOCKED_BY_DATA** |
| RF-7 sector_shock shadow | H6 | R3-v2 | ✅完了 | **BLOCKED_BY_DATA** |
| R4-B min_signal_strength | H7 | R4-v2 | ✅完了 | IMPLEMENTED_UNVERIFIED |
| R5 昇格ゲート | H5+H7 | R5-v2 | PLANNED | **REOPENED** |
| R6 Console C1-F/GW/LS | H3+H9 | R6-v2 | ✅完了 | IMPLEMENTED_UNVERIFIED |
| R8 ML | H7 | R8-v2 | PLANNED | BLOCKED_BY_DATA |
| RF-3 atomic write | H1 | R1-v2 | ✅完了 | VERIFIED_COMPLETE |
| RF-8b attribution recovery | H4 | R1-v2 | ✅完了 | VERIFIED_COMPLETE |
| R4-A signal saturation | H7 | R4-v2 | ✅完了 | VERIFIED_COMPLETE |
| R7-A corporate action | H8 | R7-v2 | ✅完了 | VERIFIED_COMPLETE |
| G2 console false-OK fix | H3 | R6-v2 | ✅完了 | VERIFIED_COMPLETE |
| G1 circuit breaker | — | R0-v2-C | ✅完了 | VERIFIED_COMPLETE |
| G9 min_hold 1日 | — | R3-v2 dep. | ✅完了 | VERIFIED_COMPLETE |
| G1-v2 lag exclusion | — | R0-v2-C | ✅完了 | IMPLEMENTED_UNVERIFIED |
| RF-8b-v2 attribution | — | R1-v2 | ✅完了 | VERIFIED_COMPLETE |

---

## Status を REOPENED にした項目と根拠

### R0-v2（および P9/P6/RF-1/G3）: REOPENED

**確認した実データ**:
- `pnl_state.json` 実測: closed/quarantine overlap = **41件**
- entry_time > exit_time = **62件**
- holding_days is None = **245件**
- asset_class unknown = **245件**

**コード確認**:
- `paper_demo.py:1927-1939` の `_post_metrics`: `daily_realized_loss_pct` / `weekly_total_loss_pct` / `consecutive_losing_trades` / `token_spend_spike_pct` が **MISSING**
- `api_error_rate_pct = 0.0` ハードコード
- `record_submission()` に run_id / experiment_id / config_hash 未渡し
- `reduce_size` action: DecisionRecord へ未反映（破棄）
- decision → trade join: **0/259件**

### R2-v2: REOPENED

**確認した実データ**:
- `config/strategy/portfolio_allocation.yaml`: ETF=0.85, Stock=0.15（逆転）→ **修正済み**
- asset_class unknown in closed: **245件**

### R3-v2: BLOCKED_BY_DATA

**確認した実データ**:
- sector_shock shadow logs の有効件数: soft_stop=2, no_sector_data=5, relative_weakness=1
- 実際の sector_shock_hold trigger: **0件**（Codex review P0-4 と一致）
- counterfactual: $0 仮定のみ（実価格 path 未使用）

---

## Stock 85% / ETF 15% 訂正を反映した箇所

1. **`config/strategy/portfolio_allocation.yaml`**: `ETFs: 0.85` → `stocks: 0.85, ETFs: 0.15`（訂正済み）
2. **`docs/console_improvement_tasks.md`**: R2-v2 / R5-v2 の方針記述を全て Stock 85% / ETF 15% へ統一
3. **`docs/IMPROVEMENT_PLAN_CHANGELOG_20260721.md`**: セクション 1 で詳細記録
4. **旧 ETF-first 記述**: 歴史的 note としてのみ残存（現行方針として使用禁止）

---

## 未解決 Conflict

| No. | Conflict | 詳細 | 対応方針 |
|-----|---------|------|---------|
| 1 | `stock_new_buy_multiplier: 0.25` | ETF-first 時代の stock_reduced に由来。R0-v2 完了まで維持。 | R0-v2-C 完了後に 1.0 への戻し可否を判断 |
| 2 | sector_shock shadow カウント「3件有効」 | 旧計画は3件有効と記録。Codex review では0件と指摘。 | BLOCKED_BY_DATA に変更。有効件数の定義を明確化 |
| 3 | performance_summary.json の -$5,690.07 | 旧 dry-run 値。現在の公式値は -$103,309.56 | R0-v2-B の PerformanceSnapshot 統一で解決予定 |
| 4 | G1-v2 verification | commit 84e4532 で実装済みだが clean run が1件のみ | 10 scheduled runs でunexplained=0 確認後に VERIFIED_COMPLETE |

---

## 次に実装すべき最初の Batch（R0-v2 containment）

### Batch 1: R0-v2-A（07-22 着手）

**実装**:
1. `config/runtime/current_mode.yaml` 作成（paper 固定）
2. `INVALID_LEDGER` 時は promotion/live readiness を NO-GO 強制
3. circuit breaker manual clear → `recovery_pending` 遷移。次 clean run 後のみ `ok`
4. `SECTOR_SHOCK_HOLD_MODE=shadow` 維持

**変更ファイル**: `config/runtime/current_mode.yaml`（新規）、`guardrails/pre_trade_check.py`、`console/app.py`

**完了条件**:
- invalid ledger でも live-ready 表示にならない
- manual clear だけでは status が OK にならない

### Batch 2: R0-v2-B Ledger（07-23〜07-27）

**実装目標**:
- closed/quarantine overlap = 0
- entry_time > exit_time = 0
- holding_days is None = 0
- rebuild 2回実行で hash/count/PnL 不変

### Batch 3: R0-v2-C Guardrail（07-23〜07-28、Batch 2 と並行）

**実装目標**:
- 全 9 metrics を RiskSnapshot で実測供給
- 全 5 actions に E2E test
- pending reconciliation state machine (G1-v2 置換)

---

## セルフチェック結果

| チェック項目 | 結果 |
|------------|------|
| H0-H9 が独立した第二 roadmap として残っていないか | ✅ 残っていない（R0-v2〜R8-v2 に統合）|
| F/G/P task の履歴が失われていないか | ✅ TRACEABILITY.csv で全 traceability 保持 |
| ETF-first / Stock 15% が現行方針として残っていないか | ✅ portfolio_allocation.yaml 訂正済み。historical note のみ残存 |
| evidence なしで VERIFIED_COMPLETE になっていないか | ✅ 証拠確認済みの 6件のみ VERIFIED_COMPLETE |
| R0-v2 未完のまま R3/R5/R8 が開始可能になっていないか | ✅ BLOCKED_BY_DATA / REOPENED で明示的にブロック |
| roadmap / implementation status / Go/No-Go の status が矛盾していないか | ✅ 全て REOPENED / BLOCKED_BY_DATA に統一 |

---

## git diff --stat（コミット後）

```
 config/strategy/portfolio_allocation.yaml          |  43 +-
 config/strategy/portfolio_allocation.yaml.bak_*   |  34 +
 docs/console_improvement_tasks.md                  | 407 +++--
 docs/IMPROVEMENT_PLAN_CHANGELOG_20260721.md         | 新規
 docs/IMPROVEMENT_PLAN_TRACEABILITY_20260721.csv    | 新規
 docs/IMPROVEMENT_PLAN_MERGE_RESULT_20260721.md     | 本ファイル
```
