# 凍結した現行ソースの入口・順位・出口の対応

本表は2026-10-28の現行ソースの読取結果。過去の全実効設定や各runの価格入力の再現ではない。実ファイルはinputs.zip内にhash固定した。

| 工程 | 凍結パスと関数/呼出し | 確認事項 |
|---|---|---|
| 入口 | `strategy_engine/breakout_momentum_strategy.py:generate` | 品質flag、momentum/trend、macro補正後の強度下限で候補化。rawはmomentum/.20、正規化は上限処理とmacro補正。raw>1は仕様であり異常値ではない |
| イベント入口 | `strategy_engine/event_swing_strategy.py` | イベントまでの日数、momentum/trend、macroによる補正。breakoutとは別戦略として集計 |
| 実入口設定 | `cli/paper_demo.py`のargparse/strategy構築 | CLI既定はmin-momentum=.05、min-signal-strength=.60。クラス既定の強度.40を実効値と誤認しない。各runの上書き・履歴版は別途確認 |
| intraday | `cli/paper_demo.py`のenhanced_breakout_signals | 日足由来の候補に分足確認でstrength×1.2/上限1を適用する経路。metadataの正規化前/後と最終値を区別。本保存集合ではこの版IDは観測なし |
| 順位 | `utils/signal_prioritization.py:annotate_cross_sectional_percentile` | 同じrunのstrictly-lower比率で同点は同順位。単独候補は1。同点満点が識別できるという意味ではない |
| 優先/除外 | `cli/paper_demo.py`から`prioritize_buy_signals_v2`→decision_engine | 分散/既存保有/資金等の影響が入る。スコアだけの順序と実行順序は別 |
| 保存 | `cli/paper_demo.py`のall_signalsループ→`FeatureSnapshotStore` | 順位付け/優先処理後のsignalを保存。生成条件不成立の全銘柄やraw OHLCV全体の保存ではない。今回192runは記録nと保存買い候補数が一致 |
| 出口の結合 | `simple_exit_v2_strategy.py:_resolve_thresholds` | 入口強度の.65/.85区分で基礎stop/trailing条件が変わる実装。volatility補正等も存在。高スコア群の損益差を入口予測力だけへ帰属させない。stop幅はギャップ時の損失上限ではない |
| 旧分析関数 | `scripts/analyze_signal_strength_decile.py` | 件数で10分割するため同じ強度も分割される。pseudo-calibrationと結果後の最良閾値推奨を採否へ流用しない。本検証ではmainを実行せず対象関数だけ抽出 |
| 未実行builder | `scripts/build_post_signal_outcomes.py` | 外部取得と原本CSV上書きを伴い、今回の隔離・固定入力という条件にはそのまま適合しない。オンラインmainは呼んでいない |

これは新しいスコア方式・exit方式の提案/実装ではない。記録不足を埋めるために新DBや全旧履歴replayを先行構築しない。
