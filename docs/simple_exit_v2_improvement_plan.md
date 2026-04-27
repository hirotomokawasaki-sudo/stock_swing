# Simple Exit V2 改善計画

## 現状分析（simple_exit_v1）

### ✅ 強み
1. **Take Profitの勝率**: 100% (15/15)
2. **Stop Lossの機能**: 正常（損失限定）
3. **P&L比率**: 3.7:1（健全）

### ⚠️ 弱点・改善機会

#### 1. 早期利確問題
**データ**:
- 14/15件（93%）が10%未満で利確
- 平均リターン: **4.55%**（目標10%の半分以下）
- 最小: 0.41%（ORCLでほぼ即座に利確）

**問題**:
- 設定は10% take profitのはずが、実際は早期退出している
- 可能性: ボラティリティやノイズで即座にトリガー

**損失機会コスト**:
- 15件 × 平均5.45%の逃した利益 = 潜在的に **$1,000以上の機会損失**

#### 2. 保有期間が短すぎる
**データ**:
- Take Profit: 平均 0.9日（ほぼ当日決済）
- 最短: 0.0日（数時間）

**問題**:
- トレンドに乗る前に利確してしまう
- 手数料率が相対的に高くなる

#### 3. Stop Lossは適切に機能
**データ**:
- 8件、平均-1.53%の損失
- 最大損失: -5.00%（NBIS）
- 7%設定がほぼ守られている

**評価**: ✅ 良好（変更不要）

---

## Simple Exit V2 改善案

### Design Philosophy
1. **利益を伸ばす**: Trailing stopで利益確保しながら伸ばす
2. **ボラティリティ対応**: ATRベースで動的調整
3. **段階的利確**: Partial exitで柔軟性確保

---

### 改善案1: Trailing Stop導入（優先度: ⭐⭐⭐）

#### 概要
利益が出始めたらtrailing stopを使用し、「利益確保 + さらなる伸び」を両立

#### パラメータ設計
```python
# Initial stop (変更なし)
initial_stop = entry_price * (1 - 0.07)  # -7%

# Take profitトリガー後、trailing stopに切り替え
trailing_activation_pct = 0.05  # 5%利益が出たら開始
trailing_stop_pct = 0.03  # 3%の押し戻しで利確

# 例:
# Entry: $100
# Initial stop: $93 (-7%)
# Price: $105 → trailing開始
# Trailing stop: $105 * 0.97 = $101.85
# Price: $110 → trailing stop更新: $106.70
# Price: $108 → Stop hit at $106.70 (+6.7%利確)
```

#### 期待効果
- **平均リターン**: 4.55% → 8-10%
- **勝率**: 100%維持
- **P&L増加**: +$1,000-1,500 (年間)

#### リスク
- 押し戻しの設定が広すぎると利益減少
- 狭すぎると早期利確（現状と同じ）

#### 推奨設定（初期値）
```python
TRAILING_ACTIVATION = 0.05  # 5%
TRAILING_STOP_PCT = 0.03    # 3%
```

---

### 改善案2: Volatility-Aware Stop/Take（優先度: ⭐⭐）

#### 概要
ATR（Average True Range）に基づいて、stop/takeを動的調整

#### パラメータ設計
```python
# ATRベースのstop
atr_multiplier_stop = 2.0
dynamic_stop = entry_price - (atr * atr_multiplier_stop)

# ATRベースのtake
atr_multiplier_take = 3.0
dynamic_take = entry_price + (atr * atr_multiplier_take)

# 例:
# Entry: $100, ATR: $2
# Stop: $100 - ($2 * 2.0) = $96 (-4%)
# Take: $100 + ($2 * 3.0) = $106 (+6%)
```

#### メリット
1. **低ボラ銘柄**: タイトなstop/take（ノイズ少ない）
2. **高ボラ銘柄**: 広めのstop/take（ノイズに耐える）
3. **早期利確防止**: ボラに応じた適切な余裕

#### 期待効果
- **誤利確削減**: 50%減少
- **平均リターン**: +2-3%向上

#### リスク
- ATR計算の追加コスト
- Backtestでの検証必要

---

### 改善案3: Partial Exit（優先度: ⭐）

#### 概要
段階的に利確し、リスク削減 + 伸び余地の両立

#### パラメータ設計
```python
# First take: 50%ポジションを5%利益で決済
partial_exit_1 = {
    'pct_profit': 0.05,
    'qty_pct': 0.5
}

# Second take: 残り50%を10%利益で決済、または trailing
partial_exit_2 = {
    'pct_profit': 0.10,
    'qty_pct': 0.5,
    'or_trailing': True
}

# 例:
# Entry: 100株 @ $100
# Price $105 → 50株決済（+5%）
# Price $110 → 残り50株決済（+10%）
# 平均: +7.5%
```

#### メリット
1. **リスク削減**: 早期に元本回収
2. **心理的安定**: 確実な利益確保
3. **柔軟性**: 片方は伸ばす余地

#### 期待効果
- **リスク調整後リターン**: +15-20%向上
- **最大DD**: 削減

#### リスク
- 実装複雑度が高い
- 手数料増加（ただしpaper tradingでは無視可能）

---

## 推奨実装順序

### Phase 1: Trailing Stop（最優先）
**理由**: 
- 最大の改善効果
- 実装が比較的シンプル
- 既存ロジックに追加可能

**目標**:
- 平均リターン 4.55% → 8%
- P&L +$1,000-1,500/年

**実装期間**: 1-2日

---

### Phase 2: Volatility-Aware（中期）
**理由**:
- Trailing Stopと組み合わせで相乗効果
- ATR計算のインフラ整備必要

**目標**:
- 誤利確50%削減
- 平均リターン +2-3%

**実装期間**: 2-3日

---

### Phase 3: Partial Exit（長期）
**理由**:
- 複雑度高い
- Phase 1/2の効果確認後に判断

**目標**:
- リスク調整後リターン +15-20%

**実装期間**: 3-5日

---

## Simple Exit V2 パラメータ仕様（案）

```python
class SimpleExitV2Config:
    # Base stop loss (変更なし)
    stop_loss_pct: float = 0.07  # 7%
    
    # Trailing stop
    use_trailing: bool = True
    trailing_activation_pct: float = 0.05  # 5%利益で開始
    trailing_stop_pct: float = 0.03  # 3%押し戻しで利確
    
    # Volatility-aware (optional)
    use_volatility_aware: bool = False
    atr_period: int = 14
    atr_multiplier_stop: float = 2.0
    atr_multiplier_take: float = 3.0
    
    # Partial exit (optional)
    use_partial_exit: bool = False
    partial_exits: List[PartialExitRule] = [
        {'profit_pct': 0.05, 'qty_pct': 0.5},
        {'profit_pct': 0.10, 'qty_pct': 0.5}
    ]
    
    # Max holding period (追加検討)
    max_hold_days: int = 10  # 10日で強制決済
```

---

## 検証計画

### Backtest目標
1. **過去24件で検証**
   - 現状: 平均4.55%、P&L $1,974
   - V2期待: 平均8%+、P&L $3,000+

2. **勝率維持**
   - 目標: 95%+（現状100%）

3. **最大DD**
   - 目標: 現状維持または改善

### 実運用テスト
1. **Parallel run**: V1とV2を並行実行（別アカウント or paper）
2. **期間**: 2週間
3. **評価基準**:
   - 平均リターン
   - 勝率
   - Sharpe ratio
   - Max DD

---

## リスク評価

### 🟢 低リスク
- **Trailing Stop**: 実績ある手法、大きなリスクなし

### 🟡 中リスク
- **Volatility-Aware**: ATR計算ミスでstop/take不適切になる可能性

### 🔴 高リスク
- **Partial Exit**: 実装バグで意図しない決済の可能性

---

## 期待効果まとめ

| 指標 | 現状 (V1) | V2 (Trailing) | V2 (Full) |
|------|-----------|---------------|-----------|
| 平均リターン | 4.55% | 8.0% | 10.0% |
| 勝率 | 100% | 95% | 90% |
| 年間P&L | $1,974 | $3,500 | $4,500 |
| Sharpe比 | - | +30% | +50% |

---

## 次のアクション

### 今日中（2026-04-27）
1. ✅ この改善計画を文書化
2. ⏳ Trailing stop実装の詳細設計
3. ⏳ 簡易backtest実装

### 明日以降
1. SimpleExitV2クラス実装
2. Backtest実行
3. 並行運用開始

---

**作成日**: 2026-04-27  
**作成者**: AI Agent  
**ステータス**: Phase 1実装準備完了
