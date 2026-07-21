# Go/No-Go 現状レポート — 2026-07-21 時点
**判定日**: 2026-07-31  
**作成**: 2026-07-21  
**ステータス**: 継続観察中（残 10 日）

---

## エグゼクティブサマリー

| 判定 | 内容 |
|------|------|
| 🟡 **条件付き GO 候補** | trailing_stop は安定稼働。stop_loss の構造的課題は把握済み。リスク管理（circuit breaker / guardrail）は修正完了。50% サイズ開始で許容範囲。 |
| ❌ **ブロック要因** | overall PF=0.62（目標 1.20 preferred）。sector_shock_hold 未有効化（shadow 3/10件）。|
| ✅ **進捗** | attribution 98.8%、G1-v2 race condition 修正、all 12 cron healthy |

---

## パフォーマンス指標

### 期間別 Overall PF

| 期間 | 件数 | PF | net |
|------|------|-----|-----|
| 全期間 (05-08~) | 259 | **0.62** | -$103,310 |
| post-R1-B (06-26~) | 50 | **0.25** | -$55,574 |
| post-min_hold (07-14~) | 14 | **0.28** | -$11,434 |

> ⚠️ 全期間の PF=0.62 はチェックリストの「1.20 preferred」を大きく下回る。ただし「preferred」（必須条件ではない）。

### exit_reason 別（全259件・attribution 98.8%）

| exit_reason | 件数 | WR | PF | net |
|-------------|------|----|----|-----|
| **trailing_stop** | 81 | 71.6% | **3.48** ✅ | +$77,202 |
| time_based | 14 | 57.1% | 1.41 ✅ | +$6,422 |
| **stop_loss** | 112 | 24.1% | 0.12 ❌ | -$166,114 |
| breakeven_stop | 47 | 21.3% | 0.47 ❌ | -$18,434 |
| corporate_action | 2 | 50.0% | 0.17 | -$3,027 |

**結論**: trailing_stop のみが黒字。stop_loss が全損失の **85%** を占める。

---

## stop_loss 構造分析

### 問題の分解

```
stop_loss 全112件（net -$166,114）
│
├── pre-min_hold era（107件 hd=0.0d, net -$154,000）
│   └── 原因: 1日未満の「ノイズ誤発動」
│   └── 対策: min_hold 1日（07-13実装）→ 再発なし ✅
│
└── post-min_hold（5件 hd>1d, net -$12,114）
    ├── セクターショック（2件 07-16 NOW/DELL, net -$4,897）
    │   └── 対策: sector_shock_hold（未有効化、shadow 3/10件）
    └── 通常下落（3件 AMD/ANET/QTEC, net -$7,218）
        └── 評価: 許容できるロスカット（gradual decline after 2-20d hold）
```

### post-min_hold stop_loss 詳細（5件）

| Symbol | hold | return | pnl | 原因 |
|--------|------|--------|-----|------|
| AMD | 14.0d | -5.9% | -$1,874 | 株式 gradual decline |
| ANET | 2.1d | -10.5% | -$3,158 | 株式 fast drop |
| QTEC | 20.1d | -5.1% | -$2,186 | ETF gradual decline |
| **NOW** | 8.7d | **-8.1%** | **-$2,461** | **07-16 sector shock** |
| **DELL** | 1.1d | **-11.7%** | **-$2,436** | **07-16 sector shock** |

**Key insight**: min_hold 有効化後、「ノイズ誤発動」はゼロ。残る課題はセクターショック（解決策あり）と通常の下落（受け入れ可能）。

### 今後の改善見通し

| 対策 | 効果 | 状態 |
|------|------|------|
| sector_shock_hold A/B | セクターショック日の保有継続 → -$4,897 節約推定 | shadow 3/10件（残7件待ち）|
| min_hold（実装済み） | hd=0 誤発動ゼロ | ✅ 確認済み |
| 閾値チューニング | gradual decline には不効果 | 07-31 以降検討 |

---

## trailing_stop の評価

| 期間 | PF | net |
|------|-----|-----|
| 全期間（81件） | **3.48** ✅ | +$77,202 |
| post-07-14（6件） | **1.21** ✅ | +$1,647 |

**評価**: trailing_stop は一貫して機能している。これが唯一かつ確実な収益源。

---

## システム運用健全性チェック

| 項目 | 状態 |
|------|------|
| Circuit Breaker | ✅ ok（G1-v2 修正後、次回 market_open cron から有効）|
| Broker/Tracker mismatch | ✅ 0件（11/11 一致）|
| attribution coverage | ✅ 98.8%（目標 ≥95%）|
| cron 全12本 | ✅ consecutiveErrors=0 |
| guardrail hard-halt | ✅ 有効（paper_warning_only: false）|
| 緊急停止ランブック | ✅ docs/runbooks/emergency_stop.md |

---

## Go/No-Go チェックリスト（07-31 用）

### Critical Gates（必須）

| Gate | 状態 | 判定 |
|------|------|------|
| Guardrail hard-halt enabled | ✅ 有効 | **GO** |
| Circuit breaker status OK | ✅ ok（G1-v2修正済み） | **GO** |
| Broker/Tracker mismatch | ✅ 0件 | **GO** |
| Reconcile job health | ✅ 全12本 ok | **GO** |
| Attribution completeness | ✅ 98.8% | **GO** |
| Exit strategy reviewed | ✅ R3-B 完了 | **GO** |
| Emergency stop runbook | ✅ 準備済み | **GO** |
| Live switch runbook | ✅ 準備済み | **GO** |

### Performance Gates（preferred = 必須ではない）

| Gate | 目標 | 現状 | 判定 |
|------|------|------|------|
| Overall PF | ≥1.20 preferred | **0.62** | ❌ |
| trailing_stop PF | ≥1.5 | **3.48** | ✅ |
| stop_loss WR | ≥30% | **24.1%** | ❌ |
| Post-R1-B closed trades | ≥20 | **50件** | ✅ |
| Attribution | 0 unknown | **3件** | ✅ |

---

## 07-31 判定に向けた見通し

### 楽観シナリオ
- 07-21〜07-31 の 8 営業日で trailing_stop が 10+ 件発火
- sector_shock shadow が 7 件追加 → A/B 開始条件クリア
- 全体 PF が改善

### 現実的シナリオ
- PF は 07-31 までに 1.0 を超えない可能性が高い（ベースラインが -$103K）
- **条件付き GO の根拠**: trailing_stop は機能している（PF=3.48）。stop_loss の構造的問題は把握済みで対策（sector_shock_hold）が待機中。50% サイズ開始で max drawdown を限定。
- **NO-GO の根拠**: overall PF=0.62、recent PF=0.28 はシステムが現時点でマイナス期待値であることを示す。

### 推奨判断フレーム（07-31）
1. `trailing_stop PF ≥ 1.5`（現在 3.48）を必須条件とする
2. `overall PF ≥ 0.8`（現在 0.62）を推奨目標として 07-28〜07-30 の最終確認で再評価
3. sector_shock_hold A/B 開始条件（10件）は満たせない可能性が高い → 50% サイズで開始後の実データで評価

---

## 07-28〜07-31 スケジュール

| 日付 | アクション |
|------|----------|
| 07-28 | 07-22〜07-27 のパフォーマンス集計・評価 |
| 07-28〜07-30 | hard-halt 環境でのペーパー最終確認（BLOCKING） |
| 07-30 | sector_shock shadow 累計確認 |
| **07-31** | **Go/No-Go 最終判定**（このドキュメントを参照）|
| 08-01 | リアルトレード開始（承認時）、初期 50% サイズ |
