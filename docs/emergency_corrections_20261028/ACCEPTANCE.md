# 受入・状態契約・残条件

## 変更した最小経路

- `scripts/emergency_sell.py`：import時submitを止めmainへ。NOW/IBMごとのReductionResultを出力し、最も悪い終了コードを返す。他銘柄のunknownだけでは、確認できる独立銘柄のSELLを止めない。
- `scripts/close_hpe_short.py`：既存の.env読取/yes-noを保持し、HPE short解消を共通helperへ。新規long BUYのrisk保留を機械的に流用しない。.env/認証情報は検証コピー/packetへ含めない。
- `execution/reduction_orders.py`：paper runtime・account ID/status、同じaccount-route lock、strict履歴を確認。固定`manual-reduction-v1:kind:symbol`から既存client IDへ。先行不明は照会し同じ意図を非再送。確認前のsnapshotと確認後のsnapshot/口座を照合し、保有/未約定残の差分を整数化する。
- 共通`SubmissionGuard`：実HTTP拒否（400/401/403/422）を、架空のbroker IDを作らず`rejected,response=null,http_rejection.status`で記録/厳密読取できるよう拡張。無効shape/型/statusは拒否。既存通常submitの判断方式は変えない。
- `BrokerClient`：POST v2/ordersの正規化済み例外に観測HTTP statusを付与するだけ。既存の例外型/本文、GET retry、POST/DELETE1回、価格/記録hookを保持。timeout/5xx/不正ACKを「明示拒否」と決めつけない。422でも同IDの一致照会があれば、その応答で判定する。

## 状態と出力

| 場合 | state/終了 | 送信/永続状態 |
|---|---|---|
| 初回・数量/口座/両snapshot適格 | accepted、0（整数の場合） | preparedのfsync後1POST、正規ACKを検証してoutcome。acceptedは約定済みでない |
| ACK喪失・一致照会あり | accepted、0（整数の場合） | 同じ1POSTの照会結果を保存。再送ではない |
| ACK喪失/5xx/不正ACK・照会なし/不整合 | unknown、1 | unknown/preparedを保持、再送しない。404を未送信の証明にしない |
| 明示HTTP拒否/正規status rejected | rejected、1 | 拒否記録、同意図再送なし。API拒否と不明を別表示 |
| 同じ意図で再実行 | held/unknown/rejected、1 | 履歴と同ID照会。qtyが変わっても新IDにしない。accepted照会後も自動再送しない |
| malformed/missing/partial履歴、marker不整合、symlink、書込/fsync不能、busy lock | held、1（送信後ならunknown、1） | 状態を空へresetせず保留。未観測qty/予約/小数残はnullで、0としない |
| 初回で検証済みflat/反対方向保有/人no | flat/not_applicable/cancelled、原則0 | 新intent/POSTなし。unsupported小数残が分かった場合は1を維持 |
| 整数切捨て後の小数残 | accepted等でも1 | 数量政策は維持、残を表示して「完了」にしない |

同一意図を再実行した時のheldは非再送の判断で、既受付注文の最新broker状態はbroker_statusで別表示する。受付後に拒否等へ変わる全ライフサイクルを新しいイベントへ移行する機能は対象外。

`ReductionResult → to_dict → 人向け行/REDUCTION_SUMMARY_JSON → main exit`をテストする。プロセスkillや.env読込自体の障害など、全てのOS/認証読取経路にJSON出力を保証したものではない。終了0もfillの証明でなく、状態/理由を必ず読む。

## 数量・入力の受入

- positions全体がlist、symbol一意、qtyは非欠測/非bool/有限数、long/short表記との符号整合。空listと欠測を区別する。
- open ordersはlistで500件未満、ID一意、既知状態/種類、simple、正のqtyと`0≤filled<qty`。複雑注文、未知type/状態、変更中pending_replace、反対方向注文、型/数量異常は保留。
- `abs(position)−Σ(qty−filled)`の残から整数株を採る。pending_cancelは残予約のまま。残予約が保有を超えれば保留。確定前の取消/未確認SELLで枠を空けない。
- 他intentのacceptedをjournalだけから捨てず、現在の照会とopen側のID/side/qty/filled/status/type/clientID/TIFを照合。不在/矛盾は保留。同方向の過去fillに保有が残れば再照合待ち。replaced/done_for_dayを無条件に解放しない。
- 人の確認後ももう一度positions/orders/accountを取得し、意味が変われば発注しない。価格の変化を数量0へ変換しない。これでもbroker側の同時点性/実鮮度は未認定。

## 試験の対応

- 修正前2失敗→候補成功：ACK不明再実行、安定ID、非ゼロ終了/「完了」なし。
- 新規60＋既存295＝重点355。状態/再起動、正常/flat/逆方向/欠測/NaN/不正shape、部分約定/取消中/反対注文/500件/complex/変更中、口座/snapshot差、拒否400/401/403/422・不正ACK・照会一致/不一致、履歴欠損/破損/逆遷移、init/prepare/outcome fsync障害、fractional/human no、他銘柄不明でもshort解消、accepted履歴とopen予約の照合を含む。
- 実scriptsは74条件×2版＝148対照、198回の独立Python起動。同じrootを意図的に2回実行する再起動条件は、前回のjournalと外部broker fixtureだけを保持。別条件間は新規root。
- 並行/killは2scripts×2版＝4対照、12起動。最初のHTTP受付後にbarrier、別プロセスを同じrootで実行、その後最初をkillして再起動。内部lockやjournalをモックしない。外部HTTP/human input・fsync等のOS境界だけ代替。
- 通常CLI40ケース、provider/記録/K安全295件も保持。全体回帰2,959/3skip＋分離localhost1、既存collection warning1。重点355を全体へ加算しない。

## 未認定と次の確認

| 残条件 | 影響/最小次作業 | 担当/確認 |
|---|---|---|
| 将来の別ポジション世代/正当な追加解消 | 固定IDは保守的に保留。lot/注文同一性を資格化した世代契約なしに新epoch/手動resetを追加しない | Agentの最小仕様＋本人方針、2026-10-30 18:00 JSTに是正枠/政策差レビュー |
| 実brokerの照会/冪等・鮮度/atomic snapshot | 合成受付と実契約は別。接続方式/口座の最小必要証拠が揃ってから技術受入 | Agent/口座提供者、11/06 18:00不足込み一次結論、11/13 18:00受入/工数 |
| 非協調caller/別端末・state全消失/電源断 | 協調lockと存在する履歴の保証範囲外。全callerやglobal exactly-onceとしない | 既存CMP-C01/K14/K15へ、11/06閉包表・11/13限定受入 |
| 小数株/新しい数量政策・全設定閉包 | 既存整数切捨ての表示だけ是正。小数株注文・分類/閾値・CB/出口fallbackの採用は別 | 本人/Agent、10/30政策、11/06未完込み |
| 本番配備・正規運用復帰 | 候補のテスト合格だけでは実注文後のstate整合/定期実行を認定しない。journalを消すrollbackは禁止案 | 11/13限定適用案または未完。現在は本番未適用 |

P4の実入力・正式U/epsilon/rho/delta/標本/将来観測、実請求額は今回解消しない。主C11対U/Required・P4全体未完/T0未設定/F1未開始を保持する。必要な独立研究を全K機能完成待ちにはしない。
