# R3-B: Exit Replay 評価レポート

**実施日**: 2026-07-02  
**対象**: 227 closed trades（全期間）  
**ツール**: `scripts/compare_exit_variants.py`  
**成果物**: `artifacts/exit_variant_comparison.json`

---

## 結果サマリー

| Variant | Win% | Total PnL | Δ vs Baseline | PF |
|---|---|---|---|---|
| **A: baseline（現行）** | 55.1% | $31,876 | — | 1.21 |
| B: +break_even（+4%起動） | 52.4% | $27,581 | **-$4,295** | 1.18 |
| C: +stalled_winner（積極）| 47.1% | -$37,333 | **-$69,209** | 0.77 |
| C6: +stalled_winner（保守） | 55.1% | $30,305 | **-$1,571** | 1.20 |
| **D: +staged_trailing（推奨）** | 55.1% | $36,965 | **+$5,089** | 1.24 |

> **Note**: replay は actual exit 日を上限とする保守的な first-pass シミュレーション。
> actual PnL との差は exit タイミングの違いによるもので look-ahead ではない。

---

## 重要発見

### 1. Staged Trailing Stop (D) が最良 (+16% 改善)

```
D variant specs:
  activation 5%  → trailing 3.5%
  activation 8%  → trailing 3.0%
  activation 12% → trailing 2.5%
```

利益が大きくなるほどトレイリング幅を縮める設計が有効。現行（固定 trailing 3%）より+$5,089。

### 2. Break-Even Stop (B) は逆効果 (-13%)

ANET を例にとると:
- 実際: +$12,144（break-even 発動せず、保有継続）
- シミュレーション: +$0（+4%時点で break-even stop 発動 → ちょうど元値で切られた）

**勝ちトレードの一部を break-even 付近で切ってしまっている。現行の breakeven_stop ロジック（+3% 到達後に 0% 以下で売却）は廃止を検討。**

### 3. Stalled Winner (C) は壊滅的

47% WR, PF 0.77。「6日保有でピーク6%未満かつ現在2%未満なら売却」は過剰に早い exit を引き起こす。

### 4. 現行 (A) の主な問題は exit 戦略ではなく実行ラグ

TSM の分析でも確認の通り、discrete paper_demo 実行（1日4〜5回）では stop 条件成立後に価格が更に下落してから約定する。これはバー・バー・リプレイでは測定できない「構造的な問題」。

---

## 現在 open ポジションの要注意シグナル（全バリアント共通）

| Symbol | 現在リターン | ピーク | 保有日 | 緊急度 |
|---|---|---|---|---|
| **CHPX** | **-11.29%** | -0.29% | 6.5d | 🚨 stop_loss 水準超過 |
| **SOXX** | **-5.59%** | 1.25% | 6.5d | ⚠️ stop_loss 接近 |
| **SOXQ** | **-5.51%** | 0.97% | 6.5d | ⚠️ stop_loss 接近 |
| **FTXL** | **-6.10%** | 0.23% | 6.5d | ⚠️ stop_loss 接近 |
| **NBIS** | -6.85% | 13.08% | 6.4d | ⚠️ trailing_stop 水準（peak 13%→現在-7%） |
| **MU** | -7.26% | 5.91% | 2.5d | ⚠️ stop_loss 水準 |

> これらは本日の paper_demo 実行時に stop_loss / trailing_stop が発動する可能性が高い。

---

## 結論と推奨アクション

### 採用推奨: Variant D（staged_trailing）

```python
staged_trailing_levels=[
    {"activation_pct": 0.05, "trailing_stop_pct": 0.035},
    {"activation_pct": 0.08, "trailing_stop_pct": 0.030},
    {"activation_pct": 0.12, "trailing_stop_pct": 0.025},
]
```

改善幅は控えめ（+$5,089 / +16%）だが win rate を維持しており副作用が少ない。

### 廃止検討: Break-Even Stop

現在の `breakeven_stop` ロジックは exit_reason として記録されており、performance に悪影響。
**勝ちトレードを break-even 付近で切る**傾向が確認された。

`breakeven_activation_pct` の引き上げ（+3% → +8%）、または廃止を推奨。

### 変更しない: Stalled Winner

どちらのパラメータ設定でも baseline と同等か大幅悪化。導入しない。

---

## 次のステップ

- [ ] Variant D の staged_trailing を `simple_exit_v2_strategy.py` に実装（R3-B 完了条件）
- [ ] Break-even stop の activation 閾値を +3% → +8% に引き上げ（または廃止）
- [ ] 実行ラグ対策として paper_demo の頻度引き上げ検討（現在 4-5回/日）
- [ ] 実装後 2週間 paper で検証してから 08-01 本番適用

**R3 全体の受け入れ基準**: ✅ 「短期クローズ ≠ 損失の主因、exit 戦略の改善余地はあるが限定的。主課題は実行ラグ」と数値で結論。
