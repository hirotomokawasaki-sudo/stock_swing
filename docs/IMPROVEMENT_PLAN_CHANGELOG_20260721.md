# IMPROVEMENT_PLAN_CHANGELOG_20260721.md

**作成日**: 2026-07-21
**対象**: docs/console_improvement_tasks.md (R0-R8 → R0-v2〜R8-v2)
**作業者**: OpenClaw assistant
**commit**: see git log

---

## 変更サマリー

| カテゴリ | 変更件数 |
|----------|---------|
| Status 変更（旧 ✅完了 → REOPENED） | 5件 |
| Status 変更（旧 ✅完了 → IMPLEMENTED_UNVERIFIED） | 2件 |
| Status 変更（旧 PLANNED → BLOCKED_BY_DATA） | 2件 |
| Status 変更（旧 PLANNED → IN_PROGRESS） | 1件 |
| 新規 allocation 方針訂正 | Stock 85% / ETF 15% |
| config ファイル更新 | portfolio_allocation.yaml |

---

## 1. Stock 85% / ETF 15% 訂正

**変更**: ETF-first / stock-reduced 方針（ETF 85% / Stock 15%）→ Stock 85% / ETF 15%

**根拠**:
- ユーザー確認済みの正式方針は Stock 85% / ETF 15% 前後
- 実ポートフォリオ (07-21): Stock 90.9% / ETF 9.1% → 方針に概ね沿っており重大問題ではない
- `config/strategy/portfolio_allocation.yaml` が ETF=0.85 / Stock=0.15 と逆転していた
- Codex review P1-2 指摘

**変更ファイル**:
- `config/strategy/portfolio_allocation.yaml`: ETFs: 0.85 → stocks: 0.85, ETFs: 0.15
- `docs/console_improvement_tasks.md`: 全 allocation 記述を Stock 85% / ETF 15% へ統一

**歴史的注記**: ETF-first 方針は 2026-06-23 に ETF PF=2.776 / Stock PF=0.740 の broker データを根拠に設定。
この判断自体は当時の情報に基づくものとして git 履歴に残す。現在は Stock 85% / ETF 15% が正式。

---

## 2. Status 変更詳細

### R0 (guardrail + experiment 接続): ✅完了 → REOPENED

**根拠 (P0-3, P1-3)**:
- post_run に渡す metrics: 9 rules 中 5 metrics のみ供給
- 不足: `daily_realized_loss_pct`, `weekly_total_loss_pct`, `consecutive_losing_trades`, `token_spend_spike_pct`
- `api_error_rate_pct` = 0.0 ハードコード
- `record_submission()` に run_id / experiment_id / config_hash 未渡し
- `reduce_size` action が DecisionRecord に反映されず破棄
- `ai_pause` / `flatten_risky` の実行経路なし
- decision → trade join 成功: 0/259件

**必要な証拠 (VERIFIED_COMPLETE になるには)**:
- 全 9 configured metrics が毎 run 実測供給される
- 全 5 actions に E2E test
- 10 scheduled runs 連続で unexplained mismatch=0、false HALT=0
- decision → trade join ≥99%

### R1 (exit attribution): ✅完了 → REOPENED

**根拠 (P0-1)**:
- closed/quarantine trade_id overlap: 41件
- entry_time > exit_time (reversed chronology): 62件
- holding_days is None: 245件
- asset_class unknown: 245件
- 「quarantined は公式成績から除外済み」という PNL_RECONCILIATION の判定は実データと矛盾

**必要な証拠**:
- invalid chronology=0、missing holding_days=0、closed/quarantine overlap=0

### R2 (ETF/Stock 分離): ✅完了 → REOPENED

**根拠 (P1-2, H5)**:
- portfolio_allocation.yaml が ETF=0.85 / Stock=0.15 と逆転
- asset_class unknown in closed: 245件 → R2-A の backfill 未完または rebuild で喪失

**必要な証拠**:
- asset_class unknown=0
- config / allocator / console が同じ policy source を参照

### R3 (反実仮想検証): ✅完了(R3-A/B) → BLOCKED_BY_DATA

**根拠 (P0-4, H6)**:
- 旧 R3-B の counterfactual は sector shock stop 22件を $0 と仮定（実価格 path 未使用）
- sector_shock valid trigger: 0件（以前計上した「3件」は soft_stop / no_sector_data）
- days_held / state が session 間で persistent でない
- symbol-specific benchmark 未使用（全銘柄を SMH/SOXX と比較）
- signal_strength を return 代用として使用中 → 廃止必要

**A/B 開始条件 (新定義)**:
- historical shock replay ≥100 events
- forward valid sector_shock_hold trigger shadow ≥10
- costs 込み PF / CVaR / max drawdown で 2 指標改善

### R5 (昇格ゲート): PLANNED → REOPENED

**根拠**:
- promotion gate の入力コホートに closed/quarantine 重複 41件が含まれている
- allocation policy が逆転していた（R2-v2 で訂正）
- `data_quality=RED` でも PF/WR が通常値として表示・使用されている

### R6 (Console): C1-F/GW/LS 完了 → IMPLEMENTED_UNVERIFIED

**根拠 (P1-5, H3)**:
- non-dry-run の ConsoleSummary に `ledger_quality={}` / `entry_filter_stats` 未渡し
- `current_status` と `last_run_status` が混在表示
- manual clear 後の RECOVERY_PENDING 状態なし
- 07-21 時点: circuit breaker=OK, latest console=HALTED → 状態不一致

**必要な証拠**:
- non-dry-run で ledger_quality が正しく表示される
- manual clear 後に RECOVERY_PENDING と表示される

### R4 (signal 飽和): IMPLEMENTED_UNVERIFIED（変化なし、再確認）

**根拠**:
- R4-A/B は実装済み（min_signal_strength ≥0.40 filter）
- signal_strength=1.0 が 73% のまま（R4-B 後も saturation 継続）
- R4-C 未実施
- acceptance criteria（decile 別 PF 検証）未達

### R7 (データ品質): IN_PROGRESS（変化なし、確認）

**根拠**:
- R7-A Corporate Action 台帳 ✅
- Connection pool full 警告が発生中
- macro (FRED) は unknown のまま
- R7-B/C 未着手

### R8 (ML): PLANNED → BLOCKED_BY_DATA

**根拠 (H7)**:
- clean joinable outcomes: 0件 (need ≥300 for initial calibration)
- decision → trade join 0件（R0-v2-D 未完）

---

## 3. 旧 ETF-first 記述の扱い

以下の旧記述を historical note として保持し、現行方針として使用しない:
- `portfolio_allocation.yaml` 旧設定 → backup: `portfolio_allocation.yaml.bak_20260721`
- スケジュール概要内の ETF-first / stock-reduced 記述 → 歴史的記録セクションに残存
- G8 関連コミット（ETF-first 有効化）→ git 履歴に残す

---

## 4. 未解決 Conflict

| Conflict | 内容 | 対応方針 |
|----------|------|---------|
| stock_new_buy_multiplier 0.25 | 旧 stock-reduced の一時措置として残存。R0-v2 完了後に見直し | R0-v2-C 完了後に 1.0 へ戻すかを判断 |
| sector_shock shadow カウント | 以前「3件有効」と記録されていたが、実際は 0件 | R3-v2 BLOCKED_BY_DATA に変更済み |
| PnL -$5,690.07 vs -$103,309.56 | G3 修正後の公式値は -$103,309.56。-$5,690.07 は旧 dry-run 値 | 現在の running_oper_status は -$103,309.56 が正 |
