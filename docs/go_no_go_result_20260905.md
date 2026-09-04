# Go/No-Go 判定結果 — 2026-09-05 04:18 JST

## 最終判定: 🔴 **NO-GO**

## Required 条件チェック

| 条件 | 判定 | 実測値 | 必要値 |
|------|------|--------|--------|
| console_summary_freshness | ✅ | 3.31h old | <=30h old |
| console_summary_not_dry_run | ✅ | dry_run=False (invocation_source=paper_demo_scheduled) | dry_run=False (real scheduled/manual paper run) |
| ledger_quality_gate | ✅ | VALID | VALID |
| circuit_breaker | ✅ | ok | ok |
| broker_tracker_mismatch (real, lag-excused) | ✅ | 0 | 0 |
| attribution_coverage_pct | ✅ | 96.4% | >=95% |
| guardrail_hard_halt | ✅ | ok | ok or recovery_pending |
| cron_jobs_healthy | ✅ | 34/34 jobs parsed (0 parse error(s), 0 job(s) with lastRunStatus=error or consecutiveErrors>0) | all enabled cron jobs parse cleanly (openclaw cron list/runs) |
| paper_3day_confirmation | ✅ | 5 distinct day(s) with a real paper_demo run (decisions_generated>0) in the last 7 days: ['2026-08-31', '2026-09-01', '2026-09-02', '2026-09-03', '2026-09-04'] | >=3 distinct days with a real scheduled paper_demo run (decisions_generated>0) in the last 7 days |
| economic_viability | ❌ | n=45, PF=0.530, expectancy=$-551.33 (cohort exit_time>=2026-08-14) | n>=30 & PF>1.0 & expectancy>0 |

**判定時刻**: 2026-09-05 04:18:45 JST
**全件 Pass**: False

## 経済性ゲート詳細: economic_viability（2026-09-05追加、Required判定に含まれる）

| 項目 | 値 |
|------|------|
| コホート | closed trades, exit_time >= 2026-08-14 |
| n | 45（必要: >=30、未満は insufficient_sample として fail-closed） |
| 粗利益 | $+28,000.97 |
| 粗損失 | $-52,810.85 |
| PF（粗利益/\|粗損失\|） | 0.530（必要: >1.0） |
| expectancy（1トレード平均PnL） | $-551.33（必要: >0） |
| insufficient_sample | False |

注: このゲートは意図的なfail-closed設計。PF<=1.0 の間は他のRequired条件が
全緑でも NO-GO を維持する（2026-09-05 ユーザー承認済み。閾値の緩和は不可）。

## 補足: R5-v2 Promotion Gate（参考情報、Required判定には含まれない）

| 条件 | 判定 | 実測値 | 必要値 | 詳細 |
|------|------|--------|--------|------|
| cluster_cap | ✅ | none over cap | no cluster over cap |  |
| top5_concentration | ✅ | 14.1% of equity | <=40% of equity | gross_basis=100.0%, gross_exposure/equity=14.1%, hhi=0.3262 |
| portfolio_beta | ✅ | 0.814 | <=1.5 |  |
| clean_cohort_pf | ✅ | 1.073 | >=1.0 (n>=20) | n=49 |
| pairwise_correlation | ✅ | none | no pair with |correlation|>=0.8 | checked 3 pair(s) |

## ブロック項目
- ❌ economic_viability