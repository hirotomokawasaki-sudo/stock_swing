# 取消時刻・設定観測の残差是正と反映準備 — 2026-10-28

ユーザー「すすめて」に基づく3項目。**隔離候補のみ、本番適用・実注文/取消・追加Push/mergeなし。** 既存是正1バッチ内であり、新しい利益比較を追加しない。

## 検証したこと

| 対象 | 到達点 |
|---|---|
| 取消時刻 | UTC13:30固定/UTC19–01時の近似を、ETの直近営業日09:30・実regular close・20:00境界へ置換。既存MarketCalendarの休日とzoneinfoを再利用。土日/祝日/DST/始業/30分/UTCとoffset表記/早引けを確認。30分、extended_hours=False、既存状態/破局的SELL保護の方針は維持 |
| 日程 | NYSE公表の2026–2028年、1,096暦日、29休場日・5早引け日と一致。範囲外/年初の範囲外lookbackはheld。これは予定されたcash-equity regular日程だけで、臨時休場/個別broker/夜間執行の保証ではない |
| 実入口 | 時刻29条件×前回/候補＝58process。旧版は12条件でDELETE対象が期待と不一致、候補0。mainのnaive/未来時刻は送信せず非ゼロ。旧取消19条件×2版＝38対照/42processでACK/unknown/再起動の安全境界を保持 |
| 設定 | 既存9種類/39fieldの構築成功だけでなくconstruction_failed/not_reached/changed_since_captureを分離。生成失敗は例外型だけを耐久記録して元例外を再送出。到達しない構築を実行せず、終点で値変更を観測しても元へ戻さない |
| 実CLI | 11条件×前回/今回OFF/今回ON＝33ケース。正常/override/記録不能/拒否値/非有限/必須構築失敗/任意3構築失敗/dry-runを確認。売買判断・注文対象/数量を維持。必須構築失敗は元の中断のまま、任意失敗は従来継続のまま（記録ONだけwarning/非ゼロ）。通常CLI40も既存期待値と一致 |
| 回帰 | 全体3,089成功/3skip＋分離localhost1成功＝重複なし3,090成功/3skip、既存collection warning1。重点147は全体へ加算しない。追加75契約は旧版43失敗/32成功、候補75成功。実際の運用事故43件という意味ではない |
| 切戻し | 前回の安全候補へコードだけ戻すコピー試験3条件。pending/canceledは旧コードでjournalを読み追加DELETEなし。unknownの404はjournal読取前に非ゼロ停止・追加DELETEなし・journal/金融JSON保持。運用中の全面切戻し完了ではない |

[仕様](SPEC.json)・[calendar照合](calendar_validation.json)・[限定consumer監査](config_consumer_audit.json)・[受入](TEST_CHECKLIST.md)・[導入/切戻し](DEPLOYMENT_REVIEW.md)。[追加5runtime＋2test](delta.patch)、[現行HEADから累積27runtime＋20test/fixture](combined.patch)、[適用/逆適用](patch_validation.json)。

日程の出典は[NYSE/ICEの2026–2028年公表](https://ir.theice.com/press/news-details/2025/NYSE-Group-Announces-2026-2027-and-2028-Holiday-and-Early-Closings-Calendar/)。事実だけを[reference](calendar_reference.json)に保存。既存部品で不足部分だけ補い、新SDK/DB/汎用calendar基盤は追加しない。

## 保存先だけの追試

```sh
/Users/hirotomookawasaki/stock_swing/venv/bin/python -B \
  /Users/hirotomookawasaki/stock_swing/docs/timing_config_readiness_20261028/verify.py \
  --output /tmp/timing-config-replay.json
```

全inventory/hash/mode/依存、解決後のisolated importを確認してから、重点502・calendar・時刻58・既存取消38/42起動・切戻し3・設定33・通常CLI40を再実行する。外部通信と稼働repo書込をOS sandboxで禁止。全体suiteに要る私有financial fixture2点は同梱せずhashのみ。Gitの権限は実行bitだけなので、公開cloneではbyte照合後のmanifest mode復元が別途必要。保存先のみの追試は完了し、[receipt](packet_replay.json)・[検証結果](VALIDATION.json)に保存。[公開前点検](PUBLICATION_PREPARATION.json)と[計画保全](plan_check.json)も添付。

## 残る境界

- 変更した時刻判定は取消selectorだけ。共有MarketCalendarの他callerや臨時休場、当該brokerの執行時間資格を認定しない。Case Bは既存のafter-close→20:00 ETという選定方針であり、NYSEの全late session時間やbroker受付時間を表さない。
- 設定の失敗記録は元例外を握りつぶさず、必須コンストラクタの失敗を成功へ変えない。非稼働日skip等、recorder生成前の終了は対象外。プロセスkill/生成途中での死は観測完了ではない。
- 終点比較は「変更して元へ戻す」中間変化や全helper呼出しの動的追跡ではない。9familyの明示CLI構築9箇所・optional helper fallback7箇所を静的分類（docstring除外）、対象fieldへの直接代入候補0。alias/外部caller/EntryFilter等全設定の閉包は未完。共通helpersを未使用設定の有効化で埋めない。
- L0/F0、主C11対U/Required/P0/cap30%、是正1バッチ、S3最大1案未消費/S4固定1、既存17工程と日時を保持。P4全体未完・T0未設定/F1未開始。将来の5-session観測や経済性の認定は前倒ししない。
- 初回切戻しprobeは404も正常終了するというdriver仮定で失敗。実契約どおり非ゼロ保留を確認し、送信数/journal/金融JSONを検証した。patchの初回probeも0600と0644をGit mode差と誤判定したため、byteとGit実行bitを分け、権限全体はmanifestで別検証。成功件数へ初回失敗を加算しない。

- 保存先初回追試はmacOSの`/tmp`別名を未解決のままpytest rootへ渡し、HTTP fixture重複で29失敗/473成功。解決済みの一時rootに統一して再検証した（売買コード変更・テスト省略による回避ではない）。
- 作業中に別途Console5ファイルの変更を検出した。本作業で書換え/戻しは行わず、公開対象から除外。全体3,090件は前回隔離候補＋本修正の結果で、この並行Console差分との統合を認定しない。[保全記録](PROTECTION_CHECK.json)。

**反映・公開は準備状態。今回追加分は未Push。実口座/本番稼働・定期実行の検証ではない。**
