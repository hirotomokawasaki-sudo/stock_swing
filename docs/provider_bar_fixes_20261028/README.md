# P4 取得記録・時間足整合の隔離修正 — 2026-10-28

**技術対応完了／本番未適用・記録OFF／P4全体未完・F1未開始。**

ユーザー「対応して」に基づき、未完だった現行版照合・取得記録補強・5分足不一致の隔離修正を実装・検証した。新DB・新broker層・SDK追加・旧履歴修復はない。

## 完了した範囲

| 対象 | 実装と確認 | 完了と呼ばない範囲 |
|---|---|---|
| 現行版との適合 | 開始時fa386d1から、並行別件の8909e79（console alerts）を保持した現行treeへ照合。旧a322ea58を丸ごと適用せず既存recorderの保存・読取部分のみ再利用。台帳依存だったdirectory-fsyncを同じ処理のlocal helperへ分離 | 旧R22全修正・R14/完了足/U較正packet全体の現行版移植ではない |
| 時間足 | 日足・1〜59分足・1〜23時間足を正規化しMassiveのday/minuteへdispatch。5Min→1/dayを解消。Yahooは日足のみ。週/月足はMassive/Yahooを飛ばしbrokerへ。未知intervalはHTTP前に拒否 | providerの集計窓・完了足・公開時刻・実運用発生件数の認定ではない |
| 取得記録 | 要求interval/feed/adjustment、応答adjusted/request_id、UTCローカル受信時刻、HTTP body bytesのSHA-256、別のdecoded JSON hashを保存。各Canonical価格へ版hash・保存refを結び、通常run readerで追跡 | HTTP body原bytes自体は保存しない。暗号化wireの取得・完全replay・公開時点の証明ではない |
| 実呼出元 | 隔離CLIの明示opt-in `--capture-provider-contracts`から既存recorderを注入。通常OFFは保存storeを作らず、ONではrun_idに結ぶ。direct broker 5Min経路も取得receiptを保存 | 日次以外の全provider/全candidate/全consumerの捕捉ではない。設定追加・本番ONは未実施 |

MassiveはSDKの`raw=True`で同じHTTP要求のresponse metadataを得る。追加のmetadata通信はせず、複数pageも個別版として保存。cursor URL自体は保存せず、非許可host/循環pageを拒否する。既存SDK2.7.0の46 Pythonファイルを固定した。[互換性の内訳](compatibility.json)

**要求既定と応答事実は別欄**。Massiveの要求adjustment省略はnull、応答adjustedをそのまま保持。Alpacaは実際のIEX/raw要求を保持。Yahooの調整basisは不明のまま。異なる基準を同一として認定する処理・価格補正は加えていない。provider_first_publication_at/provider_final/bar_window_endはnull、research_qualifiedはfalse。ローカル受信を公開時刻へ読み替えない。

## 検証

- **全体2,719成功・3skip**：外部通信/本番repo書込禁止2,718＋別localhost限定1。既存collection warning1。重点や追試を合算しない。[全体ログ](full_suite.log) / [localhostログ](loopback_test.log)
- **重点90ケース**：新provider37・実CLI4・再利用storage45・既存Massive4。通常、欠落/破損、fallback、別pageの調整flag、未知interval、UTC/JST、secret拒否、保存失敗、raw/decodedの版hash、改変/欠落blob、実CLI→通常readerを確認。
- 同じ旧constructorで動く回帰6ケースは**旧版5失敗・1成功→候補6成功**。旧版の3つの分/時間足dispatchとUTC/JST両方のUTC-aware出力が失敗、日足controlは成功した。[旧版ログ](baseline_regression.log)
- 実CLIコピーの正常OFF/ON×UTC/JSTの4実行で、確認対象の判断行・HTTP要求・main戻り値0が一致、GETのみ・注文0。別の欠落入力1実行はdriver 0でもmain 1、sealも失敗を維持。保存拒否のOFF/ON 2実行は判断/HTTPを保持してONのmain 1・sealなし。全7コピーを含む4ケースであり、全業務等価性の証明ではない。
- 最初の試行で、旧候補の8ケースが未移植のexecutor/audit等に依存すると判明。今回の対象外である旧callsiteテストは再利用対象から外し、保存部分45ケースを再利用した。UTCでの全体試行にあった既存consoleのJST前提1件とnetwork deny下のlocal server1件は、全体をJST、local nodeを分離して再確認。新しいmodule欠落の途中失敗も現行8909e79を完全に取り込んで解消。途中失敗は最終成功数に含めない。

[機械可読の結果](VALIDATION.json) / [テストチェックリスト](TEST_CHECKLIST.md) / [主張と限界](CLAIMS.md)

## 保存先だけから再現

完全なcandidate source閉包、重点tests/driver、変更前の5 source、source pin・SDK/依存version・patchを本packet内へ固定。再現時に稼働source/Git/最新価格/認証を参照しない。manifestは公開署名ではなく、手元の固定packetに対する整合確認である。

```sh
env -i PATH=/usr/bin:/bin TZ=Asia/Tokyo PYTHONDONTWRITEBYTECODE=1 \
  /usr/bin/sandbox-exec -f deny.sb \
  /Users/hirotomookawasaki/stock_swing/venv/bin/python -I -B \
  verify.py --output /tmp/provider-bar-replay.json
```

既存venvを再利用しinstall不要。別配置でも元の本番repoの書込禁止を保持する。verifierは全path/hash/mode、199 source pin、依存version、SDK46 file、import originを先に検査し、一時copyで90ケースと旧版6ケースを実行する。**全体2,719件の再実行ではない**。保存結果とのbyte一致、欠落/改変/余分なfile/破損manifestの実行前拒否を確認する。

## 差分・復帰・残条件

現行base `8909e79c1a83e04d508715b132575625454b7856` → runtime `9cb1b75` → tested `067d23b`。runtime8 file・tests/fixture5 file。[runtime.patch](runtime.patch) / [tests.patch](tests.patch) / [combined.patch](combined.patch)

現行mainへの**read-only** `git apply --check`は成功。使い捨てrepoで順次・逆順復帰・結合適用のbytesを照合し、bytesが一致した後だけGit記録modeを復元した（restrictive umask対応）。[確認](patch_validation.json)。本番には適用していないためruntime rollbackは不要。採用前の破棄はこの候補を使わないだけでよく、将来配備する場合はその時点の実source/config/稼働確認を別途行う。

本作業で本番source/config/金融4原本/R14原ログ・scheduler/認証/CB/注文/サービスは変更していない。開始後の別件commit8909e79を取り込み、その後の408保護fileのhash/modeとmain HEAD不変を照合。[保護確認](protected_check.json)

**P4は10/30（金）18:00 JSTの確認目標を維持し未完**。実provider受信/完了足の適格証拠、全候補/no-signal/設定/exit/lot/pending/予約、正式な費用、実較正区間・正式U、資本制約由来のepsilon/delta/必要損失低減、標本・正式判定計画が残る。保存fixtureを実標本へ移さず追加適格0、T0未設定/F1未開始。主C11対U/P0/cap30%・既存Required・P1〜P3の完了/P5〜P11の日程は維持。IBKR前提・社内規程未確定のまま、仮の制限は作らない。

取得契約の確認根拠は[Massive公式Custom Bars](https://massive.com/docs/rest/stocks/aggregates/custom-bars)と[Alpaca公式Historical bars](https://docs.alpaca.markets/us/reference/stockbars)（10/28に再確認）、および固定SDKの実装。前者の分割調整既定・adjusted/request_idと、後者のinterval/feed/adjustmentは要求metadataの解釈にだけ使い、今回の合成応答をライブ資格認定へ昇格させない。
