# R14: 実装前契約と残課題（2026-10-20）

**状態: shadow-only維持。これは設計・受入テスト案であり、実装済みの主張でも
paper A/Bの開始許可でも、事前登録完了の主張でもない。**
正式ロードマップは `docs/console_improvement_tasks.md` のR14、昇格条件は
`docs/promotion_governance.md` を維持する。R22案全体は今回の承認対象に含めない。

## 実装順と受入条件

| 順序 | 対象 | 実装契約 | 必須の反証テスト | 現状 |
|---|---|---|---|---|
| 1 | chop gate | `risk/market_regime_indicator.py`を再利用する案。signal時点に利用可能な完了足だけで判定。欠損・古い足・未確定足は不適格。現行raw shadow候補を消さず別eligibility記録を残す | 将来足を追加しても過去判定不変、欠損で許可しない、非chopを不適格にする | 未実装。既存indicatorは観測用であり実証済みgateではない |
| 2 | Gate 3 | `risk/entry_filter.py`のrolling PF母集団をstrategy_idとenvironment_idで分離。同銘柄でも他戦略の損益を流用しない。既存momentumの判定は不変 | momentumの連敗を追加してもR14判定不変、逆方向も不変、既存戦略の回帰一致、ID欠損は勝手にR14へ帰属させない | 未実装 |
| 3 | 独立sub-ledger | 仮想cash/保有/予約資金/fees/realized・unrealized PnLをarm別に持つ。共通broker口座の残高を各armへ重複配分しない。観測と約定を区別する | 同一symbolの両arm保有、部分約定、取消、再起動、重複event、資金保存則、arm間汚染なし | 未実装。資本配分額も未確定 |
| 4 | 半導体30% projected cap | 既存の審査条件を実装する際は、個別株・ETF・全戦略の連結保有時価＋未約定BUY予約＋同runで先に許可したBUY＋今回候補を同一equityで評価。分類不能/価格欠損/equity不正なら新規riskを許可しない。SELLは妨げない | 30%境界、分割注文による上限迂回、既存超過、ETF重複分類、取消/部分約定、同時run、SELL維持 | 未実装。現行stock/ETF配分bandはこのセクターcapの代替にならない |
| 5 | A/B計画固定 | 同一時点・同一データ・同一コストでcontrol/treatmentを前向き比較。signal日でcluster化し、同日多数銘柄を独立日と数えない | cost二重控除なし、途中条件変更検出、holdout分離、片arm欠損を成績から除外して隠さない | 未完。数値条件と資本額の確定前には開始しない |

上の契約は今後のレビュー可能な実装仕様。特にchop閾値・資本額・停止損失額を、
今回の収集障害修復に紛れて決めたり有効化したりしない。

## A/B事前登録で埋める項目（未登録）

- 固定するコード/config hash、開始日、終了日、成熟horizon、最低独立signal日数。
- 共通capital/risk budget、control/treatmentの違い、約定/費用/slippage規則。
- 主比較はcost-adjusted期待値の差。precisionのみを勝敗条件にしない。
- 合格/継続/中止を分ける期待値差・下方尾・DD・集中・欠損率の**数値**。
- 同日cluster依存を扱う比較法と、単一日/単一銘柄を除いた頑健性確認。
- 経済性の既存ゲート `n>=30 & PF>1 & expectancy>0` は必要条件として維持。
  これだけではR14の追加価値・A/B有効性・昇格を証明しない。

数字を後から過去572候補に合わせて選ばない。現在のchoppy成熟候補は4 signal日へ
集中しており、新しい「10日」は独立した将来signal日で数える。過去の候補件数を
最低日数の代わりにしない。今回新しいhistorical variant探索は実施していない。

## 次の判定

- 定期実行復旧はR14の昇格条件ではない。既存のraw shadow観測だけ再開する。
- 実装・test・数値事前登録が完了し、成熟choppy signal日10日以上になってから
  promotion再審査の可否を検討する。これは昇格の十分条件ではない。
- 未達なら既存 **2026-11-17 09:30 JST** は継続コストと停止可否だけを確認する。
- 上記実装、本番配線、paper A/B、R13-C後OOSは未完として残す。HALT解除や
  economic NO-GOの例外扱いはしない。
