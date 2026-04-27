# SIMPLE_EXIT_V1 運用ドキュメント

## 概要
`simple_exit_v1` は、保有ポジションに対してシンプルなルールベースで売却判断を出す Exit 戦略です。主な目的は、損失拡大の抑制、一定利益の確定、および長期保有の固定化回避です。

## 現行ルール
実装上の基本パラメータは以下です。

- stop loss: **-7%**
- take profit: **+10%**
- max hold days: **5日**

## 判定ロジック
各保有ポジションについて、現在リターン率と保有日数を確認し、以下の順で売却判断を行います。

1. **損切り条件**
   - リターン率が -7% 以下なら売却候補
   - 例: `Stop loss triggered`

2. **利確条件**
   - リターン率が +10% 以上なら売却候補
   - 例: `Take profit triggered`

3. **最大保有日数条件**
   - 保有日数が 5日以上なら売却候補
   - 例: `Max hold period reached`

4. 上記に該当しない場合
   - 継続保有

## 現在の良い点
- ルールが明快で説明しやすい
- 売却理由を運用上説明しやすい
- 既に一定の Exit 成果が確認できている

## 現在の課題
- 全銘柄に固定の stop / target / hold days を当てており、銘柄特性差に弱い
- トレンド継続銘柄で早売りになる可能性がある
- Exit 成果の attribution は改善途中で、entry strategy と exit strategy の寄与分解は完全ではない

## 現在確認できている暫定成績
`simple_exit_v1` の過去 exit 実績 backfill 後、暫定 summary は以下です。

- closed trades: 24
- winning trades: 16
- losing trades: 8
- win rate: 66.67%
- total pnl: $1,508.77
- avg pnl: $62.87

## 今後の改善方針
### Phase 1: 見える化
- closed trade に `exit_strategy_id` を確実に保存
- `exit_reason` を保存
- コンソールで exit reason 別成績を表示

### Phase 2: ルール高度化
- 銘柄特性やボラティリティに応じて stop / target を可変化
- max hold を固定日数だけでなく状態ベースへ拡張
- partial exit / trailing exit を検討

### Phase 3: Exit 戦略の高度化
- trend weakening
- market regime deterioration
- news deterioration
などを取り込んだ richer な exit 判断へ発展させる

## 運用上の位置づけ
現時点の `simple_exit_v1` は、堅実で説明可能性の高いベースライン Exit 戦略です。今後の改善は、まず可視化と attribution の整備、その後にパラメータとルールの最適化を進めるのが望ましいです。
