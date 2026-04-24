# Backtest Engine Design - Week 3 Day 1

## 目的
Week 2の実トレードデータを使用して、パラメータ最適化を行うためのバックテストエンジンを実装する。

## 設計方針

### 1. データソース
- **入力:** Week 2の実トレードデータ (44-68 closed trades)
- **期間:** 2026-04-09 ～ 2026-04-23 (19日間)
- **データ:** 決定ログ、約定履歴、価格データ

### 2. Walk-Forward Validation

```
Training Window: 10日間
Testing Window: 5日間

例:
Train: Day 1-10  → Test: Day 11-15
Train: Day 6-15  → Test: Day 16-19
```

### 3. パラメータグリッド

優先度高（150-200組み合わせ）:

#### Entry Parameters
- confidence_threshold: [0.60, 0.65, 0.70, 0.75]
- min_news_freshness: [6h, 12h, 24h]
- momentum_threshold: [0.5, 1.0, 1.5]

#### Exit Parameters
- stop_loss_pct: [0.05, 0.07, 0.10]
- take_profit_pct: [0.10, 0.15, 0.20]
- max_hold_days: [3, 5, 7]

#### Position Sizing
- max_position_pct: [0.06, 0.08, 0.10]
- max_risk_per_trade: [0.003, 0.005, 0.007]

組み合わせ数: 4×3×3 × 3×3×3 × 3×3 = 2,916
→ 優先度でフィルタして 150-200に絞る

### 4. 評価メトリクス

Primary:
- Total Return (%)
- Sharpe Ratio
- Win Rate (%)

Secondary:
- Max Drawdown (%)
- Profit Factor
- Avg Win / Avg Loss
- Number of Trades

### 5. アーキテクチャ

```
BacktestEngine
├── DataLoader        # 過去データ読み込み
├── ParameterGrid     # グリッド生成
├── TradeSimulator    # トレードシミュレーション
├── MetricsCalculator # パフォーマンス計算
└── WalkForward       # Walk-forward validation
```

## 実装計画

### Phase 1: 基盤構築 (本日 2-3h)
1. BacktestEngine クラス
2. DataLoader (決定ログ読み込み)
3. ParameterGrid 生成器

### Phase 2: シミュレーター (本日 2-3h)
1. TradeSimulator (エントリー/エグジットロジック)
2. P&L計算
3. ポジション管理

### Phase 3: 評価 (明日)
1. MetricsCalculator
2. Walk-forward validation
3. 結果集計

## データ構造

### Trade Record
```python
@dataclass
class BacktestTrade:
    symbol: str
    entry_date: datetime
    entry_price: float
    exit_date: datetime
    exit_price: float
    qty: int
    pnl: float
    return_pct: float
    hold_days: int
    exit_reason: str  # stop_loss, take_profit, max_hold, manual
```

### Backtest Result
```python
@dataclass
class BacktestResult:
    parameters: dict
    total_return: float
    sharpe_ratio: float
    win_rate: float
    max_drawdown: float
    total_trades: int
    avg_pnl: float
    profit_factor: float
    trades: List[BacktestTrade]
```

## 次のステップ

1. ✅ 設計ドキュメント作成
2. ⏩ DataLoader実装
3. ⏩ ParameterGrid実装
4. ⏩ TradeSimulator実装

---

作成日時: 2026-04-24 11:52 JST
