# 投資システム機能比較・不足確認（2026-10-28）

## 1. 結論と対象

**売買シグナル・数量計算・リスク制限・売却・約定照合・実績集計・研究の大分類は揃っている。ただし、機能間の境界を含む完成度は不足している。追加指標や戦略数より、注文の同一性、実際に使える資金、企業行動、シグナルの寿命、集中リスク分類を先に明確化すべきである。**

- 対象は米国の通常個別株・通常ETFのロング中心スイング。現行Paper経路を読み、隔離研究・未配備修正は別扱いとした。[戦略範囲](policies/STRATEGY_SCOPE.md)
- 読取基準は作業ツリーとHEAD `8909e79c1a83e04d508715b132575625454b7856`。古いMission文書の目標年率や実装説明を現在の実績・実効設定として採用しない。
- 比較中に既存計画4文書の更新を検出したため、最新§3.38と[K03隔離是正](functional_safety_20261028/README.md)を再読した。K03の2経路には隔離修正・検証済み成果があるが通常側未配備、K01/K02/K04は限定再現/不足整理が中心、という区別を本比較でも維持する。既存計画は上書きしない。
- 比較対象はQuantConnect LEAN、NautilusTrader、IBKR TWS APIの公式資料（2026-10-28参照）。代表的な研究/運用基盤2系統とブローカーAPI1系統の**機能比較**であり、全製品調査や収益優位性の実測比較ではない。
- 方法は公式仕様とソース/既存検証資料の照合、およびASTによる型・引数・静的分類の確認。比較先の起動、実口座照会、注文送信、バックテストの追加探索は行っていない。
- 以下のC01〜C09はこの比較の所見番号であり、新しい実装タスク・利益仮説・承認済み試行を追加する番号ではない。

## 2. 比較対象から何を確認したか

| 対象 | 比較した機能 | 比較の限界 |
|---|---|---|
| QuantConnect LEAN | 銘柄選定→予測→目標保有→リスク→執行の分離、信号の有効期間、企業行動、余力/受渡・約定/費用モデル | モデルやデータの選択が必要。採用するだけでバックテストの現実性・収益性が保証されるわけではない |
| NautilusTrader | 注文/保有状態、応答不明・起動/継続時の照合、商品精度、研究/実運用でのロジック共有 | アダプター・設定・履歴範囲に依存。公式資料も永続化と送信の原子性やバックテストと実運用の相違を明記している |
| IBKR TWS API | 口座余力・受渡済現金などの区別、部分約定/注文状態、親子の利確・損切り注文 | 戦略研究システムではない。利用口座・商品・注文方式・稼働条件の確認が別途必要 |

根拠：[LEAN構成](https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/overview)、[LEAN現実性モデル](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/key-concepts)、[Nautilus実運用の境界](https://nautilustrader.io/docs/latest/concepts/live/)、[IBKR口座項目](https://www.interactivebrokers.com/docs/tws-api/doc/accounts/summary)。移行や有料データ購入を推奨・実行したものではない。

## 3. 購入から評価までの機能網羅性

「あり」は当該部品の存在を意味し、効果検証済み・十分な運用品質という意味ではない。

| 段階 | 機能 | 現行の確認結果 | 不足の位置 |
|---|---|---|---|
| 対象選定 | 銘柄台帳・対象商品の制限 | registry、通常株/ETFの対象、非IT等shadowあり | 当時の選定集合/除外履歴の完全性は別。C06 |
| 入力 | 価格・出来高・ATR・日中足 | 取得、fallback、品質flag、数量用価格の鮮度検証あり | 供給元/時間足/調整基準/完了時点の同値性は未完。K04/K05/P4 |
| 情報 | 決算予定・マクロ・ニュース等 | 取込と一部の売買接続あり | 実装/有効/実行/追加価値を分ける。K12 |
| 購入判断 | モメンタム・イベント信号 | 主力2戦略あり | スコア飽和/較正未認定。K06 |
| 信号管理 | 有効期限・撤回・根拠更新 | 生成時刻/想定保有期間あり | 発注期限・撤回との共通契約を確認できず。C04 |
| 候補統合 | 戦略競合・買い増し・優先配分 | 優先付け、cooldown等あり | 同一銘柄/相関した複数信号の統合不足。K02/K10/K11 |
| 数量 | リスク/単銘柄/総露出/業種上限 | sizing部品あり | 実exitとの整合、既定増額のno-op、実余力/予約。K09/C02 |
| 口座 | 利用可能現金・受渡・予約資金 | 口座取得、equity、buying_powerの表示あり | 実効sizing入力に受渡済現金等の契約がない。C02 |
| 集中管理 | 業種/相関群/株ETF配分 | 静的clusterとprojected株ETFバンドあり | clusterの分類漏れ・発注後/同batch、ETF中身。K01/C05 |
| 発注 | 市場/指値・注文識別 | 汎用APIはmarket/limit、通常生成は成行DAY | 指定重複防止ID・結果不明状態の復旧。C01 |
| 執行後 | 約定・部分約定・取消・再照合 | Reconciler、fill台帳、pending SELL等あり | 既知broker IDの照合と受付応答喪失の回復は別。C01/C07 |
| 保有管理 | lot・買い増し・期限 | lot情報、買い増し/期限関連部品あり | 最古lot時計/全量売却、per-lot修正OFF。K08/K10 |
| 売却 | 初期stop・trailing・建値・期限 | ソフトウェア売却ルールあり | 分岐重複・到達性、停止時保護。K08/C08 |
| 例外 | 障害・停止・kill switch | circuit breaker、監査、手動復帰等あり | 未知をゼロ/拒否確定と扱わない契約、監視空白。K03/C01/C08 |
| 企業行動 | split・配当・銘柄変更/廃止 | split検知/再構築、研究bookの分配計算あり | 通常売買/注文/資金/評価を通すライフサイクル。C03 |
| 評価 | 損益・PF・DD・benchmark等 | 台帳/比較/分析部品あり | 正式時価評価と入力品質、分配込みの寄与説明。C03/C09 |
| コスト | 手数料・slippage・資金容量 | コスト定義・感度/記述分析あり | 注文時価格と実fillのTCA、数量依存容量。C07 |
| 改善 | 診断・比較・試行台帳・昇格 | walk-forward/台帳/ガバナンス/計画あり | 同条件比較→独立証拠→採否の実行は未完。C09/K13/S1〜S6 |

## 4. 優先して明示すべき不足9点

### C01：発注受付の応答が不明な場合の復旧【最優先】

**足りない機能**：一つの発注意図を再起動・再試行後も同じ注文として識別し、受付結果不明のまま重ねて発注しないこと。

- 現行`BrokerClient.submit_order`とProtocolには発注時指定の`client_order_id`等がない。`submit_order → fetch → _fetch_with_retry → retry_with_backoff`を通り、POSTもtimeout/connection/5xx等の再試行対象となる。
- PaperExecutorの同一decision拒否はメモリ内。broker呼出し後にsubmissionを作成し、例外は`rejected`として返す。Reconcilerの当該入口には`broker_order_id`が必要である。
- したがって「brokerは受付済み、応答だけ喪失→再POST」の二重発注余地と、「未受付」と「結果不明」の混同が**静的に確認できる設計上の懸念**。実際の重複約定・発生頻度・損失は未確認。
- fill台帳の重複計上防止、注文取得/再照合、隔離された会計journalは既存であり、「注文管理全体がない」とは言わない。約定後の重複計上防止は、発注そのものの重複防止の代替ではない。

**最小受入条件案**：brokerに適合した安定ID/検索手段、必要最小限の送信前意図記録、結果不明状態、同一意図の照会/回復、再起動・応答喪失・取消競合時に追加発注しない検証。ブローカーを越える無条件なexactly-once保証とはしない。K02/K03/K14・既存移行受入へ補足する。

根拠：`sources/broker_client.py:117,491,643`、`sources/base.py:67`、`sources/retry.py:56,88`、`execution/paper_executor.py:129,225,304`、`execution/reconciler.py:91`（基点`src/stock_swing/`）。比較：[Nautilus注文照合](https://nautilustrader.io/docs/latest/concepts/execution/reconciliation/)、[送信と永続化の限界](https://nautilustrader.io/docs/latest/concepts/live/)。他システムも設定なしで原子的永続化を保証すると解釈しない。

### C02：購入可能な資金・受渡・予約の一貫管理【高／実口座接続前に確認】

**足りない機能**：「保有額を増やしてよい」と「この口座で今この注文を買える」を分け、同時注文/部分約定/取消後の利用可能額を更新すること。

- 現行sizingはequity・既存露出・業種・単銘柄・stop等で数量を算出。`PositionSizingInputs`にcash/settled cash/available funds/注文予約残はない。CLIでbuying_powerは取得・表示されるが、当該sizingへ渡されない。
- 株/ETFの発注後バンド更新は存在する。これを全制約・受渡済現金・手数料・未約定予約の一貫管理と同一視しない。
- 独立研究bookにはcash/予約を扱う成果がある。新しい資金管理エンジンをゼロから作らず、必要な契約を再利用する。

**最小受入条件案**：対象口座の資金ルールを確定し、brokerが示す利用可能資金、必要時の受渡済残、既存予約、価格/手数料余裕を使う。部分約定・取消の確定に応じて予約を解放。口座種別未確認のまま受渡日数・信用余力を決めつけない。K01/K09/K14・移行最小受入へ。

根拠：`risk/position_sizing.py:123`、`execution/paper_executor.py:325`、`cli/paper_demo.py:835`。比較：[IBKR口座項目](https://www.interactivebrokers.com/docs/tws-api/doc/accounts/summary)、[LEAN受渡モデル](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/settlement/key-concepts)。

### C03：企業行動と配当込み損益のライフサイクル【高】

**足りない機能**：配当/分配・分割/併合・銘柄変更/廃止を、保有数量/原価、価格系列、未約定注文、資金、戦略収益へ一貫して反映すること。

- `check_corporate_actions.py`のsplit/逆split異常検知、再構築時のforward split価格調整がある。全面未対応ではない。
- [rotation研究](rotation_research_20261022/README.md)は分配受取権・支払仮定・split・独立cash/lotを扱っている。ただし研究用の凍結計算であり通常の売買系に接続された証明ではない。
- 通常側の`equity_bridge_reconciliation.summarize_account_activities`はFEEを分け、FILL/SPLIT以外のnet額を`external_cash_adjustment`へ集計する。配当を入金と区別して戦略収益へ帰属させる仕組みとしては不十分。実際に配当が失われた/全評価が誤ったとまでは断定しない。
- 共通の配当・銘柄変更/廃止イベントを注文/保有/評価まで通す経路は、今回の通常`src`/`scripts`読取では確認できなかった。

**最小受入条件案**：入出金と投資収益を区別し、配当/税・費用の扱い、権利日/現金化日、raw/adjusted基準、数量・未約定注文の変更/照合を定義。最初は対象商品に必要なイベントだけ。既存M4/K05と研究bookを再利用し、全過去履歴の完全再構築を前提にしない。

比較：[LEAN企業行動](https://www.quantconnect.com/docs/v2/writing-algorithms/securities/asset-classes/us-equity/corporate-actions)、[Security Master](https://www.quantconnect.com/docs/v2/writing-algorithms/datasets/quantconnect/us-equity-security-master)。根拠：`scripts/rebuild_pnl_state_from_broker.py:711`、`scripts/check_corporate_actions.py:1`、`src/stock_swing/reporting/equity_bridge_reconciliation.py:107`。

### C04：シグナルの有効期限・撤回・根拠失効【中】

**足りない機能**：買い信号の発注可能期限、根拠が変わった際の撤回、未約定注文を残す/取り消す条件を、想定保有期間や注文DAYとは別に定義すること。

- CandidateSignal/DecisionRecordには生成時刻と`time_horizon`があるが、明示的な`valid_until`/撤回状態を持たず、今回読んだ通常のvalidation/executorに共通の信号期限強制を確認できない。
- 価格のstale flag検査や数量用参照価格の鮮度検証はすでにある。信号の根拠の鮮度とは別。
- 通常はrunで再計算して成行DAYを出すため、長時間の指値待ちほど切迫してはいない。遅延/再起動/再試行や将来の指値化で重要になる。既存保有を信号期限だけで自動全売却する提案ではない。

**最小受入条件案**：発注期限と保有期限を区別し、期限後BUY停止、未約定部分の再判断、撤回時の注文照合、同一根拠での再点灯を区別する。K02/K04/K08/K14へ。

根拠：`strategy_engine/base_strategy.py:17`、`core/types.py:44`、`decision_engine/risk_validator.py:66`。比較：[LEAN Insightの期間/取消](https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/alpha/key-concepts)。

### C05：集中分類の網羅性とETF内部の重複【高／詳細look-throughは段階化】

**足りない機能**：名目の銘柄数だけでなく、同じ経済リスクにどれだけ重ねているかを把握すること。

- 半導体個別株とETFを合算する静的cluster、beta/相関/集中に関する分析・昇格gate部品はある。相関管理が全面欠如しているわけではない。
- ASTで現行`DEFAULT_SYMBOLS`と`CLUSTERS`を照合し、**AVGO・TSM・ASMLは対象リストにあるが、当該cluster辞書ではいずれも所属が空**と確認。したがって、そのcluster guardだけでは同じ半導体リスクを網羅しない。他の業種/単銘柄/総露出guardが効く可能性は残る。
- ETF全額を半導体群として扱う粗い保守的合算はあるが、構成比を用いた個別株との重複量や複数ETF間の重複を示すものではない。

**最小受入条件案**：まず現行対象と分類のcoverage/不明分類/発注後上限を確認。詳細なETF構成比やfactor modelは、分類漏れ是正と分けて必要性を判断する。無料で取得できる運用会社資料等を優先し、構成比未取得をゼロリスクにしない。K01/K04/K11へ。上限値を今回変更しない。

根拠：`risk/correlation_cluster.py:15`、`cli/paper_demo.py:467`、`risk/promotion_gate.py`、`risk/pairwise_correlation.py`。比較：[LEAN ETF構成銘柄・比率と履歴](https://www.quantconnect.com/docs/v2/writing-algorithms/universes/equity/etf-constituents-universes)。構成比データの存在と、自動で最適な集中制御をすることは別。

### C06：当時の銘柄集合・除外銘柄を含む評価【中／比較の主張に応じて限定】

**足りない機能**：現在残った銘柄だけで過去を評価せず、当時の採用/除外・上場廃止・銘柄変更を識別すること。

- symbol registryとGitからの導入日proxyがあるので、PIT対応ゼロではない。
- 導入日取得script自身が、システム導入日の代理であって当時の公平な選定集合ではなく、銘柄選択そのもののバイアスを直せないと明記している。R13-Cの旧「実装完了」見出しだけを完全性の根拠にしない。

**最小受入条件案**：今後の採用/除外と理由・利用可能時点を既存記録へ保存。履歴が取れない比較は「現在選定集合での探索」と明記。全米株の有料PIT DBや全旧履歴を研究開始の前提にしない。既存R13-C/K05/S1へ。

根拠：`scripts/r11_symbol_universe_intro_dates.py:1`、`docs/console_improvement_tasks.md` R13-C。比較：[LEANの歴史的銘柄変更/廃止データ](https://www.quantconnect.com/docs/v2/writing-algorithms/datasets/quantconnect/us-equity-security-master)。Security Masterだけで銘柄選定バイアスが自動消去されると主張しない。

### C07：執行品質と運用可能な数量の測定【中／資金増額前には高】

**足りない機能**：注文時の実行可能な気配から実fillまでの費用、未約定の機会費用、数量増加時の費用/流動性を区別して測ること。

- [コスト定義・感度/記述分析](cost_model_definition.md)、固定bpsを使う研究、価格鮮度検証はある。コストモデル未実装とは言わない。
- 既存分析も日次始値/前日終値との差を真のslippageと区別している。通常発注は成行DAYで、同時点bid/ask・送信/ACK/個別fill・取消/未約定を結ぶ取引コスト分析（TCA）の資格は未確立。
- 出来高下限のfilterは、注文数量に応じた市場参加率・板の厚さ・解消所要時間のモデルとは別。現行資金で実害があると未計測のまま断定しない。

**最小受入条件案**：現行小サイズで必要な時点気配/注文/約定の対応を確認。仮定bpsと実測を分け、指値化による未約定・取り逃しも数える。大規模SOR/TWAPの先行開発はしない。K14/P4・移行受入へ。

比較：[LEANのfill/slippage/fee/capacityモデル](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/key-concepts)。定額bpsを外しただけで改善すると扱わない。

### C08：停止中の保護と商品別の発注条件【高／実運用接続前、K15は既知】

**足りない機能**：通常SELL判定が止まったときの保護、保護注文と通常SELLの数量競合、対象商品の注文条件を満たすこと。

- ソフトウェアstop/trailing/時間退出、監視・circuit breaker等はあるが、現行submit引数にstop価格/親子注文関係はなく、売却ルールはrun時の判定である。
- IBKRにはbracket等のAPIがあるが、現行lot/退出規則をそのまま同じ意味で載せられるとは限らない。部分約定・取消・通常SELLとの二重売却防止を含める。
- 現在の整数株・成行中心に必要な商品識別/取引可否と、将来の指値・逆指値に必要なtick等を段階化する。Nautilusの商品型も、全tick倍数の妥当性を自動で保証するわけではないと公式に明記している。

**最小受入条件案**：監視空白/遅延、切断/再開、売却可能数量、保護注文の所在/取消/再照合、口座/銘柄/通貨/取引時間を仕様化。broker固有の注文試験は接続条件確定後。stopが飛び越えや約定価格を保証するとはしない。K14/K15と既存D_IB工程へ。

比較：[IBKR bracket](https://www.interactivebrokers.com/docs/general/order-types/complex-orders/bracket-orders)、[注文状態/部分数量](https://www.interactivebrokers.com/docs/tws-api/doc/order-management/order-status)、[Nautilus商品精度の範囲と限界](https://nautilustrader.io/docs/latest/concepts/instruments/)。

### C09：同じ売買仕様による評価と利益寄与の分解【高／既存改善サイクルの中核】

**足りない機能**：研究で良かった理由が、実売買でも同じ仕様・同等リスク・実行可能な価格/資金で再現するかを判断すること。

- 研究、walk-forward/試行記録、戦略/退出理由別集計、benchmark/beta等はすでにある。評価機能自体がないわけではない。
- `r11_backtest_engine_v4.py`は固定notional/固定equity基準等の制約を自ら明記。独立cash/lotの研究bookや比較bookの隔離成果もあるが、通常系の全設定/入力/注文状態との一致は未認定。
- 「相場上昇」「銘柄選択」「数量」「出口」「執行費用」「会計訂正」の差を分けずにPFだけ比べると、どの機能を変えるべきか判断できない。旧データの全面再現を作るのでなく、今回比較する変更に必要な同時点入力と対照を絞る。

**最小受入条件案**：候補/見送り・時点/版/実効設定・数量/保有/予約・約定/費用の必要最小入力を共通化。金額の差分/ウォーターフォールと費用後・時価リスクを併記し、因果比較と記述帰属を分ける。PFは非加法なので寄与額のように足さない。既存K05/K06/K13・S1〜S6とC11/R13の枠内で実施。

根拠：[最新計画](strategy_improvement_validation_plan_20261020.md#functional-improvements-20261028)、[信号診断](signal_diagnostics_20261028/README.md)、`scripts/r11_backtest_engine_v4.py:1`。比較：[Nautilusの研究/実運用ロジック共有と相違](https://nautilustrader.io/docs/latest/concepts/live/)。同じコードでも現実の約定結果まで一致するとは主張しない。

## 5. 既存計画にどう対応するか

| 所見 | 既存の受け皿 | 重複実装を避けた最小の補足 |
|---|---|---|
| C01 | K02/K03/K14、移行最小受入 | 応答不明・安定注文ID・POST再送・再起動回復を明示。会計idempotenceと分ける |
| C02 | K01/K09/K14、P4、移行 | 口座資金/受渡/予約/部分約定/取消確定の契約を明示 |
| C03 | M4/K05、既存企業行動/研究book | 配当等を外部入出金と区別し、価格/数量/注文/収益の整合へ接続 |
| C04 | K02/K04/K08/K14 | 発注信号の寿命・撤回と保有期限を分離 |
| C05 | K01/K04/K11 | まず現行対象の分類coverage。詳細ETF look-through/factorモデルは別の必要性判断 |
| C06 | R13-C/K05/S1 | 当時の集合proxyの限界を維持し、今後の採用/除外を記録 |
| C07 | K14/P4、既存コスト定義/記録 | 実測TCA/数量依存容量と固定bpsの範囲を区別 |
| C08 | K14/K15、D_IB後の移行 | 売り監視/停止時保護/商品別条件を既存工程で検証 |
| C09 | K05/K06/K13/S1〜S6、C11/R13 | 固定比較の契約と寄与分解。全面replayや新optimizerを前提にしない |

**着手の順序案**：既存のK01〜K04最小隔離是正を優先し、そのレビューにC01の送信不明とC05の分類coverageの影響を含める。別枠の修正を無断で追加する意味ではない。C02/C03は既存記録・book・M4/移行受入の仕様へ、C04/C07/C08は執行要件へ、C06/C09は既存の限定研究へ割り付ける。

既存の期日、S3最大1候補/変更1か所・S4固定比較1バッチ、C11対UとR14の試行上限は変更しない。全9所見/全旧履歴/IBKRの完成を独立研究の一律前提にしない。適用/昇格・現在の株ETF配分・閾値・対象商品は変更しない。本資料を実装/配備完了や研究候補採用と扱わない。

## 6. 足りないからといって今は追加しない機能

- オプション/先物/空売り/信用拡大/HFT：現スコープ外。比較先が持つことは導入理由にならない。
- テクニカル指標の大量追加、深層学習、LLMによる自動変更：情報増加と費用後の改善は別。既存の否定的研究結果や試行上限を維持する。
- 汎用portfolio optimizer、新DB、取引基盤の総入替、旧broker完全replay：現時点の受入に必要な最小差分を越える。
- 税務最適化・多通貨運用・高度な大口執行：対象口座/商品/規模の必要性が明らかになるまで必須化しない。配当の収益分類/源泉控除の明示とは区別する。
- 動的ユニバースや指値、bracketを採用すれば利益が増えるという前提：いずれも新しい失敗/機会費用を伴い、効果は別検証。

## 7. 検証範囲と成果物

本比較で追加したのはこの文書のみ。ソース、実効設定、既存改善計画、金融台帳、定期設定、売買状態を編集しない。既存のdirty変更は保持。AST確認はデータ型/引数/静的表の確認であり、注文経路全体・scheduler正常性・経済効果の試験ではない。

検証対象は`src`/`config`の非pycacheファイル210件と既存改善計画4文書。前者のSHA-256不変を照合し、後者は比較中の更新を検出して最新§3.38を再読した。本作業から既存計画を編集していない。本書のローカルリンク6件は有効、参照した公式Web資料は重複除き13ページ。具体的な証跡はworkspace private tmpの`capability-comparison-20261028-*`に置き、当日のみの作業証跡として扱う。

**要約**：いま優先するのは「シグナルをもっと出す」ことより、**同じ注文を重ねない・使える資金を超えない・同じリスクを見落とさない・配当を含め正しく評価する・どの機能が効いたか比較できる**という一連の機能を閉じることである。
