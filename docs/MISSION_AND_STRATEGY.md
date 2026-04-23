# Mission & Strategy - stock_swing

**最終更新:** 2026-04-23 10:26 JST  
**ステータス:** Week 2完了、Week 3開始準備完了  

---

## 🎯 **Mission（使命）**

### **Primary Mission:**
```
米国株・ETFのイベント駆動スイングトレードにより、
安定的かつ持続可能なリターンを生成する
システマティックトレーディング基盤を構築する
```

### **Core Values:**
1. **データドリブン** - 感情ではなくデータに基づく意思決定
2. **リスク管理優先** - 利益よりも資本保全を重視
3. **継続的改善** - 週次での検証・最適化サイクル
4. **透明性** - すべての意思決定を記録・追跡可能に

---

## 🎯 **目標（Goals）**

### **短期目標（1ヶ月 - 2026年5月末）:**

**財務目標:**
```
Starting:  $100,000
Target:    $112,000 - $115,000
Return:    +12-15%
Sharpe:    1.5 - 1.8
Max DD:    -8% 以下
```

**達成手段:**
- ✅ Week 3: パラメータ最適化（+10-15%改善）
- ✅ Week 4: Kelly Criterion導入（+5-10%改善）
- ⏳ Week 5: Tax最適化フレームワーク
- ⏳ Week 6-7: 検証・微調整

**マイルストーン:**
- Week 3完了時: Sharpe 1.2+, 実行率55%+
- Week 4完了時: Sharpe 1.5+, Return +8-10%
- 1ヶ月後: Sharpe 1.8, Return +12-15%

---

### **中期目標（3ヶ月 - 2026年7月末）:**

**財務目標:**
```
Target Return: +30-35%
Target Sharpe: 2.0+
Max Drawdown:  -10% 以下
```

**実装フェーズ:**
- Phase 1（1ヶ月）: 基礎最適化完了
- Phase 2（2-3ヶ月）: 高度戦略追加
  - Alternative Data統合
  - ML Signal Quality分類
  - Intraday Entry最適化

---

### **長期目標（1年 - 2027年4月）:**

**財務目標:**
```
Target Return: +60-80%
Target Sharpe: 2.0+
目標資金:      $160,000 - $180,000
```

**戦略進化:**
- 複数戦略ポートフォリオ
- 機械学習統合
- リアルタイム最適化
- 特許取得（3-5件）

---

## 🎲 **戦略（Strategy）**

### **現在の戦略構成:**

#### **1. Entry Strategies（エントリー戦略）**

**BreakoutMomentumStrategy（主力 - 90%+）**
```python
目的:     短期モメンタムブレイクアウトを捕捉
シグナル: 3%以上の価格上昇 + 強度55%以上
保有期間: 3-5日
実績:     高頻度シグナル、安定実行
```

**Parameters:**
```python
min_momentum: 0.03          # 3%以上のモメンタム
min_signal_strength: 0.55   # 最低シグナル強度
```

**EventSwingStrategy（補助 - <5%）**
```python
目的:     決算・ニュースイベント駆動の取引
シグナル: Finnhubニュース + センチメント分析
実績:     低頻度、高品質シグナル
```

---

#### **2. Exit Strategy（出口戦略）**

**SimpleExitStrategy**
```python
目的:     利益確定とリスク制限
条件:
  - Stop Loss:    -7%（損失カット）
  - Take Profit:  +10%（利益確定）
  - Max Hold:     5日（時間制限）
```

**実績:**
- Stop Loss発動率: 約40%
- Take Profit達成率: 約30%
- 時間切れ: 約30%

---

#### **3. Risk Management（リスク管理）**

**Position Sizing（ポジションサイズ）**
```python
max_risk_per_trade_pct: 0.5%    # 1取引あたり0.5%リスク
max_position_notional_pct: 8%   # 最大8%/ポジション
max_sector_exposure_pct: 50%    # セクター集中50%制限
```

**Exposure Limits（エクスポージャー制限）**
```python
REGIME_LIMITS = {
    "bullish":  0.95,  # 強気時95%
    "neutral":  0.85,  # 中立時85%
    "cautious": 0.65,  # 慎重時65%
}
```

**実績:**
- 平均エクスポージャー: 70-75%
- 最大ドローダウン: -4.34%
- セクター分散: 2-3セクター

---

### **対象ユニバース:**

**Stocks（個別株 - 48銘柄）**
```
カテゴリ:
- AI/Semiconductor: NVDA, AMD, MU, MRVL, AVGO等
- Enterprise Software: CRM, NOW, SNOW, PLTR, DDOG等
- Cybersecurity: PANW, CRWD, FTNT等
- Cloud Infrastructure: MSFT, GOOGL, AMZN等
```

**ETFs（16銘柄 - 監視のみ）**
```
Semiconductor: SOXQ, SOXX, SMH, FTXL
Tech Sector: QTEC, SKYY, PTF等

現状: シグナルほぼなし（モメンタム閾値に届かず）
方針: 監視継続、積極的購入は不要
```

---

### **実行フレームワーク:**

**Daily Execution（1日4回）**
```
23:25 JST - Pre-market preparation
23:35 JST - Market open execution
02:00 JST - Mid-session check
05:55 JST - Market close execution
```

**Decision Process:**
```
1. Kill Switch確認（緊急停止チェック）
2. Market Hours確認（取引時間内か）
3. データ収集（価格、ニュース、マクロ）
4. Feature計算（モメンタム、レジーム検知）
5. シグナル生成（Entry + Exit）
6. リスク検証（エクスポージャー、セクター）
7. 注文実行（Alpaca API経由）
8. P&L追跡（取引記録）
```

---

## 📊 **現在のパフォーマンス（Week 2終了時）**

### **累計（19営業日）:**
```
Starting Capital:  $100,000
Current Equity:    $102,982（最新: $104,477）
Total Return:      +2.98%
Sharpe Ratio:      0.85
Max Drawdown:      -4.34%
Total Trades:      110
Win Rate:          推定55%（要計算）
Avg Hold Time:     3-5日
```

### **戦略別貢献:**
```
BreakoutMomentum:  90%+ of returns
SimpleExit:        リスク管理（損失制限）
EventSwing:        <5% of returns
```

### **セクター別:**
```
Software:          46.7%（最大配分）
Semiconductors:    19.2%
Other:             6.5%
```

---

## 🚀 **今後の戦略進化（Next 4 Weeks）**

### **Week 3（Apr 24-28）: Parameter Optimization**

**目的:**
```
既存戦略のパラメータを最適化し、
実行率とリターンを大幅に改善
```

**実施内容:**
1. Backtest engine実装
2. Parameter grid search（1,600組み合わせ → 150-200に絞る）
3. Walk-forward validation
4. 最適パラメータ選定・適用

**期待効果:**
```
Return:     +2.98% → +6-8%（19日換算）
Sharpe:     0.85 → 1.2
Execution:  18% → 55-65%
年率換算:   +45% → +55%
```

---

### **Week 4（Apr 29 - May 5）: Kelly Criterion**

**目的:**
```
シグナル信頼度に基づいて
ポジションサイズを動的に最適化
```

**実施内容:**
1. Win rate / Avg win-loss ratio計算
2. Kelly Criterion formula実装
3. Signal confidence統合
4. Position sizing適用

**Kelly Formula:**
```python
f* = (p*b - q) / b

Where:
  f* = optimal position fraction
  p  = win probability
  b  = avg_win / avg_loss
  q  = 1 - p
```

**期待効果:**
```
Return:     +6-8% → +8-10%
Sharpe:     1.2 → 1.5
年率換算:   +55% → +65%
```

---

### **Week 5-7（May 6-26）: Validation & Tax Framework**

**実施内容:**
1. Tax optimization framework（税効率化）
2. Out-of-sample validation（未知データ検証）
3. Edge case対応
4. Performance monitoring強化

**期待効果:**
```
Return:     +8-10% → +10-12%
Sharpe:     1.5 → 1.6-1.8
年率換算:   +65% → +75%
```

---

## 🎯 **成功の定義**

### **Week 3成功条件:**
```
✅ Backtest engine動作
✅ 最適パラメータ選定完了
✅ Sharpe 1.2以上達成
✅ 実行率55%以上
✅ ドキュメント完備
```

### **1ヶ月後成功条件:**
```
✅ Return +12-15%達成
✅ Sharpe 1.5-1.8達成
✅ Max DD -8%以下
✅ Kelly Criterion稼働
✅ 週次レビュー実施
```

### **1年後成功条件:**
```
✅ Return +60-80%達成
✅ Sharpe 2.0以上
✅ 資金$160k-180k達成
✅ 複数戦略稼働
✅ 特許出願完了
```

---

## ⚠️ **リスクと対策**

### **主要リスク:**

**1. 市場リスク（-30%クラッシュ）**
```
対策:
- ETF避難戦略（VIX>30時）
- ポジション削減（50%カット）
- Stop Loss厳格化（-5%）
```

**2. パラメータオーバーフィット**
```
対策:
- Walk-forward validation
- Out-of-sample testing
- 複数期間での検証
```

**3. システムバグ**
```
対策:
- 自動テスト強化
- Daily monitoring
- Git commit必須化
```

**4. データ品質問題**
```
対策:
- Broker API直接参照
- Reconciliation自動化（15分ごと）
- P&L tracking改善
```

---

## 📈 **Key Performance Indicators (KPIs）**

### **Daily Monitoring:**
```
- Equity変化
- Open positions数
- 新規シグナル数
- 実行率
- Exposure %
```

### **Weekly Review:**
```
- 週次リターン
- Sharpe ratio
- Max drawdown
- Win rate
- Avg hold time
- セクター分散
```

### **Monthly Audit:**
```
- 月次リターン
- Sharpe vs target
- パラメータ最適性
- 戦略貢献度
- リスク指標
```

---

## 🔄 **継続的改善サイクル**

### **PDCA Cycle:**

**Plan（計画）:**
- 週次目標設定
- パラメータ仮説立案
- 実装計画作成

**Do（実行）:**
- Backtest実施
- パラメータ適用
- Live trading監視

**Check（確認）:**
- Performance分析
- リスク評価
- KPI達成度確認

**Act（改善）:**
- 問題点修正
- 戦略調整
- ドキュメント更新

### **週次レビュー:**
```
毎週月曜日:
1. 前週パフォーマンス確認
2. 問題点抽出
3. 改善策立案
4. 今週目標設定
```

---

## 🎓 **学習と成長**

### **技術スキル向上:**
```
- Backtesting技術
- 統計的検証手法
- リスク管理理論
- 機械学習（Phase 2）
```

### **知的財産構築:**
```
- 特許出願（3-5件）
- 技術文書作成
- システム特性分析
- ライセンス戦略
```

### **コミュニティ貢献:**
```
- オープンソース化（将来）
- 技術ブログ執筆（任意）
- 学術論文（検討中）
```

---

## 📋 **意思決定原則**

### **取引決定:**
```
1. データ優先（感情排除）
2. リスク管理第一
3. 統計的優位性確認
4. 記録・追跡可能性
```

### **戦略変更:**
```
1. Backtest検証必須
2. Out-of-sample確認
3. 段階的ロールアウト
4. Rollback plan準備
```

### **緊急対応:**
```
1. Kill switch即時起動
2. ポジション削減優先
3. 原因分析後再開
4. 再発防止策実施
```

---

## 🏆 **成功への道筋**

### **現在地（Week 2完了）:**
```
✅ システム安定稼働
✅ +2.98% return達成
✅ データ蓄積完了
✅ Week 3準備完了
```

### **Next Milestone（Week 3完了時）:**
```
🎯 Sharpe 1.2達成
🎯 実行率55%達成
🎯 最適パラメータ確定
🎯 +6-8% return達成
```

### **Final Goal（1ヶ月後）:**
```
🏆 Sharpe 1.5-1.8達成
🏆 +12-15% return達成
🏆 Kelly Criterion稼働
🏆 持続可能な運用基盤確立
```

---

## 📞 **Contact & Resources**

**Repository:** https://github.com/hirotomokawasaki-sudo/stock_swing.git  
**Runtime Mode:** Paper Trading（Alpaca Paper API）  
**Primary Language:** Python 3.13  
**Framework:** Custom (stock_swing)  
**AI Assistant:** Claude Sonnet 4.5（OpenClaw）  

---

**Last Updated:** 2026-04-23 10:26 JST  
**Status:** Week 3 Ready ✅  
**Next Action:** Week 3 Day 1 - Backtest Engine Implementation  

---

End of Mission & Strategy Document
