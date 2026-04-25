# Stock Swing - 実装スケジュール

**作成日**: 2026-04-25  
**最終更新**: 2026-04-25 17:20 JST

---

## 📊 現在の状況

### ✅ 完了済み (2026-04-25)
- **Week 1 (T1-T4)**: 基本機能・PnL・Reconciliation
- **Week 2 (T5-T8)**: Partial fill, Discrepancy, Conversion, Strategy overview
- **Month 1 (T9-T12)**: UI 拡張、Drilldown、Summary、Parameter tuning

**Total**: 12 tasks complete (100%)  
**Commits**: 21  
**作業時間**: 6.5 hours

---

## 🎯 明日以降の優先順位

### Priority 1: 運用確認・モニタリング (1週間)

#### 📅 Day 1 (2026-04-26 土曜)
**目的**: 今日の変更の効果測定

**タスク**:
1. **朝のモニタリング (30分)**
   - Dashboard 確認
   - Conversion rate チェック
   - Position size limit 確認
   - Parameter 設定確認

2. **実運用観察 (1-2時間)**
   - paper_demo 実行を観察
   - Conversion rate: 13.2% → 20-25% 達成確認
   - Position size $400 の実行状況
   - Symbol 10% limit の動作確認

3. **ログ分析 (1時間)**
   - Submission ログ確認
   - Rejection 理由の分析
   - Partial fill 発生有無

**成果物**:
- 観察レポート (docs/daily_logs/2026-04-26.md)
- Conversion rate 実績値
- 改善点リスト

---

#### 📅 Day 2-3 (2026-04-27-28 日月)
**目的**: PnL 精度の最終確認

**タスク**:
1. **PnL 乖離の追跡 (1時間/日)**
   - Broker vs Tracker の差分確認
   - 2.3x 乖離が改善されているか
   - Partial fill 処理の動作確認

2. **Reconciliation 監視 (30分/日)**
   - 15分ごとの auto-sync 確認
   - Discrepancy の発生パターン
   - Mismatch の解消状況

3. **バグ修正 (必要に応じて)**
   - 発見された問題の対処
   - テスト追加

**成果物**:
- PnL 精度レポート
- バグ修正 (if any)

---

#### 📅 Week 2 (2026-04-29 - 05-02)
**目的**: 1週間の総合評価

**タスク**:
1. **週次サマリー作成 (2時間)**
   - Conversion rate 改善効果
   - PnL 精度改善効果
   - Position management 評価
   - Parameter tuning の使用状況

2. **T11 拡張機能の実装検討 (2-3時間)**
   - Top alerts 実装
   - Low conversion symbols 自動検出
   - Strategy health チェック

**成果物**:
- Weekly summary
- T11 拡張計画

---

### Priority 2: Console Enhancement (2週間)

#### 📅 Week 3 (2026-05-03 - 05-09)
**テーマ**: Performance Dashboard

**タスク**:
1. **戦略別パフォーマンス比較 (3-4時間)**
   - Win rate, Avg P&L, Sharpe ratio 計算
   - Strategy ID 別集計
   - 棒グラフ表示

2. **リアルタイムメトリクス (4-5時間)**
   - Current drawdown 計算
   - Portfolio heat 表示
   - Risk score 算出
   - Auto-refresh (30秒)

**成果物**:
- Performance dashboard タブ
- Real-time metrics API

**推定工数**: 7-9 hours

---

#### 📅 Week 4 (2026-05-10 - 05-16)
**テーマ**: Interactive Charts

**タスク**:
1. **インタラクティブチャート (5-6時間)**
   - Equity curve (zoom/pan)
   - Drawdown chart
   - Position size history
   - Win/Loss ratio trend

2. **トレード詳細ビュー (3-4時間)**
   - Symbol ごとの entry/exit points
   - P&L waterfall chart
   - Hold duration distribution

**成果物**:
- Charts タブ拡張
- Trade detail view

**推定工数**: 8-10 hours

---

### Priority 3: Backtest & Optimization (1ヶ月)

#### 📅 Month 2 (2026-05-17 - 06-13)
**テーマ**: Backtest Framework

**Week 5-6 タスク**:
1. **バックテストエンジン (10-12時間)**
   - Historical data loader
   - Simulated execution
   - Performance metrics
   - Report generation

2. **バックテスト UI (6-8時間)**
   - Date range selector
   - Strategy selector
   - Parameter input
   - Results visualization

**Week 7-8 タスク**:
3. **パラメータ最適化 (8-10時間)**
   - Grid search
   - Walk-forward analysis
   - Optimization results display
   - Best parameters recommendation

**成果物**:
- Backtest engine
- Backtest UI
- Parameter optimization tool

**推定工数**: 24-30 hours

---

### Priority 4: Advanced Features (継続的)

#### 📅 Month 3+ (2026-06-14 以降)

**継続的改善タスク**:

1. **リスク管理強化**
   - VaR (Value at Risk) 計算
   - Expected Shortfall
   - Correlation analysis
   - Sector exposure monitoring

2. **Alert システム**
   - High drawdown alert
   - Position concentration alert
   - Low conversion rate alert
   - Anomaly detection

3. **機械学習統合**
   - Signal quality prediction
   - Exit timing optimization
   - Risk prediction model

4. **Portfolio Optimization**
   - Kelly criterion sizing
   - Markowitz optimization
   - Black-Litterman model

---

## 📅 推奨スケジュール (カレンダー形式)

### 2026年4月
| 日付 | タスク | 工数 | 状態 |
|------|--------|------|------|
| 4/25 | Week 1-2, Month 1 (T1-T12) | 6.5h | ✅ Complete |
| 4/26 | 運用確認・効果測定 | 2-3h | 🔜 Next |
| 4/27-28 | PnL 精度確認 | 1.5h/day | 🔜 Planned |
| 4/29-5/2 | 週次評価・T11拡張 | 4-5h | 🔜 Planned |

### 2026年5月
| 週 | テーマ | 工数 | 優先度 |
|----|--------|------|--------|
| Week 1 (5/3-9) | Performance Dashboard | 7-9h | 🔴 High |
| Week 2 (5/10-16) | Interactive Charts | 8-10h | 🔴 High |
| Week 3 (5/17-23) | Backtest Engine | 10-12h | 🟡 Medium |
| Week 4 (5/24-30) | Backtest UI | 6-8h | 🟡 Medium |

### 2026年6月
| 週 | テーマ | 工数 | 優先度 |
|----|--------|------|--------|
| Week 1-2 (6/1-13) | Parameter Optimization | 8-10h | 🟡 Medium |
| Week 3+ (6/14-) | Advanced Features | 継続 | 🟢 Low |

---

## 🎯 マイルストーン

### Milestone 1: 運用安定化 ✅
**期限**: 2026-04-25  
**状態**: Complete  
**成果**:
- Conversion rate 改善施策実装
- PnL 精度向上
- UI 拡張完了
- Parameter tuning 実装

### Milestone 2: 効果確認
**期限**: 2026-05-02  
**目標**:
- Conversion rate 20%+ 達成
- PnL 乖離 <10% 達成
- 1週間の安定運用

### Milestone 3: Console 強化
**期限**: 2026-05-16  
**目標**:
- Performance dashboard 完成
- Interactive charts 実装
- Real-time monitoring 稼働

### Milestone 4: Backtest 基盤
**期限**: 2026-06-13  
**目標**:
- Backtest engine 完成
- Parameter optimization 可能
- 戦略評価自動化

---

## ⚠️ 注意事項

### 毎日のルーチン (5分)
```bash
# 朝のチェック
curl -s http://localhost:3333/api/dashboard | python3 -c "
import json, sys
d = json.load(sys.stdin)
f = d.get('pipeline', {}).get('funnel', {})
dec = f.get('decisions', 0)
orders = f.get('orders_submitted', 0)
rate = orders / dec * 100 if dec else 0
print('Conversion: %.1f%% (%d/%d)' % (rate, orders, dec))
if rate < 20: print('⚠️ ALERT: Too low!')
elif rate < 30: print('⚠️ Warning: Below target')
else: print('✅ OK')
"
```

### 週次レビュー (30分-1時間)
- Conversion rate 推移確認
- PnL 精度確認
- Discrepancy 発生パターン分析
- Parameter 調整の検討

### 月次レビュー (2-3時間)
- 全体パフォーマンス評価
- 戦略別収益性分析
- 改善施策の効果測定
- 次月計画策定

---

## 📝 進捗管理

### 完了タスク
- [x] Week 1 (T1-T4)
- [x] Week 2 (T5-T8)
- [x] Month 1 (T9-T12)

### 進行中タスク
- [ ] 運用効果測定 (4/26-5/2)

### 計画中タスク
- [ ] Performance Dashboard (5/3-9)
- [ ] Interactive Charts (5/10-16)
- [ ] Backtest Engine (5/17-30)
- [ ] Parameter Optimization (6/1-13)

---

## 🎓 学習・スキルアップ

### 推奨学習項目
1. **Chart.js / Plotly.js** (Interactive charts 用)
2. **WebSocket / SSE** (Real-time updates 用)
3. **Backtest framework design** (Backtest engine 用)
4. **Optimization algorithms** (Parameter tuning 用)

### リソース
- Chart.js documentation
- Backtest framework examples (vectorbt, backtrader)
- Financial metrics calculation (Sharpe, Sortino, etc.)

---

**次のアクション**: 2026-04-26 朝、運用確認・効果測定を実施
