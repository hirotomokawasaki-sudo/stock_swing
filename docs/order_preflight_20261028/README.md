# K01購入後上限・K02重複/競合の隔離候補 — 2026-10-28

**実入口の限定範囲で修正候補を検証済み。本番未適用、K01/K02全体の完了・経済的改善の実証ではない。**

ユーザー「すすめて」に基づく既存是正1バッチの前倒し。[前回K03候補](../functional_safety_20261028/README.md)を保持して拡張した。稼働HEADは`8909e79c1a83e04d508715b132575625454b7856`のまま。既存broker Protocol、相関cluster、PortfolioAllocator、CLIの数量計算・HTTP fixtureを再利用。新DB/注文管理基盤、SDK、有料サービス、利益試行は追加していない。

## 1. 隔離候補の変更

- **K01**：数量計算後・submit直前に、保有評価額＋未約定BUY残数量の予定額＋同runの発注試行済み予約＋今回購入額を検査。既存の銘柄上限・重複する各cluster上限・株/ETF bandを維持し、上限ちょうどは可、超過は保留。未約定SELLで容量を空けない。Decimalで金額を比較し、恣意的な許容誤差は加えない。
- **入力不明**：注文取得失敗/破損/件数上限、重複order ID、未知status、複雑注文、不正数量/価格/保有を「露出0」にしない。同一銘柄の未約定BUY/SELLがある場合も新規BUYを保留する。未約定BUYは部分約定分を除いた残数量を予約し、確認済みterminal snapshotでは予約しない。
- **K02・未採用の政策案**：実行候補に同じ銘柄の複数BUY、またはBUY/SELL競合があればBUYを保留。数量の自動合算/netting、スコアによる勝者選択はしない。元decision/strategy/evidenceを残し、関連decision IDと保留理由を追記。SELLは既存の数量・市場時間・riskチェックを維持する。複数SELLの調停・lot配賦は今回未修正。
- **応答不明の局所封じ込め**：発注前にrun内予約を取り、試行後は保持。現行executorの`rejected`はtimeoutも含むため、単なる拒否と信用せず以後のBUYを保留。後述の通信層による最初の発注の再送は防いでいない。
- decision evidence、監査log、`reports/order_preflight/<run_id>.json`へ理由・予定額を伝播。ConsoleSummary専用schema/rendererの新項目は追加していない。`PAPER_DEMO_SKIP_CLUSTER_CAP=true`の計測済みcluster overrideは維持し、不明入力の回避には使わない。

[新規計算部](code/src/stock_swing/risk/order_preflight.py)／[CLI接続](code/src/stock_swing/cli/paper_demo.py)／[新60契約テスト](code/tests/unit/test_order_preflight.py)／[結果前に固定した仕様](SPEC.md)。

## 2. 実CLI比較 — 全て合成外部入力・実発注なし

dry-runではなく、**コピーした実CLIのsubmit経路**を実行した。内部strategy/feature/guard/allocator/executorは置換せず、外部HTTP transport・時計だけをfixture化し、重複ケースでは合成earnings raw入力をコピー内に置いた。OSで外部通信と稼働repo書込を禁止。全POSTはMockTransportが記録したbodyで、brokerへの注文や約定ではない。

| 合成ケース | 前回K03候補 | 今回候補 |
|---|---|---|
| 通常NVDA | BUY61株 | 同じBUY61株 |
| cloud保有34,000＋MSFT購入7,930 | SELLに加えBUYを送る | BUY保留、同じSELL維持 |
| 保有30,000＋CRM未約定1,300＋MSFT購入7,930 | BUYを送る | BUY保留、同じSELL維持 |
| 同batch・保有25,000＋MSFT7,930＋CRM7,930 | 両BUY、予定合計40,860 | 1件目後32,930、2件目保留。SELL維持 |
| 同銘柄の未約定／取得500件 | それぞれBUYを送る | それぞれBUY保留 |
| 2戦略の同一NVDA BUY | BUY61株を2件送る | 両BUY保留、元ID2件維持 |
| 同じNVDAのBUY/SELL | SELL1株＋BUY61株 | SELL1株だけを維持 |
| 受付後に応答喪失を模した外部例外 | MSFT3回＋CRM3回のPOST | MSFT3回は残る、CRMは送らない |

比較は**9条件×2版＝18ケース**。[実行記録](CLI_EVIDENCE.json)／[安定ID等を除いた比較値](expected.json)／[検証assertion](check_results.py)。価格130・取得内容・保有mark・時刻は合成入力で、実snapshotの整合性・当時価格・実損失を証明しない。

## 3. 検証と保存先追試

- **全体2,740成功・3skip**：外部通信禁止で2,739成功、分離したlocalhost限定ケース1成功。既存collection warning1。重点テストや追試を合算しない。[全体log](full.log)／[localhost log](loopback.log)。前回K03の対象も維持するが、他の全隔離候補との結合受入ではない。
- 新契約60成功。正常/境界/欠損・破損/NaN/Inf、部分約定・取消待ち・terminal snapshot、同batch、逆方向解放禁止、復帰、既存allocatorを検証。新public計算部に独自設定file読取/state永続化はない。ファイル/HTTP/設定は既存入口へ対応し、不正な取得内容とcap設定をfail closedにする。
- 前回K03に対する[追加差分](delta_from_k03.patch)と、現行稼働sourceに対する[K03込み一体patch](combined_from_main.patch)を保存。read-only `git apply --check`、使い捨てcopyで適用/逆適用後のbyte/mode復帰を確認。mainの保護660ファイルとHEAD、および前回packetのinventory/hash/modeは不変。
- [verifier](verify.py)はmanifestの全inventory/hash/mode・Python/依存version・解決済みimport先を先に検査し、保存sourceだけから重点135ケース（前回75＋今回60）と実CLI18ケースを再現する。全体suiteの金融fixture2点は複製せず[hash](fixture_pins.json)だけ保存したため、全体suiteのpacket-only追試ではない。manifestは公開署名ではない。
- 保存先だけからの追試で重点135・実CLI18ケースの比較値が一致。改変/欠落/余分file/破損manifestの4拒否も確認した。[検証receipt](VALIDATION.json)。

```sh
env -i PATH=/usr/bin:/bin TZ=Asia/Tokyo PYTHONDONTWRITEBYTECODE=1 \
  /usr/bin/sandbox-exec -f deny.sb \
  /Users/hirotomookawasaki/stock_swing/venv/bin/python -I -B \
  verify.py --output /tmp/order-preflight-replay.json
```

## 4. 未達条件 — 本番適用の承認依頼ではない

1. **CMP-C01・最優先**：最初の発注のHTTP自動再送が残る。今回の応答喪失ケースでも同一bodyを3回送った。安定client intent ID/照会、送信前の最小記録、未受付/受付済/結果不明の区別と再起動時の重複防止は未実装。現状をexactly-onceと呼ばない。
2. **snapshot資格**：現在のadapterに対し`fetch_orders(status=open,limit=500)`の短いflat pageだけを候補の完全入力と扱う限定契約。Alpacaの[公式Orders仕様](https://docs.alpaca.markets/us/v1.1/reference/getallorders-1)は最大500件。500件ならBUY保留にし、既存paginationの終了を無条件に信用しない。他brokerへの自動移植、取得中の約定との非原子性、鮮度・時点/通貨整合は未受入。
3. **価格/資金**：市場価格の予定額でありmarket fillの保証上限ではない。実bid/ask鮮度・価格余裕/費用、利用可能資金/受渡・買付余力の数量接続、静的cluster漏れ（CMP-C05）は未完。上限値・分類・口座規制を推測で追加しない。
4. **全経路/政策**：run内予約だけで、並行process、再起動、取消確定との照合、直接executor/precomputed caller全件、複数SELL/戦略間配賦、K04破損設定、ConsoleSummary専用伝播は未完。今回の競合vetoはレビュー案であり本番政策の採用ではない。
5. **適用/復帰**：本番未適用・正規scheduled run未検証。現時点の復帰は候補撤回のみ。将来の適用は当時のhash/競合・入力資格・不明BUY保留を確認し、後続台帳を古いbackupで上書きしない。旧版へ戻すと既知経路が復活するため単純な逆patchを安全復旧と同一視しない。

## 5. 既存工程への反映

**10/30 18:00 JST**のK01/K02仕様・実入口再現分を前倒し。次は同期限のCMP-C01最小封じ込め/照会回復仕様と、K04/分類coverage等の残不足を提出する。**11/06**の是正1バッチの残完了/未完、**11/13**の技術受入/条件付き適用案、P1〜P11/S1〜S6の日時は変更しない。ユーザーの未採用政策を推測で本番ONにしない。

今回変更したのは新しい隔離packetと計画文書だけ。稼働source/config/金融原本、記録ON、scheduler、認証、実broker注文/取消/CB、commit/pushは変更なし。K03の対象成果を保持し、S3最大1案枠は未消費、主C11対U・Required・P4未完/F1未開始を維持する。
