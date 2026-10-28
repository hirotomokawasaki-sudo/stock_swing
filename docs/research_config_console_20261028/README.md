# 公開用の投影版

**元の封印済みpacketそのものではありません。** 個別判断・イベント別結果・価格入力を除外しました。集計結果は元と同じbyteです。`verify.py` は公開入力だけの技術追試（研究の合成契約24件・重点567件・実CLI44ケース・表示統合・任意Chrome）を実行し、私有入力の研究outcome/19,010セルや全体suiteは再実施しません。元manifestのhashと除外範囲は [PUBLIC_SCOPE.json](PUBLIC_SCOPE.json)、公開byte/modeは `public_manifest.json` を参照。Git取得後は `restore_modes.py` で全byte確認後に権限を復元してから追試してください。

以下は元の検証時点の報告です。「Pushなし」はその時点の履歴で、今回の公開操作とは別です。

# 5営業日診断・残設定経路・最新Console統合 — 2026-10-28

ユーザー「すすめて」に基づく3項目。**研究/隔離候補のみ。本番適用・記録ON・実注文/取消・Pushなし。** 最新Consoleは既存の稼働変更をコピーして検証したもので、今回の追加Console修正は未配備。

## 1. 5営業日後価格への接続

- 既存固定診断の未計算部分として、仕様を先に凍結し、元の4,532 decisionと既存69銘柄価格を使用。外部価格取得なし。原診断の入力・成果物を変更しない。
- **1,901保存BUY decision、53判断日**に接続（ET判断日2026-05-11〜08-07、最終outcome 08-14）。541件はBUY以外、2,090件は5session経路不足/不正。母数の分割は4,532件に一致。
- 判断日の**翌期待営業日open→5番目session close**。土日/休場を除外し、途中欠測を飛ばさず、SPYも同じentry/exit窓。片道0/2/5/10/15bpsを仮定し、株とETF、strategy、固定スコア帯を分離。同点は分割しない。
- 16区分、1,901イベント×5費用×stock/SPY差の**19,010算術セル**を別実装Decimalで照合。日内イベント平均→観測判断日平均も照合。診断契約24件成功。

例：通常breakoutの個別株、各帯に存在する判断日を等重み、仮定片道5bpsのSPY超過価格リターン：

| 保存スコア帯 | イベント | 判断日 | SPY超過（ポイント） |
|---|---:|---:|---:|
| .4以上〜.6未満 | 80 | 23 | +1.711 |
| .6以上〜.8未満 | 254 | 44 | +0.025 |
| .8以上〜1以下 | 1,120 | 44 | +0.774 |

**帯ごとに日付/銘柄/版の構成が異なるため、帯の差を選別効果としない。高スコアの優位性や採用する閾値は未認定。** 全16区分・全費用・不確実性は[results](research/results.json)、[仕様](research/SPEC.json)（個別イベントは非公開）。重複する銘柄/日・保有窓を独立標本と数えない。

これは保存価格による探索的**proxy**であり、当時利用可能時刻・価格改訂/調整basis・歴史分類・完全な全候補/no-signalは未証明。配当込み総収益でも実約定/口座PF・DDでもない。20session block感度は4000有効再標本/seed7、全区分とも独立局面が少ない。2blockに満たない窓では退化した区間を出さず「不足」。空drawは除外数を記録して補充する。正式な有意差判定やedge確率へ格上げしない。

**適格な前向き観測の追加0、S1/S2全体未完、S3最大1案枠未消費・S4未開始、主C11対U・T0/F1未開始を維持。**

## 2. 設定の残経路

既存のopt-in recorderへEntryFilterConfigとLosingPositionAddGuardConfigを追加し、**11family/51field**に拡張。from_envの戻り値を消費前に記録し、生成失敗は型だけ記録して元例外を再送出。入力に問題がある時の従来の中断/継続/fallbackを変更しない。OFFは従来と同じ。helpの古い「nine」は数に依存しない表現へ更新。

EntryFilterの同一オブジェクトがEngine・既存helper・観測へ渡ることを照合し、engine.configのaliasやlistへの持続的変更も終点で検出。既存helperの暗黙fallbackは残し、未到達設定を観測のために生成しない。[AST監査](CONFIG_PATH_AUDIT.json)は明示call26箇所を分類したが、動的/反射/外部caller、途中変更後に元へ戻す場合、全設定の閉包ではない。

新10契約は修正前5失敗/5成功→候補成功。**11条件×前回/今回・各OFF/ON＝44実CLI**で判断・注文対象・数量が一致。必須構築失敗、無効値、購入制限、disable、fallback、dry-run、書込不能を含む。旧9familyのreceipt内容も維持。記録異常時のみONの警告/非ゼロは既存契約のまま。

## 3. 最新Consoleとの統合

- 最新のConsole5変更＋読取service/受入47件を、前回安全候補と同じコピーへ統合。
- 統合probeで、broker取得失敗時のaudit-only小数qtyが共有旧parserで0へ落ちることを再現。**保留注文の表示経路だけ**修正し、小数を保持、欠測/不正/負数はnull→「未取得」。共有parserの他consumerや売買数量計算は変更しない。正しい整数の型も維持。修正前は正しい回帰5失敗/1成功→候補6成功。
- guardの実取消処理→HTTP境界→service→JSON→実JSで、pending_cancel/canceled/partial/404の4条件を確認。各1DELETE、再実行は照会のみ。未確認を取消完了にしない。11familyはsummary JSON→実text rendererへ伝播。
- **Web UIはeffective_configの個別receiptをまだ消費しない。** 今回新しいWeb設定panelを作ったとは言わない。記録の確認先はCLI/JSON/text。
- コピーの実HTML/JS/CSSと実serviceからの合成APIをChromeで描画。未計測DD、取得失敗、audit数量3.7、未確認注文、終了≠成功、稼働未反映を確認。タブ往復2回、reload1回、390px画面幅=390px、pageerror0。全HTTPはlocal fixtureへrouteし、IP通信をOS禁止。Chrome内部Unix socketだけは許可。実サービス/実broker/定期実行の資格ではない。
- 文書根拠snapshotはplan/readinessとのhash差で**stale**。コピーでも要再確認を保持し、hashだけ自動更新しない。後続計画追記も本番snapshotの更新ではない。

## 4. 検証・差分・追試

全体は**3,155成功/2skip＋分離localhost1成功＝重複なし3,156成功/2skip**。重点567・診断24・CLI44をこの全体へ足して水増ししない。既存collection warning1。初回はpytestの対象を広げ過ぎ、scriptsの手動接続probeをcollectionしてOS拒否で停止。正式対象tests/と正しいlocalhost分離へ修正した。実接続や本番書込は行っていない。

[追加差分](delta.patch)は前回安全候補＋最新Consoleからruntime3/test3ファイル。[累積差分](combined.patch)は捕捉した稼働worktreeからであり、元HEADだけへの適合とは別。[適用/逆適用](PATCH_VALIDATION.json)はコピーの全byte/Git実行bit一致、mainではcheckのみ。全permissionはmanifestで別検証。[受入](TEST_CHECKLIST.md)、[導入/切戻し](DEPLOYMENT_REVIEW.md)。

```sh
/Users/hirotomookawasaki/stock_swing/venv/bin/python -B \
  /Users/hirotomookawasaki/stock_swing/docs/research_config_console_20261028/verify.py \
  --output /tmp/research-config-console-replay.json --browser
```

追試はinventory/hash/mode/依存・隔離importの確認後、診断/独立算術/24契約・重点567・実CLI44・取消/表示4条件・任意Chromeを保存先だけで再現。全体suiteの私有financial fixture2点は含めず、全体3156を保存先だけで再実施したとは言わない。Chrome/Playwright/Nodeは既存ローカル依存、実行時にダウンロードしない。chart固定version2本を同梱し[取得hash](vendor_receipt.json)に分離（価格/API取得ではない）。

初期browser probeは全network禁止がChrome内部Unix socketまで止めたため起動失敗。IP送受信/原repo書込拒否を維持し、Unix socketだけ許可した最終probeが成功。初期統合probeの404は「有無は未確認」という空表専用文言を期待したdriver不備もあり、実際の行あり警告「取得未確認」とunknownを確認するよう修正。成功件数へ初期失敗を加算しない。

元の666 source/config/Console/test等・HEAD/indexと既存封印物を照合。mutable金融/稼働ログ全体を凍結したとは言わない。共有4計画への追記以外、本番source/config・台帳・記録ON・scheduler/認証/CB/service変更なし。旧17工程/日時・是正1バッチ・L0/F0・Required/P0/cap30%を維持。研究と技術検証は利益認定/配備/真正scheduled実行の証拠ではない。

保存先のみの最終追試は[PACKET_REPLAY](PACKET_REPLAY.json)に記録。改変・欠落・余分・manifest破損・mode変更・symlinkの6拒否境界は[INTEGRITY_NEGATIVE](INTEGRITY_NEGATIVE.json)。最終receiptを取り込んだ後でmanifestを封印した。
