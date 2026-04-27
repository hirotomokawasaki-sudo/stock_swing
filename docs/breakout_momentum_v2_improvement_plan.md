# Breakout Momentum V2 改善計画

## 現状分析（breakout_momentum_v1）

### ✅ 強み
1. **Signal品質**: 高い（avg sig=0.79, conf=0.67）
2. **勝率**: 63.6% (28/44)
3. **Profit Factor**: 5.49（優秀）
4. **Position_size問題**: 解決済み（$50→$400）

### ⚠️ 弱点・改善機会

#### 1. Denyの逆説
**発見**: 
- **Deny決済の方がSignal/Confidenceが高い**
  - DENY: avg sig=0.93, conf=0.79
  - PASS: avg sig=0.79, conf=0.67

**理由**:
- 良いSignalほど大きなposition sizeを要求
- → Sector cap / Position limitに引っかかる
- → Denyされる

**問題**:
- **最良のシグナルを逃している**
- Conversion率を下げている

#### 2. Symbol集中
**データ**:
- PLTR: 58 decisions (37.2%の集中度)
- PATH: 33 decisions (21.2%)
- 上位2銘柄で58.4%を占める

**問題**:
- 同じ銘柄に繰り返しシグナル
- Sector capで制限される
- 分散不足

#### 3. Conversion率の余地
**データ**:
- 過去7日: 62.0% (改善前)
- 最新2日: 100% (position_size改善後)

**問題**:
- Sector cap等の新しい制約が顕在化
- さらなる改善余地あり

---

## Breakout Momentum V2 改善案

### Design Philosophy
1. **良いシグナルを逃さない**: Sector cap対応
2. **分散向上**: Symbol rotation
3. **Regime連携**: Market状況に応じた調整

---

### 改善案1: Dynamic Sector Allocation（優先度: ⭐⭐⭐）

#### 概要
固定sector capではなく、Signal品質に応じて動的調整

#### 現状の問題
```python
# 現在: 固定sector cap（50%?）
max_sector_exposure = equity * 0.50

# 結果:
# - 良いシグナルでもsector cap到達で deny
# - セクター内の優先順位がない
```

#### 改善案
```python
# Signal強度に応じた優先度付き配分
class DynamicSectorAllocator:
    def allocate(self, signals, current_positions):
        # 1. Sectorごとにsignalをグループ化
        by_sector = group_by_sector(signals)
        
        # 2. Signal強度でソート
        for sector, sector_signals in by_sector.items():
            sector_signals.sort(key=lambda s: s.signal_strength * s.confidence, reverse=True)
        
        # 3. Top N signals per sectorを選択
        allocations = []
        for sector, sorted_signals in by_sector.items():
            sector_cap = self.get_sector_cap(sector, equity)
            current_exposure = self.get_current_exposure(sector, current_positions)
            remaining = sector_cap - current_exposure
            
            # 優先度順に割り当て
            for signal in sorted_signals:
                if signal.position_size <= remaining:
                    allocations.append(signal)
                    remaining -= signal.position_size
                elif remaining > 0:
                    # Partial allocation（縮小して通す）
                    scaled_signal = signal.scale_to(remaining)
                    allocations.append(scaled_signal)
                    break
        
        return allocations
```

#### 期待効果
- **Conversion率**: +10-15%向上
- **優先度**: 高Signal品質のエントリー優先
- **Sector分散**: 維持しながら最適化

---

### 改善案2: Symbol Rotation & Cooldown（優先度: ⭐⭐）

#### 概要
同一銘柄の連続エントリーを制限し、分散向上

#### 現状の問題
```
PLTR: 58 decisions (集中度高)
PATH: 33 decisions
→ 同じ銘柄に偏りすぎ
```

#### 改善案
```python
class SymbolRotation:
    def __init__(self):
        self.last_entry = {}  # symbol -> timestamp
        self.cooldown_hours = 24  # 24時間のクールダウン
    
    def can_enter(self, symbol, timestamp):
        last = self.last_entry.get(symbol)
        if last is None:
            return True
        
        hours_since = (timestamp - last).total_seconds() / 3600
        return hours_since >= self.cooldown_hours
    
    def record_entry(self, symbol, timestamp):
        self.last_entry[symbol] = timestamp
```

#### メリット
1. **分散向上**: 強制的に別銘柄を検討
2. **オーバートレード防止**: 同一銘柄の追いかけ防止
3. **リスク削減**: 銘柄集中リスク軽減

#### パラメータ
- `cooldown_hours`: 24時間（調整可能）
- `max_positions_per_symbol`: 2-3ポジションまで

---

### 改善案3: Regime-Aware Thresholds（優先度: ⭐⭐）

#### 概要
Market regimeに応じてentry/exit閾値を動的調整

#### Regime定義
```python
class MarketRegime(Enum):
    BULL = "bull"        # VIX < 15, SPY trend > 0
    NEUTRAL = "neutral"  # VIX 15-25
    BEAR = "bear"        # VIX > 25, SPY trend < 0
```

#### パラメータ調整
```python
REGIME_PARAMS = {
    MarketRegime.BULL: {
        'min_signal_strength': 0.40,  # 緩和
        'min_confidence': 0.35,
        'max_position_size': 500,
        'sector_cap_multiplier': 1.2  # +20%
    },
    MarketRegime.NEUTRAL: {
        'min_signal_strength': 0.50,  # 現状維持
        'min_confidence': 0.40,
        'max_position_size': 400,
        'sector_cap_multiplier': 1.0
    },
    MarketRegime.BEAR: {
        'min_signal_strength': 0.70,  # 厳格化
        'min_confidence': 0.60,
        'max_position_size': 300,
        'sector_cap_multiplier': 0.8  # -20%
    }
}
```

#### 期待効果
- **Bull market**: Conversion率 +15-20%
- **Bear market**: Drawdown -30-40%
- **Sharpe ratio**: +0.3-0.5

---

### 改善案4: Volatility-Aware Position Sizing（優先度: ⭐）

#### 概要
ATRベースで動的にposition sizeを調整

#### 現状の問題
```python
# 現在: 固定$400上限
# → 高ボラ銘柄も低ボラ銘柄も同じ
# → リスク不均一
```

#### 改善案
```python
def calculate_position_size(signal, atr, equity):
    # Target risk: 1% of equity
    target_risk = equity * 0.01
    
    # Risk per share (2x ATR stop)
    risk_per_share = atr * 2.0
    
    # Position size
    max_shares = target_risk / risk_per_share
    position_value = max_shares * signal.price
    
    # Apply cap
    capped_value = min(position_value, max_position_size)
    
    return int(capped_value / signal.price)
```

#### メリット
1. **リスク均一化**: 全ポジションが同等リスク
2. **高ボラ対応**: 自動的にサイズ縮小
3. **低ボラ活用**: サイズ拡大で機会最大化

---

## Breakout Momentum V2 パラメータ仕様（案）

```python
class BreakoutMomentumV2Config:
    # Base thresholds
    min_signal_strength: float = 0.50
    min_confidence: float = 0.40
    max_position_size: float = 400
    
    # Dynamic sector allocation
    use_dynamic_sector_alloc: bool = True
    sector_cap_default: float = 0.50  # 50% of equity
    top_signals_per_sector: int = 3
    allow_partial_allocation: bool = True
    
    # Symbol rotation
    use_symbol_rotation: bool = True
    symbol_cooldown_hours: int = 24
    max_positions_per_symbol: int = 2
    
    # Regime awareness
    use_regime_aware: bool = True
    regime_detection: str = "vix_spx"  # or "price_momentum"
    
    # Volatility-aware sizing
    use_volatility_sizing: bool = False  # Phase 3
    target_risk_pct: float = 0.01  # 1% per position
    atr_period: int = 14
    atr_multiplier_stop: float = 2.0
```

---

## 実装優先順位

### Phase 1: Dynamic Sector Allocation（今週）
**理由**: 
- 最大の改善効果（Conversion +10-15%）
- 既存の良いシグナルを活用

**実装内容**:
1. Signal強度でソート
2. Sectorごとに優先配分
3. Partial allocation

**期待効果**:
- Conversion率: 62% → 75%+
- P&L: +$2,000-3,000/年

---

### Phase 2: Symbol Rotation（来週）
**理由**:
- 分散向上
- 実装シンプル

**実装内容**:
1. Cooldown tracker
2. Symbol entry記録
3. Can_enter check

**期待効果**:
- 銘柄分散: +30-40%
- Max DD: -10-15%

---

### Phase 3: Regime-Aware（2週間後）
**理由**:
- Regime検出のインフラ必要
- Backtest必須

**実装内容**:
1. Regime detector
2. Dynamic parameter loader
3. Backtesting framework

**期待効果**:
- Sharpe: +0.3-0.5
- Bear market DD: -30-40%

---

## 検証計画

### Backtest
1. **過去3ヶ月データ**で検証
2. **各改善案を個別にテスト**
3. **組み合わせ効果を検証**

### 評価指標
- Conversion率
- Win率
- Profit Factor
- Sharpe Ratio
- Max Drawdown
- 銘柄分散度

### 実運用テスト
1. **Parallel run**: V1とV2を並行
2. **期間**: 4週間
3. **評価**: 週次レビュー

---

## リスク評価

### 🟢 低リスク
- **Dynamic Sector Allocation**: 既存ロジックの拡張
- **Symbol Rotation**: 保守的な制約追加

### 🟡 中リスク
- **Regime-Aware**: Regime誤検出のリスク
- **Volatility Sizing**: Position size計算ミス

### 🔴 高リスク
- **過度な最適化**: Overfittingの可能性

---

## 期待効果まとめ

| 指標 | 現状 (V1) | V2 (Phase 1) | V2 (Full) |
|------|-----------|--------------|-----------|
| Conversion率 | 62% | 75% | 85% |
| Win率 | 63.6% | 65% | 68% |
| Profit Factor | 5.49 | 6.5 | 8.0 |
| Sharpe Ratio | 0.51 | 0.65 | 0.85 |
| Max DD | $329 | $280 | $250 |
| 年間P&L | $4,293 | $7,000 | $10,000 |

---

## 次のアクション

### 今日中（2026-04-27）
1. ✅ この改善計画を文書化
2. ⏳ Dynamic Sector Allocation設計詳細化
3. ⏳ Backtest framework検討

### 明日以降
1. BreakoutMomentumV2クラス実装
2. Dynamic Sector Allocator実装
3. Backtest実行
4. 並行運用開始

---

**作成日**: 2026-04-27  
**作成者**: AI Agent  
**ステータス**: Phase 1実装準備完了
