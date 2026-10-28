# 直接発注スクリプト：確認済みと未是正

実scripts/emergency_sell.py（NOW/IBM）・scripts/close_hpe_short.py（HPE）を`.env`なしの新規コピーでrunpy実行。BrokerClientもコピーからimportした実コード。外部httpx transportと人のyes/no入力だけ代替。Brokerの実HTTP送信はOSで禁止、fixtureに対するPOSTのみ記録。応答喪失fixtureは受付後にACKが失われた場合を明示的に仮定する。現実の受付を推定したわけではない。

## 23条件×2版＝46ケース

両版の結果は全件一致。[結果](emergency_results.json)・[機械要約](emergency_summary.json)。基準は前回安全候補（adapter再試行是正後）と今回統合候補であり、元の3回再試行版との比較ではない。

| 条件 | 緊急SELL | HPE short買戻し |
|---|---|---|
| 通常 | NOW3/IBM2を各SELL1回 | -13の保有にBUY13を1回 |
| flat/反対side/qty欠測 | 発注なし。欠測qtyを0にする既存挙動 | 発注なし。欠測qtyを0にする既存挙動 |
| 人がno | 非対話スクリプトのため該当なし | 発注なし |
| 不正position形/NaN qty、GET401 | 発注前に例外。正常完了とはしない | 発注前に例外 |
| 小数株 | 3.7→SELL3、残0.7は扱わない | -13.7→BUY13、残short0.7は扱わない |
| POST400明示拒否 | 2回の異なる銘柄submitを各1回。エラーを捕捉し後続/完了表示 | 1回。例外で終了 |
| 受付後ACK喪失 | NOW/IBM各1回、例外を捕捉し後続/「完了」表示。照会なし | BUY1回、例外で終了。照会なし |
| ACK喪失後に未更新保有で同じscriptを再実行 | 2銘柄×2runで4POST（同じ意図を再送） | 1銘柄×2runで2POST（同じ意図を再送） |

全ケースでclient_order_idなし、by_client_order_id照会なし。**各submit内の通信retry停止と、再実行時の経済的重複防止は別**。遅延/未約定/ACK喪失時に安全に再実行できる証明はなく、全caller保護完了とはしない。「Emergency sell complete」は約定/受付確認を意味しない。

## CMP-C01/K14/K15へ戻す最小是正仕様（未実装・未採用）

新基盤を増やさず、既存adapter/TradeEventStore/協調lock/照会を再利用する。ただしpaper CLIの新規BUY保留をそのままshort買戻しへ流用しない。

1. 発注意図を`reduce_long`/`cover_short`として識別し、口座/route・銘柄・signed保有・同時点の既存reduce注文/部分約定/未約定残を照合する。成行数量は予約後の残保有を超えない。既存固定銘柄や小数切捨ての政策変更は別判断。
2. 安定意図ID、送信前耐久記録、協調lock、1HTTP送信、accepted/unknown/rejected/heldの区別を接続。ACK不明/404は再送許可にせず、再実行は同ID照会・保有/注文整合まで保留。意図IDをrunごとに新しく作って重複解消したことにしない。
3. 不明/拒否/部分処理時には銘柄別結果と未完を表示し、機械終了statusにも伝播する。全件約定済みとsubmit受付済みも分ける。
4. 受入はACK喪失後の再実行・並行実行・履歴破損/書込失敗・保有変化/部分約定/既存SELL・shortを跨ぐBUY・qty欠測/小数・明示拒否・他銘柄継続を合成で確認。実口座/本番操作は別工程。

担当：agentが最小差分/政策差/工数と是正1バッチ適合を2026-10-30 18:00 JSTに確認、11/06一次結論へ未完込みで記録。本人が資本/競合/小数方針を決める。移行先固有契約はD_IB確定後。これは新規是正バッチを認可・実装した記録ではない。
