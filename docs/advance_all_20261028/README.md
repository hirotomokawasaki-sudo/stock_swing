# 10/28：本日前倒し可能分の成果物

**10/30の仕様・不足表と、11/06予定の最小是正バッチの対象部分を前倒しした隔離候補。本番未適用、P4全体未完・F1未開始。**

## 完了した範囲

- **発注再送／応答不明**：変更前はtimeout/500/429でPOST・DELETE各3回。候補は1回だけ送信し、安定client IDで照会。送信前fsync記録・厳密な履歴読込・account/route別協調lockを追加。同じdecisionの再送なし、404も再送許可にしない。再起動・accept後のプロセス終了・他プロセスlock・書込失敗・破損・照会不一致を検証。
- **設定異常**：使用されるexit/allocation/registry/intradayの型・有限値・由来と未使用項目を明示。欠損/破損時はBUY保留、診断と対象SELLを継続する隔離案。壊れたexitには既存missing-fileの既定値を使う案であり、設定された出口との同値性・本番政策採用を意味しない。正常数量は維持、未使用flagは有効化しない。
- **分類coverage**：既定60銘柄・registry80件を照合。半導体関連flag trueだが`semis_combined`外は **ASML/AVGO/CRDO/SMCI/TSMの5銘柄**。分類/上限値は変えず、候補/保有/未約定に漏れがあると関連半導体BUYを保留する案を検証。他群の適格BUYとSELLは維持。保存trackerにopen0でも現在broker flatとは認定しない。
- **10/30の資料**：[K01〜K15/CMP-C01〜09の受入・不足・担当・再開条件](ACCEPTANCE_CONTRACTS.md)、[P4/S1の比較・費用/U/判定値案と最小入力表](P4_S1_READINESS.md)を完成。これら全機能の実装完了を意味しない。

## 確認した結果と読み方

[検証集約](VALIDATION.json)／[全体回帰](full_suite.log)／[localhost単独](loopback_test.log)／[変更前retry再現](baseline_retry_red.log)／[実CLI固定対照](expected.json)／[分類監査](coverage.json)。実CLIは19条件×前回版/候補＝38ケース、外部HTTP・時計・入力だけを合成した非dry-runコピー。実注文・約定・利益証拠ではない。

| 実入口の例 | 前回K03/K01/K02候補 | 今回累積候補 |
|---|---|---|
| 正常NVDA BUY | 61株 | 61株（同値） |
| SELL1株＋別銘柄BUY61株 | 両方送信 | 両方送信（同値） |
| ACK喪失・照会404 | 最初のMSFTを3回送信、次BUYは保留 | MSFT1回のみ、unknownを明示、次BUY保留 |
| ACK喪失・一致照会 | 最初のMSFTを3回送信 | MSFT1回→一致照会、次のCRM1回 |
| exit null/list/壊れ | SELL評価前に中断するケースあり | BUYなし・対象SELL1株、警告/receipt |
| exit NaN/文字bool/欠損、allocation異常、registry異常、使用intraday null | 無言の既定値/BUY継続/中断が混在 | 12条件すべてBUYなし・対象SELL1株、DEGRADED |
| AVGO候補／AVGO保有・未約定＋NVDA | 漏れを含むBUYを送信 | 関連BUY保留、MSFTは維持 |

`unknown`/`held`は`rejected`に数えず、JSON funnelと警告・rendererへ伝播。CLIのexit0/cronのprocess statusは診断処理完了を示す場合があり、DEGRADEDを正規運用成功や技術受入済みと読み替えない。

保存先だけからの[独立追試](packet_replay.json)は **集中209成功・CLI38ケース一致**。byte/mode/余分なfile/symlinkの改変4条件は実行前に拒否。

全体回帰は **2,813成功・3skip**、分離localhostは **1成功**（重複なし合計2,814）。全テスト対象の資格・利益効果を認定する数字ではない。

[呼出元の境界・未配線script](CALLER_BOUNDARIES.md)も保存した。

## 差分・追試

- [追加差分](delta.patch)：前回K03/K01/K02候補から。既存修正を保持。
- [一体差分](combined.patch)：main `8909e79`の保護対象実ファイルから。コピーで適用→候補byte一致→reverse一致を確認。
- `code/`は必要な依存source/config/testの保存コピー、`baseline/`は前回との差分復元用。既存financial原本・秘密・`.env`は同梱しない。全体回帰の実fixture版は検証時に凍結、packet追試は下記の集中検証と合成CLIを対象とし、全回帰の独立再実行とは区別する。

```bash
cd /Users/hirotomookawasaki/stock_swing/docs/advance_all_20261028
/usr/bin/env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 \
  /usr/bin/sandbox-exec -f deny.sb \
  /Users/hirotomookawasaki/stock_swing/venv/bin/python -B verify.py \
  --output /tmp/advance-all-replay-result.json
```

出力はpacket外。最初にinventory/hash/mode/symlink・Python/依存版を検査し、packetだけから一時コピーを作る。import元を実パスで検査し、集中テストと38 CLIの正規化結果を照合する。外部通信と元repoへの書込みはOSで拒否。`--check-only`は検査だけ。manifestはローカル整合性検査で、外部署名による真正性保証ではない。

## 未完の境界・次の確認

- 狭いpaper CLI/協調callerの是正。異なる新decisionが同じ経済信号か、全caller、非協調プロセス、state全削除、電源断の完全耐性、注文・snapshotの原子性/鮮度、実brokerのID/照会契約、複数SELL調停、全設定reader閉包は未認定。exactly-once/全体安全を主張しない。
- 新journalの初期化は過去注文全件の取り込みではない。以前の未知注文を自動解決した扱いにしない。復帰時もjournalを削除せず、注文/保有と照合する。code reverse成功は稼働rollback安全性の認定ではない。
- 本人の資本・損失/許容収益減/必要効果、実時点入力・正式U較正/標本、未来の定期実行・成熟outcome、移行口座/商品条件は未完。[不足表](P4_S1_READINESS.md)の担当・絶対確認日と再開条件を維持する。
- 10/30に未達条件の再確認、11/06に不足込み一次結論・是正枠適合、11/13に技術受入/固定比較または未完、11/20・11/27・12/04の既存判断へ接続。**全17P/S行・日時、主C11対U/Required、是正1バッチ・S3最大1案未消費を維持**。10/30まで待つこと自体は条件でない。
- 他のprovider/記録候補の一体適合、本番配備/設定ON/正規scheduled runは未実施。金融原本・source/config・scheduler・認証・CB・実発注/取消は変更していない。commit/pushなし。

## 現行provider仕様の根拠

今回のadapterのclient ID（最大128文字）と照会endpointは[Alpaca Create Order](https://docs.alpaca.markets/us/reference/postorder)、[Get Order by Client Order ID](https://docs.alpaca.markets/us/reference/getorderbyclientorderid)、[Working with orders](https://docs.alpaca.markets/us/docs/working-with-orders)を参照。これはIBKRにも同じ保証があるという根拠ではなく、現口座の実応答資格は未認定。今回の非再送はローカル側で送信回数を制限した結果で、providerのexactly-once保証に依存した主張ではない。
