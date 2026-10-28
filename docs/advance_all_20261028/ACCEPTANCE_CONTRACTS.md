# 10/30成果物の前倒し：機能別受入・不足表

2026-10-28。正本は詳細計画§3.37〜3.41・§8。これはその成果物で、別ロードマップではない。担当は下表の「本人/口座提供者」の判断以外はエージェント。全項目の**仕様提出**と、実装・実入力資格・配備・利益効果を分離する。既存の是正1バッチ、S3最大1案・変更1か所、S4固定比較1バッチを維持。今回、経済仮説を追加・実行していない。

## K01〜K15：実効仕様・合否の観測・残条件

共通契約：`run_id / decision_id / strategy_id / version / account-route / input_hash / received_at / window_end / signal_at / side / qty / reason / order-id / fill-id / config_hash`を必要な既存経路に結ぶ。取得していない値はnull、不明を0/無期限/成功にしない。全情報の新規収集基盤を前提としない。

| ID | 実効仕様／既存証拠 | 固定する受入ケース・観測 | 本日の到達点と未達・次の有界作業 |
|---|---|---|---|
| K01 | CLIの数量計算後・発注前。保有＋未約定BUY残＋同run試行済み予約＋今回予定額。銘柄/重複cluster/株ETF band | 上限ちょうど可・微小超過不可。部分約定は残数量のみ予約、未確認取消/SELLは容量を空けない。500件/複雑注文/価格不明はBUY保留 | 既存K03/K01/K02隔離候補を維持し分類漏れの対象群を追加保留。実口座鮮度/原子性/通貨/価格余裕・資金余力は未認定。10/30に不足再確認、11/06に閉包/枠適合レビュー |
| K02 | 元判断・戦略・理由を保持し、同銘柄重複BUY/BUYSELLはBUY保留という未採用案。発注意図再試行は別問題 | 複数戦略BUYを合算/勝者選択しない、SELL維持。同じaccount-route/decisionの再送なし。ACK喪失→照会/unknown。再起動/並行lock/破損/書込失敗 | 既存イベント記録・flock・BrokerClientを再利用した狭い候補を追加。複数SELL調停/lot配賦、異なる新decisionが同じ経済信号かの永続同一性、wrapper迂回は未修正。政策採用は本人の判断、11/13技術受入案 |
| K03 | 計算不能riskはnull、BUY保留。executorの露出例外を0へ戻さない | 正常0と欠損/破損を区別しdecision→JSON→renderer/監査へ伝播。確認可能なSELLは継続 | 前回2経路の隔離修正を保持・回帰対象。precomputed全caller・すべての上流異常/SELL例外を認定したものではない。11/06の未検証caller表へ残す |
| K04 | breakoutの実条件はCLI momentum/score、保有期限はexit YAML。entry YAMLのenabled/max_hold、出来高/filing等は未接続 | 使用設定のmapping/型/有限値を検査し由来/hash/effective/unusedを記録。null/list/壊れ/NaN/文字bool/欠損はBUY保留・診断継続。正常同値、OFF機能を接続しない | exit/allocation/registry/使用されたintradayの隔離処理を追加。壊れたexitは既存missing-file既定退出へfallbackする**未採用案**で、設定通りの出口との同値性は主張しない。全設定reader閉包は未完。10/30政策/11/06技術レビュー |
| K05 | 記録スコア2,089件の再計算一致。決済422行中入口スコア197行、225行欠測。既存S1/S2固定診断 | 全候補/見送り分母と判断前入力・fill/exit・費用・企業行動のjoinを別々に表示。同点一群、欠測除外による偏り、粗利益と会計訂正を区別 | 既存診断を再試行せず保持。10/30 coverage仕様は本表/CMP表、11/06は適格範囲の一次結論または保留。不足を補完してPFを作らない |
| K06 | 個別株買い記録47.3%が満点。score/confidenceは成功確率でない | 固定5営業日horizon・同日対照・同点群・費用後差。価格窓/上場日/非取引日/未成熟/欠測の資格を列分け | 診断仕様のみ前倒し。成熟価格/時点資格不足、高順位の優位性未確認。11/06に改善案最大1案/なし/保留。閾値の総当たりなし |
| K07 | PF集計は渡された決済履歴、停止後の実取引観測は減る。既存停止中BUY観測が別経路 | 停止候補/否認理由/版/cohort、定期実行、捕捉、5日outcome成熟を分離。価格proxyは実売買PnLでない | 既存10/29 07:10 JST確認を待つ部分は本日完了不能。二重予約しない。自然経過/影観測だけで解除しない。11/06に不足込み診断 |
| K08 | 段階trailing優先・建値分岐重複、最古lot時計。per-lot修正OFFを保持 | 同入口/数量/価格/費用で出口と単純保有を比べる。初回/追加lot・暦日/営業日・部分退出・未約定・exit優先順位。信号TTLとは別 | 契約表を前倒し。出口別実現PnLは因果効果でない。分岐/lot変更を無断ONにせず、選ぶならS3の1案。11/06到達可能性/不足を提出 |
| K09 | 現行quantity制約と実exit距離を区別。confidence増額の既定no-op・修正版OFF | 各制約の上限株数・採択min・倍率前後・ATR実方式・exit距離/ギャップ・現金/予約。単純縮小Uとの独立cash経路 | C11/P0/研究cap30%を維持。実口座の資金項目はCMP-C02。11/06に現行対応と不足、11/13正式較正条件。資金増の利益を選別力と呼ばない |
| K10 | 初回購入と24h後の追加を区別、含み損add抑制はshadow | 根拠の更新時点/既保有lot・リスク/追加量とcash/予約。24h通過だけで独立機会にしない。見送りの反発/再配分機会も分母へ | 仕様のみ、追加禁止や−3%を採用しない。必要な記録は既存最小経路へ、選択時のみS3。11/06に情報増分の有無 |
| K11 | 業種round-robin、未指定notional $1,000、件数による露出枠増は実額配分と別 | 候補・保有継続・現金の予定必要額/重複群/予約/費用/回転を同じ資本で比較。株85/ETF15を維持 | 分類coverageを本日照合。ETF詳細重複は未認定。順位変更はS3、数量はC11/R13へ。11/06に資金・機会差の不足を提出、最適化なし |
| K12 | intraday加点とconfidenceは同義でない、決算近接は内容でない。shadowは実装/有効/実行/適格を分ける | 入口固定、同じ時計/足basis/eligible sessionで追加情報の有無比較。非稼働/重複/将来時刻を除外する分母を表示 | K04の使用設定だけ検証。他の有効化/新PnLなし。既存R14時点証拠・適格0を維持。11/06に既存証拠から一次診断 |
| K13 | recommenderの平均score/否認率は利益最適化の証明でない | 仮説・変更1か所・対照・費用後主指標・反証・終了条件・入力版・独立性の欄を必須にする。比較未実施を明記 | 本表で提案→比較→採否の契約を完成。自動反映なし。S3最大1案未消費、11/06案/なし、11/13固定比較または未完 |
| K14 | 成行DAY、数量用quoteと実fill/費用を分離。実注文は未実施 | 送信前intent/価格時刻→ACK/unknown→照会→個別fill→費用→残予約。取消要求は確定でない。期限不明なら採用保留 | CMP-C01の狭い隔離是正あり。他のTTL/TCA/資金は下表。11/13 broker-neutral最小要件/見積もり。指値/SOR/TWAPへの改造なし |
| K15 | run時のソフト退出で、broker常駐保護ではない | 判定/遅延/監視空白・切断/再起動・通常SELL/保護注文/部分約定残・口座商品条件・二重売却防止 | 現状と最小受入契約を本日提出。実際の保護注文/監視停止試験は未実施、全停止耐性を認定しない。11/13対象商品/接続方式に絞る見積もり |

## CMP-C01〜C09：既存部品・入力契約・未達条件

研究arm C01とは別。以下の未取得入力を0としない。次回確認は全て2026年JST18:00。入力が揃わなくても11/06の一次報告を延期しない。

| ID | 最小入力・受入／既存部品 | 不足の影響・本日の到達点 | 担当・次の確認／再開条件 |
|---|---|---|---|
| CMP-C01 | account/route/decision/安定client ID・注文payload・prepared/outcome・照会応答。既存BrokerClient/TradeEventStore/flock | POST/DELETE自動再送停止、GET retry維持、fsync前記録・厳密読込・協調lock・同intent非再送を隔離確認。404は未送信の証明でない。実provider資格/新decision同一性/全callerは未認定 | Agent、10/30残契約、11/06閉包/枠適合、11/13技術受入。正規口座の照会契約・snapshot前後と実運用復帰手順が揃うこと |
| CMP-C02 | currency/as_of、cash/settled_cash/available_to_trade、broker余力、open残/fees/価格余裕。quantityは既存制約と購入可能額上限のmin | equityは余力でなく、信用口座/受渡日数/FXを仮定しない。部分約定で残だけ、未確認取消/SELLで解放なし。既存allocator/book/Protocol再利用案、資金制約実装は対象外 | 口座提供者の仕様＋Agent、10/30欠測、11/06接続案、11/13必要欄/工数。対象口座・通貨・資金項目の意味が確定して再開 |
| CMP-C03 | event ID/type/symbol/ex/record/pay/available、ratio/gross/net/withholding/fees/currency、price-adjustment basis・反映先 | splitは数量/原価とcashを分離し、dividendは投資収益、入出金は外部flow。再受信同eventの重複なし、raw/adjustedと配当二重加算なし。既存split・activities/equity bridge・bookの対応案。実イベント完備未認定 | Agent/口座記録、10/30欠測、11/06既存経路案、11/13M4受入。必要なイベント一次証拠と調整basisが一致すること。全旧台帳復元は不要 |
| CMP-C04 | signal生成/根拠更新/available/valid_until、order TIF、未約定残、撤回理由・取消確認 | signal TTLと保有期限は別。TTL値は未決。期限ちょうど/期限超過/再起動/取消受付中の仕様：新BUYは期限資格が必要、取消不明なら再発注しない。保有全売却なし | 政策は本人、技術はAgent。10/30契約、11/06具体案、11/13接続後最小要件。TTL採用理由/時刻定義を先に固定 |
| CMP-C05 | default/held/pending/reserved × registry flag/asset class/cluster/版hash。既存registryと静的cluster | 既定60・registry80の照合、半導体flag trueでsemis_combined外5銘柄。関連BUYを保留する隔離案であり分類修正ではない。saved tracker closed422/quarantined1/open0、現在broker保有/未約定は不明。ETF詳細look-throughは未測定 | Agent、10/30分類レビュー、11/06最小差分、11/13残受入。新分類は根拠/由来/版をレビューしてから。詳細有料DBは必須化しない |
| CMP-C06 | universe採用/除外/rename/delist、valid_from/toと当時のavailable、source/hash | 現在60銘柄を歴史PIT集合と呼ばない。既存導入日proxy/履歴は部分資料。除外全件・廃止履歴は不足、探索の選択バイアスが残る。今後は既存run入力へ採用集合hashを結ぶ最小案 | Agent、10/30coverage、11/06記録案、11/13比較資格。対象研究に必要な当時集合の証拠のみ追加し、全米PIT取得の一律待ちにしない |
| CMP-C07 | bid/ask/timestamp/available、send/ACK/各fill qty-price-time、fee、取消/未約定、同期間出来高 | BUY符号s=+1/SELL=-1としてslippage bps=10,000*s*(VWAPfill/mid_at_decision−1)。spread・price_moveとfeesを別列、機会費用は未約定残と共通評価時点で別計上。固定bps感度を実測と呼ばない。既存fill ledger/quote/latency再利用 | Agent/接続先、10/30入力差、11/06計測案、11/13対象サイズの最低要件。時点整合した気配/fillと費用資格で再開。容量/市場impact未推定 |
| CMP-C08 | account/product/currency/tradable/lot/tick/session、注文方式/保護残qty/通常SELL、監視heartbeat/復帰snapshot | 常駐保護なしの空白を明示。切断/再起動/部分約定/取消不明で二重SELLなし、再接続時残量照合・新BUY停止から再開。stopは価格/最大損失保証でない | Agent＋接続方式/口座提供者、10/30現状契約、11/06案、11/13最小試験/工数。D_IBと必要商品確定後の実配線。週1程度手動再認証希望を維持、毎日手動を仮定しない |
| CMP-C09 | 同期間/初期cash/全候補/入力版/数量/予約/exit/price/fill/fees/会計basis。既存独立bookとS診断 | bridgeは相場・選別・数量・出口・執行・会計訂正を**金額**で示しresidualも表示。順序依存の記述帰属と因果対照は別、PFを寄与額として足さない。揃わない比較は不適格/探索 | Agent、10/30比較契約、11/06不足込み一次結論、11/13固定比較/未完。既存主C11対U・Requiredを維持、新利益試行なし |

## 実装差分・復帰境界

- 1つの累積隔離候補。前回K03/K01/K02を置換せず保持し、HTTP retry境界、狭いintent journal、設定validation/receipt、分類gap guardだけを追加。新SDK/DB/依存なし。
- 元BrokerClientProtocolの構造互換を保ち、client ID照会はoptional capabilityとして分ける。全brokerが同じ照会保証を持つとはしない。
- 本番適用は未実施。コードのreverse patchは**未使用コピー**だけに適用する受入。いったん発注したjournalを消して過去版へ戻す運用は再送を招くため、コード復帰と状態/注文の照合を分離し、既存journalは保持する。旧版へ戻れば今回の再送脆弱性が復活するので「安全な運用rollbackを認定済み」とは呼ばない。
- 未認定：全caller/新signal同一性、非協調プロセス、state全削除、電源断/ディレクトリfsync、実provider応答・実口座pending/FX/settlement、複数SELL、正規scheduled run、他のprovider/記録候補との一体適合。
- 作業見積もりは実装承認でない。残閉包レビュー/政策整理/配備差分準備は各半日程度の**未計測概算**。broker-specific接続/認証/保護/実資金試験は要件未定のため未算出とし、11/13に対象範囲と上下限を示す。新機能の一律先行実装をしない。
