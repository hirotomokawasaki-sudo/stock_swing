# Go/No-Go 判定結果 — 2026-08-21 12:11 JST

> ⚠️ **記録訂正ノート（2026-08-21 12:17 JST追記）**: この判定は
> `reports/console/latest_console_summary.json`（最新スナップショット）を参照する仕様だが、
> このスナップショットは **2026-08-20 19:55:29 UTC時点（consecutive_losing_trades
> 発火直後）のもの** で、以降更新されていなかった。実際の
> `data/guardrails/circuit_breaker.json` は同日 02:58:03 UTC（JST 11:58）に
> 手動クリア済み（`status: ok`）であり、この判定実施時点（12:11 JST）では
> **実際にはcircuit_breaker/guardrail_hard_haltはすでに解消済みだった**。
> つまり以下の「🔴 NO-GO」判定は **古いスナップショットに基づく見かけの失敗**であり、
> 09-15のGo/No-Go最終判断としての位置づけではなく、単なる動作確認の副産物として
> 保存されたもの。次回の`paper_demo`実行（本日13:25 UTC以降予定）でスナップショットが
> 再生成されれば、circuit_breaker/guardrail_hard_haltは正しく✅に戻る見込み。
> 参考値セクション（R5-v2 Promotion Gate）はスナップショット日時に依存しない別項目の
> 実測値なのでこの訂正の影響を受けない（下記参照）。

## 最終判定: 🔴 **NO-GO**（▲上記ノート参照、実際は解消済みの可能性高）

## Required 条件チェック

| 条件 | 判定 | 実測値 | 必要値 |
|------|------|--------|--------|
| ledger_quality_gate | ✅ | VALID | VALID |
| circuit_breaker | ❌ | degraded | ok |
| broker_tracker_mismatch (real, lag-excused) | ✅ | 0 | 0 |
| attribution_coverage_pct | ✅ | 98.8% | >=95% |
| guardrail_hard_halt | ❌ | degraded | ok or recovery_pending |
| cron_jobs_healthy | ✅ | OK | OK |
| paper_3day_confirmation | ✅ | 07-28 ok / 07-29 ok / 07-30 ok | 3日間正常稼働 |

**判定時刻**: 2026-08-21 12:11:52 JST
**全件 Pass**: False

## 補足: R5-v2 Promotion Gate（参考情報、Required判定には含まれない）

| 条件 | 判定 | 実測値 | 必要値 | 詳細 |
|------|------|--------|--------|------|
| cluster_cap | ✅ | none over cap | no cluster over cap |  |
| top5_concentration | ❌ | 50.2% | <=40% |  |
| portfolio_beta | ✅ | 0.773 | <=1.5 |  |
| clean_cohort_pf | ❌ | 0.913 | >=1.0 (n>=20) | n=252 |
| pairwise_correlation | ❌ | ['ASML/LRCX=0.8216', 'LRCX/MU=0.8567', 'MSFT/TSLA=0.9962', 'NOW/PATH=0.814'] | no pair with |correlation|>=0.8 | checked 55 pair(s) |

## ブロック項目
- ❌ circuit_breaker
- ❌ guardrail_hard_halt
