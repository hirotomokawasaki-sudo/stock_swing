# Feature: Portfolio Value Comparison Chart

## 概要
自分のポートフォリオとベンチマーク (SPY) を同じチャートで比較表示する。

## UI デザイン

```
Portfolio Value Over Time
┌────────────────────────────────────────────────┐
│ [ Day ] [ 3 Days ] [ Week ] [ Month ] [All Time] │
├────────────────────────────────────────────────┤
│                                                │
│  $120k ┤                    あなた ─────────  │
│        │                   ╱                   │
│  $115k ┤                 ╱                     │
│        │               ╱                       │
│  $110k ┤             ╱    SPY ············     │
│        │           ╱    ╱                      │
│  $105k ┤         ╱    ╱                        │
│        │       ╱    ╱                          │
│  $100k ┼━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│        │ Jan  Feb  Mar  Apr                    │
└────────────────────────────────────────────────┘
Legend:
  ━━━ あなた (青色)
  ··· SPY Benchmark (グレー破線)
  
Stats:
  あなた:      +5.53% (+$5,534)
  SPY:         +3.01% (+$3,010)
  Alpha:       +2.52% ✅ Outperforming
```

## データ構造

### 必要なデータ
1. **あなたの Equity curve**
   - 既に `daily_snapshots` にある
   
2. **SPY の価格データ**
   - 既に `data/benchmarks/SPY_daily.json` にある
   - Normalize が必要 (starting point を $100k に揃える)

### Normalize 計算
```javascript
// 例: SPY の normalize
const spyStart = spyData[0].close;  // 710.06
const spyNormalized = spyData.map(d => ({
  date: d.date,
  value: (d.close / spyStart) * 100000  // $100k スタート
}));

// あなたの Equity は既に absolute value
```

## 実装ステップ

### 1. Backend API 拡張
**File**: `console/services/dashboard_service.py`

```python
def get_comparison_chart_data(self, period='all'):
    """Get portfolio vs benchmark comparison data."""
    # Load portfolio snapshots
    snapshots = self._load_snapshots()
    
    # Load SPY benchmark
    spy_data = self._load_benchmark_data('SPY')
    
    # Filter by period
    if period == 'day':
        snapshots = snapshots[-1:]
        spy_data = spy_data[-1:]
    elif period == '3days':
        snapshots = snapshots[-3:]
        spy_data = spy_data[-3:]
    # etc.
    
    # Normalize SPY to start at same point
    spy_normalized = normalize_benchmark(spy_data, snapshots[0]['equity'])
    
    return {
        'portfolio': snapshots,
        'benchmark': spy_normalized,
        'period': period
    }
```

### 2. Frontend Chart.js 実装
**File**: `console/ui/app.js`

```javascript
renderComparisonChart() {
    const ctx = document.getElementById('comparisonChart');
    new Chart(ctx, {
        type: 'line',
        data: {
            datasets: [
                {
                    label: 'あなた',
                    data: portfolioData,
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    borderWidth: 2,
                },
                {
                    label: 'SPY Benchmark',
                    data: benchmarkData,
                    borderColor: '#6b7280',
                    backgroundColor: 'transparent',
                    borderDash: [5, 5],
                    borderWidth: 2,
                }
            ]
        },
        options: {
            responsive: true,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            let label = context.dataset.label || '';
                            if (label) {
                                label += ': ';
                            }
                            label += '$' + context.parsed.y.toLocaleString();
                            return label;
                        }
                    }
                }
            }
        }
    });
}
```

### 3. Period Selector
```html
<div class="period-selector">
    <button class="period-btn active" data-period="day">Day</button>
    <button class="period-btn" data-period="3days">3 Days</button>
    <button class="period-btn" data-period="week">Week</button>
    <button class="period-btn" data-period="month">Month</button>
    <button class="period-btn" data-period="all">All Time</button>
</div>

<script>
document.querySelectorAll('.period-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
        const period = e.target.dataset.period;
        loadComparisonChart(period);
    });
});
</script>
```

## 期待される効果

1. **視覚的に分かりやすい**
   - 一目で市場を上回っているか分かる
   
2. **モチベーション向上**
   - ベンチマークを上回っていることが確認できる
   
3. **問題の早期発見**
   - ベンチマークに負け始めたら警告

4. **プレゼンテーション用**
   - 投資家やコンペ審査員に見せやすい

## 次のステップ
1. Backend API 実装
2. Frontend Chart 実装
3. Period selector 実装
4. Stats calculation (Alpha 表示)
