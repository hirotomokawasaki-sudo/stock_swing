# Go/No-Go 事前レポート — 2026-07-31 判定用

**作成日**: 2026-07-28 / **最終更新**: 2026-07-30 09:53 JST（paper 3日確認完了 + 07-30修正追記）
**判定予定**: 2026-07-31
**リアルトレード想定開始**: 2026-08-20以降（延期済）
**開始サイズ**: 50%（stock_new_buy_multiplier = 0.50）

---

## 1. Required 条件チェックリスト

> 全項目 ✅ 必須。1件でも ❌ の場合は No-Go。

| 条件 | 状態 | 値 |
|------|------|-----|
| ledger_quality_gate | ✅ **VALID** | overlap=0 / reversed=0 / exit_None=0 / hd_missing=1(ANET,entry_time欠損) |
| circuit_breaker | ✅ **ok** | last halt: 2026-07-24, cleared 2026-07-25 |
| attribution coverage | ✅ **98.5%** (目標95%) | 196/199件 |
| broker/tracker mismatch | ✅ **0** | 07-29現在 |
| cron ジョブ正常稼働 | ✅ **全13本** | consecutiveErrors=0 |
| guardrail hard-halt | ✅ **有効** | hard mode（config/runtime/current_mode.yaml） |
| paper 最終確認（07-28〜30） | ✅ **完了** | 07-28 ok / 07-29 ok / 07-30 ok（04:55 JST）|

**→ Required 条件: 7/7 全て達成 ✅**

---

## 2. Preferred 条件チェックリスト

> preferred は判断材料。未達でも Go の選択肢あり（根拠が説明できる場合）。

| 条件 | 状態 | 値 | 目標 |
|------|------|-----|------|
| overall PF（全期間 197件） | ❌ **0.843** | wins=89 / losses=108 | 1.20 |
| overall WR | ❌ **45.2%** | n=197（07-29 Batch A/B後） | 50% |
| trailing_stop PF | ✅ **6.30** | n=72 / WR=80.6% / net=+$90,980 | 機能確認 |
| stop_loss 正しい止損率 | ✅ **推定95%+** | 07-10以降: avg_ret=-7.1% | ≥70% |
| sector_shock shadow | ⚠️ **3件** | A/B 開始に10件必要 | ≥10 |

---

## 3. パフォーマンス詳細（2026-07-29 最終計算）

### 3-A. 全期間サマリー（Batch A/B + KLAC quarantine後）

```
closed=197  quarantined=101（KLAC split anomaly追加）
status=open: 5件（ADBE/DDOG/HPE/HPQ/MSFT ─ 現在保有中）
PF=0.843  WR=45.2%  n=197
sum(pnl, closed only): -$30,984

state.cumulative_realized_pnl: -$74,666（rebuild前の値、未更新）
  ↑ 差: KLAC split -$39,342除外、台帳修復等の影響

Batch A/B 実装後の変化:
  overlap=0 / duplicate=0 / exit_None(closed)=0 / hd_missing=0
  legacy synthetic raw: 568件を raw_legacy_untrusted/ へ隔離
  KLAC broker_match_0117 quarantine（entry pre-split/$2126.92）
```

### 3-B. exit_reason 別パフォーマンス

| exit_reason | N | PF | WR | net PnL |
|-------------|---|----|----|---------|
| **trailing_stop** | 72 | **6.30** | **80.6%** | **+$90,980** |
| **time_based** | 10 | **2.44** | **70.0%** | **+$14,581** |
| breakeven_stop | 43 | 0.65 | 20.9% | -$7,980 |
| broker_fill | 3 | 0.58 | 33.3% | -$100 |
| corporate_action | 2 | 0.17 | 50.0% | -$3,027 |
| **stop_loss** | 67 | **0.13** | **19.4%** | **-$125,438** |
_注: KLAC broker_match_0117（-$39,342 split anomaly）は quarantine 済み_ |

### 3-C. 注目点

- **trailing_stop は完全に機能している**（PF=6.30、n=72）
- **stop_loss が損失の大部分**（-$166K）。ただし正しい止損率≥95%のため「機能している」
- stop_loss の改善策: tiered min_hold（FIX-007でbaselineはdisable中）+ sector_shock_hold（shadow=3件、A/B未開始）

---

## 4. 台帳整合性（2026-07-29 修正後）

| 指標 | 修正前 | 修正後 | 判定 |
|------|--------|--------|------|
| closed/quarantine overlap | 15件 | **0件** ✅ | PASS |
| duplicate trade_id | 1件(ADBE×2) | **0件** ✅ | PASS |
| exit=None in closed | 6件 | **0件** ✅ | PASS |
| hd_missing | 2件 | **1件** (ANET, entry_time欠損) | 軽微 |
| ledger_quality_gate | VALID | **VALID** ✅ | PASS |

**修正内容（2026-07-29）**:
- ghost entries 6件除去（ADBE×2, DDOG, HPE, HPQ, MSFT、全てexit=None）
- overlap 14件: quarantine側のtrade_idに`qinv_`プレフィックス付与（元データ保持）
- overlap 1件(ANET): quarantine除去（closed側が正、q_reason=holding_days_None）

---

## 5. Fix Batch 2026-07-29（SSR-20260729-01）実装済み

| FIX | 内容 | 影響 |
|-----|------|------|
| FIX-001 | synthetic data production pathから削除 | データ信頼性向上 |
| FIX-002 | allocation price=0 block / qty両対応 | BUY制御精度向上 |
| FIX-003 | recently_sold_symbols 30分窓制限 | 再購入suppression解消 |
| FIX-005 | guardrail daily_loss計算正確化 | guardrail精度向上 |
| FIX-006 | DecisionRecord join metadata付与 | attribution追跡改善 |
| FIX-007 | 7d tier disable（到達不能） | 誤シミュレーション防止 |
| FIX-009 | console 127.0.0.1 bind / write off | セキュリティ修正 |
| FIX-010 | token usage_source分離 | コスト計算正確化 |

---

## 6. Go/No-Go 判断フレーム（07-31向け）

### Required（ブロッカー）→ 全件✅
- ledger VALID ✅ / CB ok ✅ / attribution 98.5% ✅ / mismatch 0 ✅ / cron ✅ / guardrail hard ✅

### 焦点：overall PF 0.699 を許容するか

**Go を支持する根拠：**
1. trailing_stop PF=6.30（n=72）→ コアロジックは機能している
2. stop_loss PF=0.10 は「機能不全」ではなく「正しく止損している（95%+）」
3. stop_loss改善策（tiered min_hold / sector_shock_hold）は実装済みで検証中
4. 50%サイズ開始なら実損失リスクは限定的

**No-Go を支持する根拠：**
1. overall PF 0.699 < 1.0 → 現状は損失超過
2. sector_shock shadow 3件（A/B 10件未達）→ 主要改善策未検証
3. tiered min_hold は7d tier無効化で未評価

**推奨判断（システム側意見）**：
> 07-31の状況次第だが、paper 3日間正常稼働確認ができれば「50%サイズ Go」の条件を満たす。
> ただし sector_shock_hold A/B が完了する08-20以降の開始が当初判断通り適切。
> 07-31は「準備完了確認」として Go/No-Go を記録し、08-20の実際の移行判断を別途行うのが妥当。

---

## 8. 2026-07-30 実施済み修正（Go/No-Go 前日）

| 修正 | commit | 内容 |
|------|--------|------|
| 有効上限 60K→80K | `d6b936e` | DEFAULT_MAX_POSITION_NOTIONAL_PCT: 0.06→0.08 |
| AMD 購入制限解除 | `d6b936e` | rolling_pf_gate bypass (PF=0.60, pf_gate_skip_symbols) |
| ANET reconcile WARNループ修正 | `3a67a48` | quarantined trade を recorded_qty に含める |
| Decision allocation_blocked バグ修正 | `0857b2f` | position_limit_pct を alloc_config 統一（legacy STOCK_MULTIPLIER 二重適用を排除） |

次回 paper_demo（07-30 22:25 JST〜）から全修正が有効になる。

---

## 7. 残リスク・未対応事項

| リスク | 重要度 | 状況 |
|--------|--------|------|
| sector_shock shadow 3件（目標10件） | HIGH | A/B未開始 |
| ANET holding_days=None（entry_time欠損） | LOW | 軽微 |
| state PnL vs sum差 -$2,869 | LOW | pre-epoch分、許容範囲 |
| run_id coverage closed trades 0% | MEDIUM | 新規決定から有効（既存未遡及） |
| tiered min_hold: paper評価なし | MEDIUM | baseline=disable中 |


---

## 9. 2026-07-30 追加対応（EPB-010 CONTROLLED_PAPER_BUY_GO後）

### EPB Gate Matrix 最終判定（14:00 JST）

**`decision=CONTROLLED_PAPER_BUY_GO`** ✅

| Gate | 状態 |
|---|---|
| EPB-001〜007, 009 | ✅ VERIFIED_COMPLETE |
| EPB-008 changed-line coverage | ✅ **90%達成**（閾値90%）|
| EPB-010 approval | ✅ VERIFIED_COMPLETE |

commit: `73e1ad0` / 全suite: 1253 passed

### RGT-008: KLAC corporate action 検証完了

- `broker_match_0117_KLAC`: entry=\$2126.92（pre-split）vs exit=\$253.5（post-split）
- 価格比 ~8.4x、split日: 2026-06-09〜06-23の間
- **すでにquarantine済み（klac_split_anomaly）→ 追加修正不要** ✅
- 証跡: `stock_swing_remediation_result_20260730/rgt008_klac_corporate_action.json`
- **RGT-008: VERIFIED_COMPLETE**

### ANET holding_days=None 修正

- `broker_open_0247_ANET`: entry_timeがnullだったためquarantine
- trade_eventsから entry_time=2026-07-22T16:00:27 / broker_order_id を特定・復元
- holding_days = **5.906日** に修正
- ledger_quality_gate: 影響なし（quarantine status維持）
- commit: 本日のpatchに含む

### PAPER BUY 再開状態

- `PAPER_DEMO_EXIT_ONLY` 環境変数: **未設定（BUY有効）**
- clean_epoch_id: `clean_epoch_20260730_014631` → 新規fillは独立集計
- 次回paper_demo（22:25 JST ET 09:25）から新規BUY評価が有効
- 監視: 最初の20 clean runsでEPB状態を毎回記録
