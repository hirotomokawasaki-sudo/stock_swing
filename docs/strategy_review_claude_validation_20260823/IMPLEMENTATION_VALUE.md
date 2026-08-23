# Implementation Value Review

以下はClaudeに評価させるための**初期仮説**です。承認済み実装計画ではありません。

| 改善案 | 期待価値 | 工数 | 挙動変更リスク | 初期判定 |
|---|---:|---:|---:|---|
| dry-runとscheduled paper証跡の分離 | 非常に高い | 低～中 | 低 | IMPLEMENT_NOW |
| cron最新run statusの実評価 | 高い | 低 | 低 | IMPLEMENT_NOW |
| paper 3日gateをsuccessful scheduled runに変更 | 高い | 低～中 | 低 | IMPLEMENT_NOW |
| promotion PFをattributable/cost-adjustedへ分離 | 高い | 低 | 低 | IMPLEMENT_NOW |
| top5/equity、top5/gross、gross/equity、HHIの分離 | 高い | 中 | 低 | IMPLEMENT_NOW |
| R11をt+1 execution・資金制約付きで再構築 | 非常に高い | 高 | 研究基盤のみ中 | IMPLEMENT_NOW |
| point-in-time universe/corporate action対応 | 高い | 高 | 研究基盤のみ中 | R11再構築に含める |
| signal_strengthとstop/sizingの切り離し | 高い可能性 | 中 | 高 | PAPER_AB_FIRST |
| high-confidence sizing no-opの整理 | 中 | 低 | 中 | PAPER_AB_FIRST |
| strategy名・unused YAMLの契約整理 | 中 | 低 | 低 | IMPLEMENT_NOW |
| ETF rotation独立戦略 | 中～高 | 高 | 本番前は低 | RESEARCH/SHADOW |
| JP overnight spillover | 中～高 | 中～高 | 本番前は低 | SHADOW継続 |
| shock mean reversion | 不明 | 高 | 高 | DEFER |

## 価値が高いが「収益を直接増やさない」改善

証拠provenance、promotion母集団、backtest時系列の修正は、取引シグナルを直接改善
しません。しかし、誤ったGOや偽のedgeに資金を投入する確率を下げるため、期待損失の
削減価値があります。Claudeには「利益改善」と「意思決定品質改善」を別採点させます。

## 挙動変更前にA/Bが必要な改善

signal_strength連動のstop幅を即時削除すると、既存ポジションのexit分布が変わります。
コード上の根拠が弱いことと、即座に本番挙動を変えることは別問題です。

推奨比較:

- Control: 現行score-linked stop/trailing
- Variant: uniform stop/trailing、scoreは観測のみ
- 評価: net PnLだけでなくmax DD、CVaR、stop後5/10/20日regret、turnover、gap loss

## R11-v2の最低要件候補

- signal at t close → fill at t+1 open/VWAP
- conservative OHLC pathでstop/trailingを再生成
- point-in-time universe
- split/dividend/delisting処理
- cash、gross exposure、sector/cluster cap
- spread/slippage/impact
- rolling walk-forward＋embargo
- 全trial registry
- paper fillとのreconciliation

この全てが常に必要とは限りません。Claudeには「結論を変え得るもの」から最小構成を
選ばせてください。

