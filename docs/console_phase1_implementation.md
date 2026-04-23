# Console Enhancement Phase 1 - Implementation Plan
**承認日:** 2026-04-23 17:30 JST  
**実装期間:** Week 3 Day 3-5 (Apr 25-27)  
**工数:** 13-17時間

---

## 🎯 Phase 1 スコープ

### 実装機能
1. **戦略別パフォーマンス比較** (3-4h)
2. **リアルタイムメトリクス** (4-5h)
3. **インタラクティブチャート** (6-8h)

---

## 📋 実装タスク詳細

### Task 1: 戦略別パフォーマンス分析 (3-4h)

#### 1.1 バックエンド: Strategy Analyzer (1.5-2h)
```python
# src/stock_swing/analysis/strategy_analyzer.py

from dataclasses import dataclass
from typing import Dict, List, Any
import numpy as np

@dataclass
class StrategyMetrics:
    strategy_id: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    avg_win: float
    avg_loss: float
    avg_pnl: float
    sharpe_ratio: float
    max_drawdown: float
    profit_factor: float

class StrategyAnalyzer:
    def analyze_by_strategy(self, trades: List[Dict]) -> Dict[str, StrategyMetrics]:
        """Analyze performance by strategy"""
        
    def get_top_performers(self, by='sharpe', n=5):
        """Get top N strategies by metric"""
        
    def get_symbol_breakdown(self, strategy_id: str):
        """Get per-symbol performance for a strategy"""
```

#### 1.2 Dashboard Service統合 (1h)
```python
# console/services/dashboard_service.py

def get_strategy_analysis(self) -> Dict[str, Any]:
    analyzer = StrategyAnalyzer()
    trades = self._tracker.state.trades
    
    return {
        "by_strategy": analyzer.analyze_by_strategy(trades),
        "top_strategies": analyzer.get_top_performers(),
        "comparison_chart": analyzer.get_comparison_data(),
    }
```

#### 1.3 フロントエンド表示 (0.5-1h)
```javascript
// 新タブ: "分析" (Analysis)
<div class="card">
  <h3>戦略別パフォーマンス</h3>
  <div id="strategy-comparison"></div>
</div>

function renderStrategyComparison(data) {
  // Horizontal bar chart
  // Win rate, Avg P&L, Sharpe per strategy
}
```

---

### Task 2: リアルタイムメトリクス (4-5h)

#### 2.1 Risk Calculator (2-2.5h)
```python
# src/stock_swing/analysis/risk_calculator.py

class RiskCalculator:
    def calculate_current_drawdown(self, equity_curve):
        """Current drawdown from peak"""
        
    def calculate_kelly_criterion(self, win_rate, avg_win, avg_loss):
        """Optimal position size per Kelly"""
        
    def calculate_portfolio_heat(self, positions, equity):
        """% of capital at risk"""
        
    def calculate_risk_score(self, positions, equity, volatility):
        """Overall risk score 0-10"""
        
    def calculate_var(self, returns, confidence=0.95):
        """Value at Risk"""
```

#### 2.2 Live Metrics API (1h)
```python
# console/services/dashboard_service.py

def get_live_metrics(self) -> Dict[str, Any]:
    calc = RiskCalculator()
    
    current_dd = calc.calculate_current_drawdown(equity_curve)
    kelly = calc.calculate_kelly_criterion(...)
    heat = calc.calculate_portfolio_heat(...)
    risk_score = calc.calculate_risk_score(...)
    
    return {
        "current_drawdown": current_dd,
        "max_drawdown": max_dd,
        "kelly_suggested_size": kelly,
        "portfolio_heat": heat,
        "risk_score": risk_score,
        "days_since_last_trade": days,
        "open_pnl": unrealized_pnl,
    }
```

#### 2.3 Auto-refresh UI (1-1.5h)
```javascript
// 概要タブに追加
<div class="card live-metrics">
  <h3>📊 Live Metrics <span class="refresh-indicator">●</span></h3>
  <div id="live-metrics-content"></div>
</div>

// Auto-refresh every 30s
setInterval(async () => {
  const metrics = await fetch('/api/live_metrics').then(r => r.json());
  renderLiveMetrics(metrics);
}, 30000);
```

---

### Task 3: インタラクティブチャート (6-8h)

#### 3.1 Chart.js統合 (2-3h)
```html
<!-- CDN追加 -->
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0"></script>
```

```javascript
// console/ui/charts.js (新規作成)

class InteractiveCharts {
  createEquityCurve(canvasId, data) {
    // Line chart with zoom/pan
    new Chart(ctx, {
      type: 'line',
      data: { ... },
      options: {
        plugins: {
          zoom: { enabled: true },
          tooltip: { mode: 'index' },
        }
      }
    });
  }
  
  createDrawdownChart(canvasId, data) {
    // Area chart (inverted)
  }
  
  createWinLossDistribution(canvasId, trades) {
    // Histogram of P&L
  }
  
  createMonthlyReturns(canvasId, snapshots) {
    // Bar chart by month
  }
}
```

#### 3.2 チャートタブ追加 (2-2.5h)
```html
<!-- 新タブ: "Charts" -->
<div id="charts-tab">
  <div class="grid">
    <div class="card">
      <h3>Equity Curve</h3>
      <canvas id="equity-chart"></canvas>
    </div>
    <div class="card">
      <h3>Drawdown</h3>
      <canvas id="drawdown-chart"></canvas>
    </div>
  </div>
  <div class="grid">
    <div class="card">
      <h3>P&L Distribution</h3>
      <canvas id="pnl-histogram"></canvas>
    </div>
    <div class="card">
      <h3>Monthly Returns</h3>
      <canvas id="monthly-returns"></canvas>
    </div>
  </div>
</div>
```

#### 3.3 トレード詳細モーダル (1.5-2.5h)
```javascript
// クリック可能なトレード行
function renderTradeRow(trade) {
  return `
    <tr class="clickable" onclick="showTradeDetail('${trade.id}')">
      <td>${trade.symbol}</td>
      <td>${trade.pnl}</td>
      ...
    </tr>
  `;
}

// モーダル表示
function showTradeDetail(tradeId) {
  // Fetch trade details
  // Show modal with:
  //   - Entry/exit prices
  //   - Strategy logic used
  //   - Position size calculation
  //   - Duration chart
}
```

---

## 🗓️ 実装スケジュール

### Day 1 (Apr 25, Week 3 Day 3)
```
Morning (4h):
  ✅ Task 1.1: StrategyAnalyzer module
  ✅ Task 1.2: Dashboard integration
  
Afternoon (3h):
  ✅ Task 1.3: Frontend display
  ✅ Task 2.1: RiskCalculator (partial)
```

### Day 2 (Apr 26, Week 3 Day 4)
```
Morning (4h):
  ✅ Task 2.1: RiskCalculator (complete)
  ✅ Task 2.2: Live Metrics API
  
Afternoon (3h):
  ✅ Task 2.3: Auto-refresh UI
  ✅ Task 3.1: Chart.js setup
```

### Day 3 (Apr 27, Week 3 Day 5)
```
Morning (4h):
  ✅ Task 3.1: Chart.js charts (complete)
  ✅ Task 3.2: Charts tab
  
Afternoon (2-3h):
  ✅ Task 3.3: Trade detail modal
  ✅ Testing & refinement
```

---

## 📦 必要なパッケージ

```bash
# Python
pip install numpy scipy

# Frontend (CDN - no install)
- Chart.js 4.4.0
- Chart.js Zoom Plugin
```

---

## 🧪 テスト計画

### Unit Tests
```python
# tests/analysis/test_strategy_analyzer.py
def test_analyze_by_strategy():
    # Mock trades
    # Assert metrics calculated correctly

# tests/analysis/test_risk_calculator.py
def test_kelly_criterion():
def test_drawdown():
```

### Integration Tests
```python
# Test API endpoints
def test_get_strategy_analysis():
def test_get_live_metrics():
```

### Manual UI Tests
```
✓ Charts render correctly
✓ Auto-refresh works
✓ Trade modal displays
✓ No console errors
```

---

## 📊 Success Criteria

### 機能要件
- [ ] 戦略別パフォーマンス表が表示される
- [ ] Win rate, Sharpe, P&Lが正確
- [ ] Live Metricsが30秒ごとに更新
- [ ] Kellyサイズが計算される
- [ ] Equity/Drawdownチャートがズーム可能
- [ ] トレード詳細モーダルが開く

### 性能要件
- [ ] API応答 < 500ms
- [ ] チャート描画 < 1s
- [ ] メモリリーク無し

### UX要件
- [ ] 視覚的に分かりやすい
- [ ] レスポンシブ（モバイル対応）
- [ ] エラーハンドリング

---

## 🚀 実装開始

Next: Task 1.1 StrategyAnalyzer実装
File: src/stock_swing/analysis/strategy_analyzer.py

Ready to start?
