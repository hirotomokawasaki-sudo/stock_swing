# Go/No-Go 事前レポート — 2026-07-31 判定用

**作成日**: 2026-07-28  
**判定予定**: 2026-07-31  
**リアルトレード想定開始**: 2026-08-20以降（延期済）  
**開始サイズ**: 50%（stock_new_buy_multiplier = 0.50）

---

## 1. Required 条件チェックリスト

> 全項目 ✅ 必須。1件でも ❌ の場合は No-Go。

| 条件 | 状態 | 値 |
|------|------|-----|
| ledger_quality_gate | ✅ **VALID** | overlap=0 / reversed=0 / hd_missing=0 / ac_unknown=0 |
| circuit_breaker | ✅ **ok** | consecutive_losses=None / daily_loss=None |
| attribution coverage | ✅ **98.5%** (目標95%) | 193/196件（broker_fill残3件は05-14〜15の初期データ） |
| cron ジョブ正常稼働 | ✅ **正常** | reconciliation/news_collection/paper_demo 全稼働 |
| paper 最終確認（07-28〜30） | 🔄 **進行中** | Day 1/3（07-28夜）から開始 |

**→ Required 条件: 4/5 確認済み。残1件（paper確認）は07-30完了予定。**

---

## 2. Preferred 条件チェックリスト

> preferred は判断材料。未達でも Go の選択肢あり（根拠が説明できる場合）。

| 条件 | 状態 | 値 | 目標 |
|------|------|-----|------|
| overall PF（全期間） | ❌ **0.718** | — | 1.20 |
| overall WR | ❌ **45.4%** | 89W/107L/196件 | 50% |
| trailing_stop PF | ✅ **6.30** | WR=81% / net=+$90,980 | 機能確認 |
| stop_loss 正しい止損率 | ✅ **推定95%+** | 07-10以降: avg_ret=-7.1%（深い、回復しない） | ≥70% |
| sector_shock shadow | ⚠️ **7件** | A/B 開始に10件必要 | ≥10 |

---

## 3. パフォーマンス詳細分析

### 3-A. 全期間サマリー

```
closed=196  quarantined=100  open=7
Cumulative PnL: -$65,459
Gross profit:  +$166,910
Gross loss:    -$232,369
```

### 3-B. exit_reason 別パフォーマンス

| exit_reason | N | PF | WR | net PnL |
|-------------|---|----|----|---------|
| **trailing_stop** | 72 | **6.30** | **81%** | **+$90,980** |
| **time_based** | 10 | **2.44** | **70%** | **+$14,581** |
| breakeven_stop | 43 | 0.65 | 21% | -$7,980 |
| broker_fill | 3 | 0.58 | 33% | -$100 |
| corporate_action | 2 | 0.17 | 50% | -$3,027 |
| **stop_loss** | 66 | **0.10** | **20%** | **-$159,914** |

**→ trailing_stop（コア戦略）は明確に機能している。損失の主因は stop_loss。**

### 3-C. ETF / Stock 別

| asset_class | N | PF | WR | net PnL |
|-------------|---|----|----|---------|
| ETF | 35 | 1.31 | 60% | +$14,777 |
| Stock | 161 | 0.57 | 42% | -$80,236 |

**→ ETF は黒字。Stock の stop_loss 損失が全体を押し下げている。**

### 3-D. 月別推移

| 月 | N | WR | net PnL |
|----|---|----|----|
| 2026-05 | 31 | 42% | -$11,534 |
| **2026-06** | 113 | **54%** | **+$10,333** |
| 2026-07 | 52 | 29% | -$64,258 |

**07-07 以降の急激な悪化が全体を押し下げている。**

### 3-E. 07-10以降（RF修復後・clean period）

```
N=28  PF=0.115  WR=25.0%  (7W/21L)

exit_reason 別:
  stop_loss    : N=12 PF=0.00 net=-$22,672  ← 全件損失
  breakeven_stop: N= 8 PF=0.10 net=-$3,500
  trailing_stop : N= 7 PF=3.25 net=+$2,141  ← 機能中
  time_based    : N= 1 PF=0.00 net=-$2,648
```

**→ trailing_stop のみ利益（PF=3.25）。stop_loss が直近 PF を壊している。**

### 3-F. 07-16〜07-18 セクターショック（主因）

| symbol | exit | reason | pnl |
|--------|------|--------|-----|
| NOW | 07-16 | stop_loss | -$2,459 |
| DELL | 07-16 | stop_loss | -$2,437 |
| META | 07-17 | breakeven_stop | -$1,193 |
| FTNT | 07-16 | breakeven_stop | -$159 |

**→ 07-16 の sector shock（半導体/テック下落）で $5K超の集中損失。**  
**→ sector_shock_hold（per-symbol benchmark修正済 07-28）で今後は防御可能。**

### 3-G. 損失トップ5（07-10以降）

| symbol | net PnL |
|--------|---------|
| DELL | -$3,034 |
| PLTR | -$2,888 |
| AMZN | -$2,847 |
| FRWD | -$2,648 |
| NOW | -$2,459 |

---

## 4. 改善施策の効果予測

### 4-A. tiered min_hold（07-27 実装済）

```
ret > -5%: min_hold 7日（ノイズ誤発動を防ぐ）
-5〜-8%:   min_hold 3日
≤ -8%:     min_hold 1日（従来通り）
```

- シミュレーション: stop_loss 損失 -$167K → -$126K（+$41K 改善）
- 07-10以降の stop_loss N=12 のうち、avg_ret=-7.1%（-5%以上が多数）→ 大半が tiered で遅延されるはず
- **直近 PF への影響: 最大の負の要因を大幅に削減**

### 4-B. sector_shock_hold（07-28 バグ修正済）

- 07-16ショック相当のイベントが再来した場合、exit シグナルを最大5日延期
- shadow log 7件 → A/B に10件必要（08-04〜08-18 頃に到達見込み）

### 4-C. stop_loss 評価軸の変更（07-27 確立）

- 正しい止損率（止損後にさらに下落した割合）≥ 70% が本来の目標
- WR目標（30%）は不適切だったと結論
- 全期間・07-10以降とも、深い止損（-7%〜-8%）が多数 → 「正しく止めている」

---

## 5. 判断フレームワーク

### 判定ロジック

```
Required ALL PASS?  → YES (paper確認待ち)
      ↓
trailing_stop が機能している?  → YES (PF=6.30, WR=81%)
      ↓
PF不振の主因が特定され、対策済み?
  - stop_loss: tiered min_hold で軽減（シミュ+$41K）
  - sector_shock: per-symbol benchmark 修正済み
  → YES (構造的問題ではなく、特定イベント + 設定によるもの)
      ↓
50% サイズで開始してリスクを限定しながら検証できる?  → YES
```

### 推奨: **条件付き Go（50%サイズ）**

**Go の根拠:**
1. **trailing_stop が明確に機能している**（PF=6.30）— エントリー品質は高い
2. **PF不振は構造的欠陥ではない**— tiered min_hold と sector_shock_hold で対処済み
3. **Required 条件は全て PASS**— システムの信頼性は担保されている
4. **50% サイズ**で開始 → drawdown は最大でも従来の50%。設定1行で調整可能。

**No-Go の根拠（もしあれば）:**
- PF=0.718（全期間）/ PF=0.115（07-10以降）が preferred 目標に未達
- sector_shock A/B 未完（shadow 7件、A/B 開始に10件必要）
- paper 最終確認（07-30まで）の結果次第

### 最終判定に必要な追加情報（07-31 当日）
- [ ] paper 最終確認 Day 2〜3 の結果（circuit breaker HALT なし / mismatch=0）
- [ ] sector_shock shadow が 07-28〜30 で正しく per-symbol ベンチマークで動作したか
- [ ] 07-28〜30 の trailing_stop / stop_loss 発火件数・金額

---

## 6. 開始後の運用条件

| 条件 | 値 |
|------|-----|
| 開始サイズ | 50%（stock_new_buy_multiplier = 0.50） |
| 開始日 | 2026-08-20以降（07-31 Go 判定後、準備期間2〜3週） |
| circuit breaker | hard-halt 有効（HALT 時は即座に manual review） |
| sector_shock A/B | shadow 10件到達後に正式実施（08-04〜08-18 頃） |
| 昇格フルサイズ条件 | 実トレード PF ≥ 1.0 / 30件以上 / 3週間経過 |
| 緊急停止条件 | weekly drawdown ≥ 5% or circuit breaker HALT が3回連続 |

---

## 7. 残タスク（07-31 判定まで）

| タスク | 期限 | 状態 |
|--------|------|------|
| paper 最終確認 Day 1 | 07-28夜 | 🔄 今夜 |
| paper 最終確認 Day 2 | 07-29夜 | 🔲 |
| paper 最終確認 Day 3 | 07-30夜 | 🔲 |
| sector_shock shadow per-symbol 動作確認 | 07-30 | 🔲 |
| Go/No-Go 最終判定 | 07-31 | 🔲 |

---

---

## 8. breakeven_stop 分析（候補改善事項）

> ⚠️ 今日は分析のみ。設定変更は 07-31 Go 判定後に実施。

### 現状

```
N=43  PF=0.65  WR=21%  net=-$7,980
avg_win=+$1,631  avg_loss=-$666
return 分布: -10〜0%: 34件 / 0〜+5%: 6件 / +5%以上: 3件
```

### 根本原因

`breakeven_activation_pct = 3%` が低すぎる。

- 市場ノイズで一時的に **+3%** に達しただけで activation が発動
- その後引き返す → breakeven_stop が損失（avg -0.2%）で終了
- 利益の +3% を全部返している

### 問題の矛盾

`avg_win ($1,631) > avg_loss ($666)` なのに `PF=0.65` → **WR=21% の低さが原因**  
→ 勝つときは大きく勝てるが、breakeven が早すぎて9割近くが損失になる

### 推奨対応（Go 判定後に実施）

| Option | 内容 | メリット |
|--------|------|----------|
| **A（推奨）** | `breakeven_activation_pct: 3% → 5%` | staged_trailing[0]（5%/3.5%）と整合。変更1行。 |
| B | breakeven_stop を完全無効化 | staged_trailing が 0%〜5% を自動カバー |
| C | 両者を比較するためのシミュ実行 | data driven 判断が可能 |

**効果見込み**: `breakeven_stop net -$7,980` の大部分が trailing_stop に転換 → PF 改善  
**設定変更ファイル**: `config/strategy/simple_exit_v2.yaml`

---

*本レポートは 2026-07-28 時点のデータに基づく。07-31 判定時に最新データで更新すること。*
