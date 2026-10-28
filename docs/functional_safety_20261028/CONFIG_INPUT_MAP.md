# 実効設定・次の検証入力の対応表

対象はbase8909e79と本packetのK03候補。**コード既定値、今回の合成CLI値、実運用runの値を区別する**。この表は全設定消費の記録完成や、実運用のas-of入力認定ではない。

## 設定と呼出元

| 対象 | 参照元/優先関係 | 今回の根拠・残り |
|---|---|---|
| Breakout momentum閾値 | paper_demo CLI→BreakoutMomentumStrategy。CLI既定0.05、min_signal_strength既定0.60。class単体のstrength既定0.40はCLI実行値ではない | 実CLI fixtureは0.01/0.1。momentumを0.99へ変えると候補消失。wrapperは0.05を明示するが、当時のautomation payload/env/argv receiptは今回再確認していない |
| breakout/event YAML | config/strategy/breakout_momentum_v1.yaml、event_swing_v1.yamlは入口constructに未接続 | 両YAMLをenabled:false/max_hold_days:999へ変更しても今回のBUY判断は同じ。event発火や全flagの動的影響までは検証していない。volume/filing/insider等を接続に便乗してONにしない |
| 保有日数/出口 | paper_demoがsimple_exit_v2.yamlをsafe_loadし個別.get値をconstructorへ。現fileのmax_hold_days20、欠損時既定20 | 入口YAMLの2/3日は未使用。出口file欠損のCLIは成功、null YAMLはAttributeErrorで中断。個別出口/lot時計の効果検証ではない |
| risk budget | risk_budget.py定数WARN0.04/BLOCK0.06、entry_strengthからstop推定0.05/0.08/0.09 | K03候補は値を変えず旧5/8%表示を訂正。欠損/破損/非有限値はunknown。skip envは計測済み値の閾値overrideだけ |
| cluster上限 | correlation_cluster.py DEFAULT_CLUSTER_CAPS。cloud0.35等 | 既存保有だけを入力とし購入額/pending/予約を含まない限定経路を再現。研究C11のcap30%とは別 |
| その他の入口制約 | allocation YAML/registry、EntryFilterConfig環境変数、同銘柄cooldown、runtime、PF/CB等 | 本修正で閾値/ON-OFF変更なし。全env/default閉包とrunごとの消費receiptは旧記録候補の未完範囲を引き継ぐ |

## 次の成績検証に必要な入力

| 入力 | 現在使えるもの | 不足・影響・最小の次作業 |
|---|---|---|
| 全候補/見送り/no-signal | 10/28固定診断のdecision/feature snapshot | 全候補分母と時点資格は未認定。約定部分の良いスコア帯を採用しない。既存最小記録経路でcoverageを表示する |
| entry→fill→exit/outcome | 固定診断では入口score197/422行 | 225行を推定補完しない。復元可能な参照だけ照合し、未復元行/部分exitを分離する |
| 設定・版・時刻 | 本packetのcode/config hash、合成CLI入力 | 実runのargv/env消費版、feature利用可能時刻、判断前受信/足終端は未認定。記録済み参照の資格照合が必要 |
| 初期lot/現金/保有 | 既存入力候補、今回の合成broker/空台帳 | 全lot/数量/通貨・初期資本の同一時点照合、brokerとの完全性は未認定。空JSONを実口座flatと同一視しない |
| pending/予約/購入後上限 | 既存allocatorのprojected-band部品 | cluster用のsizing後notional、同batch累積、取消/部分約定/拒否/再開での解放/復元が必要。K01全体は未完 |
| 銘柄別意図・帰属 | 別戦略の判断ID/strategy_id | K02の集約数量/SELL優先/競合解消は未決。自動nettingせず、選ばれない意図の根拠/帰属も保持する仕様へ |
| 価格・費用・評価窓 | 既存provider隔離候補、5bps等の研究仮定 | 実価格basis/受信版/執行可能時刻、IBKR正式費用、較正U/epsilon/delta/標本期間は未確定。新たな収益計算はしていない |

担当はエージェント。**10/30 18:00 JST**に現行仕様/不足/政策案を提出し、既存**11/06**の一次結論は保留を含め延期せず提出する。全過去履歴修復・全K完了・IBKR完成を独立研究の一律前提にしない。
