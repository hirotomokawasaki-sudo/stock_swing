# T22 Entry / Exit 一体改善の分析観点

## 目的
`breakout_momentum` の entry quality と `simple_exit` の exit quality を別々ではなく、組み合わせとして評価し、改善優先順位を明確化する。

## まず答えるべき問い
1. 良い entry を悪い exit で取りこぼしていないか
2. 悪い entry を exit が救っているだけになっていないか
3. symbol / regime ごとに相性の良い entry × exit の組み合わせがあるか
4. conversion を上げる施策が、exit 後の成績を悪化させていないか

## 分析軸

### 1. Entry quality × Exit outcome
各 trade を以下で集計する。
- entry strategy / version
- exit strategy / version
- signal_strength
- confidence
- decision → submission conversion
- hold days
- realized pnl
- max favorable excursion (MFE)
- max adverse excursion (MAE)
- exit_reason

見るポイント:
- 高 signal / 高 confidence なのに `stop_loss` 終了している比率
- 低 signal だが `take_profit` / 良好 exit している比率
- entry quality と最終損益の相関

### 2. Exit reason 別に見た entry の質
`exit_reason` ごとに entry 側の質を比較する。
- stop_loss に終わった trade の signal_strength / confidence 分布
- take_profit に終わった trade の signal_strength / confidence 分布
- trailing stop / max_hold のときの平均保有日数・平均損益

狙い:
- entry が悪いのか
- exit が早すぎる / 遅すぎるのか
を切り分ける。

### 3. Conversion 改善後の Exit 成績
T22 では conversion 改善が重要だが、通しやすくした結果の exit 成績悪化を確認する。
- deny → pass 化した trade 群のその後損益
- position_size_limit 緩和後の勝率 / 平均損益 / drawdown
- sector cap / symbol rotation 変更後の exit_reason 構成比

狙い:
- conversion 改善が単なる件数増で終わっていないか確認する。

### 4. Symbol 別の entry / exit 相性
銘柄ごとに以下を比較する。
- conversion rate
- avg realized pnl
- stop_loss 比率
- take_profit 比率
- hold days
- repeat entry frequency

特に確認対象:
- 集中しやすい銘柄
- stop_loss が連続しやすい銘柄
- breakout とは相性が悪いが、rotation 候補として残っている銘柄

### 5. Regime 別の entry / exit 相性
regime ごとに trade を分ける。
- bullish / neutral / cautious
- regime ごとの entry conversion
- regime ごとの exit_reason 構成
- regime ごとの avg pnl / hold days / drawdown

狙い:
- Bull では entry 閾値を緩め、Bear/Cautious では exit を早めるなどの判断材料を作る。

## 優先KPI
優先順は以下。
1. realized pnl
2. profit factor
3. stop_loss 比率
4. avg return per trade
5. conversion rate
6. hold days

## 先に見るべき組み合わせ
優先度順:
1. `breakout_momentum_v1/v2 × simple_exit_v2`
2. 高 signal だが deny された trade 群
3. stop_loss で終わった breakout trades
4. symbol 集中が強い銘柄（PLTR, PATH 系）

## 次の具体タスク
1. closed trades を entry_strategy × exit_reason で集計するスクリプトを作る
2. signal_strength / confidence / pnl / hold_days のクロス集計を出す
3. symbol別・regime別に stop_loss 偏重銘柄を特定する
4. その結果から
   - entry 側で絞るべきか
   - exit 側で trailing / stop を調整すべきか
   - symbol rotation を入れるべきか
   を優先順位づけする

## 暫定優先順位
- Priority 1: `stop_loss` 終了 trade の entry quality 分析
- Priority 2: conversion 改善後 trade の exit 成績確認
- Priority 3: symbol / regime ごとの相性分析

## 完了条件への対応
T22 の未完了条件である以下を満たすための観点を定義済み。
- Exit 戦略との組み合わせ分析観点を定義
- entry / exit 一体改善の優先順位を明確化
