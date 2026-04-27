# BREAKOUT_MOMENTUM_V1 運用ドキュメント

## 概要
`breakout_momentum_v1` は、上昇モメンタムが明確な銘柄を選別し、一定のシグナル閾値・信頼度・リスク制約の下で買いエントリーを行う主力戦略です。現在の stock_swing における主要な entry strategy として機能しています。

## 戦略の基本思想
- 強い上昇継続が期待できる銘柄のみを選ぶ
- ノイズの多いシグナルや弱い候補は deny / review で見送る
- 口座全体のリスクと銘柄集中度を守りながらサイズを決める

## 現行の実質ルール
### エントリー判断
- momentum / breakout 条件を満たすこと
- `signal_strength` が最低基準を上回ること
- `confidence` が最低基準を上回ること
- risk validator を通過すること
- 実行可能な position size が算出できること

### リスク制約
- max position size
- symbol position limit
- total exposure
- sector exposure
- 既存保有との重複制御

## 現在の良い点
- シンプルで説明しやすい
- 実際に主要な利益源として機能している
- deny / review で見送りやすく、暴走しにくい

## 現在確認できている代表成績
分析タブ/API 上の主要値として、現時点で以下の実績が確認できています。

- total trades: 44
- win rate: 63.64%
- total pnl: $4,292.74
- profit factor: 5.49
- sharpe ratio: 0.508

## 現在の課題
- threshold が比較的固定で、相場レジーム差を吸収しにくい
- 銘柄群ごとのボラティリティ差を十分に反映していない
- deny / reject 理由を改善ループへ十分還元できていない
- Exit 戦略との組み合わせ最適化がまだ弱い

## 今後の改善方針
### Phase 1: 可視化強化
- deny / reject reason の集計強化
- conversion の symbol / strategy 別深掘り
- signal_strength / confidence 分布の観測

### Phase 2: v2 エントリー最適化
- regime-aware thresholds
- volatility-aware thresholds
- symbol group 別パラメータ

### Phase 3: Exit と一体最適化
- `simple_exit_v1` との組み合わせ分析
- どの entry が take profit / stop loss / max hold に流れやすいかを計測
- Exit 側の改善と一体で期待値を最適化

## 運用上の位置づけ
現時点の `breakout_momentum_v1` は、stock_swing の主力エントリー戦略です。今後は deny/conversion の可視化、相場レジーム対応、銘柄群別最適化を進めつつ、Exit 戦略と一体で改良することで収益性向上が期待できます。
