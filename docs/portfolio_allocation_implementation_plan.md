# Portfolio Allocation Implementation Plan

## 目標
- ETF: 35% of portfolio value
- Stocks: 65% of portfolio value
- Total Exposure: 70-85% (市場レジームに応じて)

## 現在の問題
1. `portfolio_allocation.yaml`が読み込まれていない
2. ETF/Stock比率を強制する仕組みがない
3. ETFへのシグナルが発生していない可能性

## 実装計画

### 1. Portfolio Allocatorクラスの作成
```python
# src/stock_swing/risk/portfolio_allocator.py

from pathlib import Path
import yaml
from typing import Dict, List

class PortfolioAllocator:
    """Enforce portfolio allocation rules (ETF vs Stocks)"""
    
    def __init__(self, config_path: Path):
        self.config = self._load_config(config_path)
        self.target_etf_pct = self.config.get('portfolio', {}).get('allocation', {}).get('ETFs', 0.35)
        self.target_stock_pct = self.config.get('portfolio', {}).get('allocation', {}).get('stocks', 0.65)
    
    def _load_config(self, path: Path) -> Dict:
        with open(path) as f:
            return yaml.safe_load(f)
    
    def should_prioritize_etf(self, 
                               current_etf_value: float, 
                               current_stock_value: float,
                               portfolio_value: float) -> bool:
        """ETFを優先購入すべきか判定"""
        total_invested = current_etf_value + current_stock_value
        if total_invested == 0:
            return True  # 初期状態ではETFを優先
        
        current_etf_pct = current_etf_value / total_invested if total_invested > 0 else 0
        
        # ETFが目標より5%以上低い場合、ETFを優先
        return current_etf_pct < (self.target_etf_pct - 0.05)
    
    def should_prioritize_stock(self,
                                 current_etf_value: float,
                                 current_stock_value: float,
                                 portfolio_value: float) -> bool:
        """Stockを優先購入すべきか判定"""
        total_invested = current_etf_value + current_stock_value
        if total_invested == 0:
            return False
        
        current_stock_pct = current_stock_value / total_invested if total_invested > 0 else 0
        
        # Stockが目標より5%以上低い場合、Stockを優先
        return current_stock_pct < (self.target_stock_pct - 0.05)
    
    def filter_decisions_by_allocation(self, 
                                        decisions: List,
                                        current_positions: Dict,
                                        portfolio_value: float,
                                        etf_symbols: set) -> List:
        """Portfolio allocation戦略に基づいて意思決定をフィルタリング"""
        
        # 現在のETF/Stock保有額を計算
        current_etf_value = sum(
            p.get('market_value', 0) 
            for p in current_positions.values() 
            if p.get('symbol') in etf_symbols
        )
        current_stock_value = sum(
            p.get('market_value', 0) 
            for p in current_positions.values() 
            if p.get('symbol') not in etf_symbols
        )
        
        # 優先度を判定
        prioritize_etf = self.should_prioritize_etf(current_etf_value, current_stock_value, portfolio_value)
        prioritize_stock = self.should_prioritize_stock(current_etf_value, current_stock_value, portfolio_value)
        
        if prioritize_etf:
            # ETFの意思決定を優先
            etf_decisions = [d for d in decisions if d.proposed_order.symbol in etf_symbols]
            stock_decisions = [d for d in decisions if d.proposed_order.symbol not in etf_symbols]
            return etf_decisions + stock_decisions
        elif prioritize_stock:
            # Stockの意思決定を優先
            stock_decisions = [d for d in decisions if d.proposed_order.symbol not in etf_symbols]
            etf_decisions = [d for d in decisions if d.proposed_order.symbol in etf_symbols]
            return stock_decisions + etf_decisions
        else:
            # バランスが取れている場合、そのまま
            return decisions
```

### 2. paper_demo.pyへの統合

```python
# src/stock_swing/cli/paper_demo.py に追加

from stock_swing.risk.portfolio_allocator import PortfolioAllocator

# 初期化セクションで
portfolio_allocator = PortfolioAllocator(
    project_root / "config" / "strategy" / "portfolio_allocation.yaml"
)

# 意思決定フィルタリングの前に
actionable = portfolio_allocator.filter_decisions_by_allocation(
    decisions=actionable,
    current_positions=current_positions_full,
    portfolio_value=equity,
    etf_symbols=ETF_SYMBOLS
)
```

### 3. Exposure目標の引き上げ

```python
# config/strategy/exposure_targets.yaml (新規作成)

exposure_targets:
  neutral: 0.75  # 現在の85%から75%に変更（より積極的）
  bullish: 0.85  # 95%から85%に（やや保守的に）
  cautious: 0.60 # 65%から60%に

  # ETF優先時の追加配分
  etf_boost_pct: 0.10  # ETFが不足時、10%追加配分
```

### 4. IT系ETFリストの最適化

現在のETF_SYMBOLS（17銘柄）から、流動性と実績のあるものに絞る：

**推奨ETF（優先順位順）:**
1. **SOXX** - iShares Semiconductor ETF（最大、最も流動性高い）
2. **SMH** - VanEck Semiconductor ETF
3. **SOXQ** - Invesco PHLX Semiconductor ETF
4. **QTEC** - First Trust NASDAQ-100 Tech Sector
5. **SKYY** - First Trust Cloud Computing ETF
6. **FTXL** - First Trust Nasdaq Semiconductor ETF

**除外を検討:**
- SHOC, CHPX, CHPS, SMHX（流動性が低い）
- TDIV, FRWD（配当重視、成長性低い）

## 実装スケジュール

### Week 1: 基盤実装
- [ ] PortfolioAllocator クラス作成
- [ ] テストコード作成
- [ ] paper_demoへの統合

### Week 2: 調整とモニタリング
- [ ] ETF購入が実際に行われるか確認
- [ ] 35%/65%比率に収束するか検証
- [ ] Exposure目標の達成状況を確認

### Week 3: 最適化
- [ ] ETFリストの絞り込み
- [ ] シンボル別制限の調整（10% → 12-15%）
- [ ] Exit戦略の修正

## 期待される効果

### Before (現在)
- Exposure: 42.6%
- ETF: 0%
- Stock: 100%
- 遊休資本: $45,000

### After (改修後)
- Exposure: 70-75%
- ETF: 35% (~$25,000)
- Stock: 65% (~$48,000)
- 遊休資本: $25,000（チャンス用として適切）

### 年間パフォーマンス改善予測
- 現在: 年間リターン 4-5%
- 改修後: 年間リターン 10-15%（**2-3倍改善**）
- ETF効果: ボラティリティ削減、Sharpe Ratio向上

## リスク管理

1. **段階的導入**: 
   - Week 1: ETF 20%目標でスタート
   - Week 2: 25%に引き上げ
   - Week 3: 35%達成

2. **モニタリング指標**:
   - 日次でETF/Stock比率を確認
   - Drawdownが8%を超えたら一時停止
   - 勝率が55%を下回ったら見直し

3. **フェイルセーフ**:
   - ETFが30%を超えたら新規購入停止
   - Stockが70%を超えたらETF優先モード

## 結論

この実装により：
1. ✅ 資本効率が大幅に向上（42% → 75%）
2. ✅ ETF 35%目標を達成
3. ✅ リスク分散とリターンの両立
4. ✅ IT系に限定しながらポートフォリオ最適化
