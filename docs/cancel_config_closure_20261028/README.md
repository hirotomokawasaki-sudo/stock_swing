# 取消状態の隔離是正・消費時設定記録・公開版追試 — 2026-10-28

ユーザー「すすめて」に基づく3点。**本番未適用・実注文/取消なし・追加Push/mergeなし**。前回候補を保持した既存是正1バッチ内の追加で、利益試行ではない。

## 結果

| 対象 | 今回の到達点 |
|---|---|
| 取消 | 合成HTTPで実BUY/SELL選択関数、手動取消script、reconcile mainを19条件×2版＝38対照、再実行を含め42 processで比較。取消API成功を完了とせず再照会、requested/unknown/terminal/heldと未解決の非ゼロ終了を分離。受付後の強制終了→新processでは旧版2DELETE、候補1DELETE。POSTでの代替解消なし |
| 理由・予約 | 確認済みcanceled・filled_qty0だけの理由削除。pending/unknown、filled、部分約定後canceledは理由保持。未解決取消があれば協調guardの新規BUY/同銘柄解消を保留。予約ledgerの再構築・実資金解放の証明ではない |
| 設定記録 | 明示opt-in `--capture-config-instances`、通常OFF。到達した9種類・39fieldを消費前に複写し、許可済み環境キーの存在だけを記録。生env/秘密値は保存しない。6条件×前回/今回OFF/今回ON＝18実CLIケースで判断・注文数量・対象SELLを維持。記録失敗・非有限値・拒否文字列はwarning/非ゼロ終了、summary JSON/rendererへ伝播 |
| 既存候補の回帰 | 全体3,014成功/3skip＋分離localhost1成功＝重複なし3,015成功。既存collection warning1。通常CLI40ケースは前回期待値と一致。重点回帰/保存先追試は全体件数に加算しない |
| 公開物 | 公開commit e2d98eeをHTTPSで新規clone。7packet全inventory/hash一致。Gitで失われた595 fileの権限をmanifestとbyte一致後だけ復元。最新の**前回**候補を重点355・scripts148・並行4・CLI40で再現。これは新候補の合格数ではない |

[今回の範囲](SPEC.json)、[追加12path](delta.patch)、[現行mainからの累積26runtime＋18test/fixture](combined.patch)、[patch往復](patch_validation.json)、[公開版の実測](PUBLIC_CLONE_REVIEW.json)。新9runtime差分・3test差分。既存SDK/TradeEventStore/SubmissionGuard/account-route flockを再利用、新SDK/DBなし。

## 保存先だけからの検証

```sh
/Users/hirotomookawasaki/stock_swing/venv/bin/python -B \
  /Users/hirotomookawasaki/stock_swing/docs/cancel_config_closure_20261028/verify.py \
  --output /tmp/cancel-config-replay.json
```

保存先のみの追試済み（[receipt](packet_replay.json)）。最初に全inventory/hash/mode/依存を確認し、使い捨てsourceへ解決したimportを確認する。重点427、取消38対照/42起動、設定18・通常40CLIを再実行する。外部通信/稼働repo書込はOS sandboxで禁止。全体suiteに必要な私有financial fixture2点は複製せずhashだけを保存。元のmode-sensitive verifierはGit cloneだけでは通らず、byteを確かめた明示mode復元が必要。signalの私有inputs.zip/input_manifest.jsonは公開版にはなく、公開subsetの生データ追試は未可能のまま。

## 残る境界

- broker実受付/約定、完全な同時点snapshot、実provider/口座資格、非協調端末/外部発注、電源断を認定しない。全callerのexactly-onceでもない。取消選定の旧時刻/市場窓/政策は変更せず、再設計の正しさも認定しない。
- 取消terminalの読取と台帳へのfill取り込みは別。partial/filledの理由を残し、会計的な完了/資金解放を捏造しない。既存cleanupや他writerの全閉包、非終端status/複雑注文、末端アダプタの契約は残る。
- 記録対象は生成済みCLI instance9種だけ。到達しない分岐、生成失敗、暗黙helper・下流上書き、全環境設定/ファイル設定の完全な再現ではない。記録するために未使用設定を有効化しない。記録失敗は売買policyと区別する。
- L0/F0（固定意図・整数残を未完表示）を保持し、L1/L2や小数株を採用しない。P4全体未完・T0未設定・F1未開始、主C11対U/Required/既存日時/試行上限を維持。本番適用、記録ON、認証/scheduler/CB、main統合は別の状態。
- 初回全体試行は相対PYTHONPATHが子processのcwd変更で破綻した1件とnetwork-deny下のlocalhost1件で失敗。絶対source pathに固定し、localhostを分離して上記成功を確認した。初回取消driverには既存baselineにもDELETE再送停止が入っていることを見落とした期待値があり、応答不明と別run再送を分けて是正した。失敗した初回を成功件数へ加算しない。

**今回の成果物はローカル保存。公開Push済みは前回e2d98eeのみ。** [検証receipt](VALIDATION.json)と[テスト基準](TEST_CHECKLIST.md)に結果を保存。[保全確認](PROTECTION_CHECK.json)・[工程表の保存確認](plan_check.json)も添付。
