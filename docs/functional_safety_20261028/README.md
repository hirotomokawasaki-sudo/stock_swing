# K03の隔離是正・K01/K02限定再現・実効設定/入力表 — 2026-10-28

**K03の対象2経路の修正候補を隔離検証済み。本番未適用。K01/K02/K04の是正全体、P4全体、正式比較F1は未完/未開始。**

ユーザー「すすめて」に基づく、[既存K01〜K04工程](../strategy_improvement_validation_plan_20261020.md#functional-improvement-schedule-20261028)の前倒し。baseは`8909e79c1a83e04d508715b132575625454b7856`。既存risk budget、PaperExecutor、ConsoleSummaryと既存の隔離HTTP driverを再利用し、新基盤/SDK/有料サービスは追加していない。利益比較や戦略条件の追加でもない。

## 1. 実施結果と境界

| 対象 | 今回の結果 | 未完/未検証 |
|---|---|---|
| K03・台帳risk guard | 旧版は欠損/破損時にguardをskipし、実CLI dry-runのBUYが残る。候補はBUYを保留、risk比率をnull、状態をunavailable、runをDEGRADEDへ伝播。正常な空台帳のBUYは維持 | 実broker・正規scheduled run・本番適用なし。全入力の整合性/台帳完全性を証明しない |
| K03・保有露出計算 | 旧executorは集計例外で露出0へ戻る。候補は不正な口座/保有入力をunknownとし数量0・明示理由を返し、BUY submitを拒否。確認済み保有数量を渡したSELLは既存経路で通過 | precomputed数量を外部から直接渡す全呼出元の資格検証、CLI上流で不正broker応答が起きる全経路、SELLの全異常系は未完 |
| K01・集中上限 | cloud保有34,000＋購入3,000（上限35,000）、上限ちょうど35,000からの追加、同batch30,000＋3,000＋3,000が当該guardを通ることを再現 | helper/判断チェーンの限定再現。実際の超過約定や損失額、全submit経路は未確認。今回修正なし |
| K02・同一銘柄 | 異なる2戦略のAAPL BUYが優先付け→DecisionEngine→cooldownを別IDで通過。保有10株のBUY/SELL競合も残る | 実際の重複/往復約定を示さない。集約数量/優先規則は未確定、今回修正なし |
| K04・設定 | 実CLIで入口YAMLをenabled:falseにしても判断は同じ、CLI momentum閾値変更では候補が消える。出口YAML欠損は既定値へ、null YAMLはAttributeErrorで中断 | 未使用flagは有効化していない。出口nullの修正、全設定/環境変数の消費閉包と実scheduled runの設定receiptは未完 |

[設定・不足入力の対応表](CONFIG_INPUT_MAP.md)／[技術仕様・残受入ケース](ACCEPTANCE.md)／[限定再現script](diagnostics.py)。

## 2. K03差分

[候補patch](candidate.patch)は稼働source5ファイルとtests2ファイルだけ。設定・閾値・注文優先/数量政策は変更しない。

- risk計算の欠損/不正schema/不正lot/非有限数/不正equityを測定値0にせず、unknownとして新規BUYを保留する。**確認済みの空tradesだけが0**。
- 既存のWARN4%/BLOCK6%、stop推定5/8/9%は維持。旧表示だけが5/8%になっていたため表示を実値へ合わせた。このstop推定は実stop/実現損失上限の保証ではない。
- 既存`PAPER_DEMO_SKIP_RISK_BUDGET=true`は、**計測できた値の閾値overrideに限定**。unknownの回避には使えない。これは意図した互換性差で、適用時に運用説明が必要。
- ConsoleSummaryのrisk比率はnullableとし、状態・警告・risk_budget_blocked stage・監査eventへ伝播。通常の数値表示は維持。
- executorの露出集計失敗は数量0・risk_inputs_unavailableへ。既存の確認済み数量によるSELL処理、runtime Paper限定、他guardは維持。

## 3. 検証

- **全体2,680成功・3skip**：外部通信/稼働repo書込禁止で2,679成功、別のlocalhost限定実行で1成功。既存collection warning1。[全体log](full_suite.log)／[localhost log](loopback_test.log)。重点テストや追試を合算しない。
- **重点75成功**：新K03契約47ケース＋既存risk/executor28ケース。旧sourceに同じ新47ケースを当てると46失敗/1成功。失敗はBUY漏れだけでなく例外/unknown表示/契約不足も含む。SELLの維持ケースは旧版でも成功する。
- **実CLIコピー10ケース**：旧版3、候補7。外部HTTP transportと時計だけをfixture化し、内部strategy/filter/executorは置換しない。全HTTPはGET、全てdry-run。`BUY 0`は既存の未sizing placeholder表示で、発注や数量0の実注文ではない。
- mainへのread-only `git apply --check`、隔離copyでの適用/逆適用とbyte復帰、封印packetだけからの重点/CLI/限定診断追試、欠落/改変/余分file/破損manifest拒否を確認済み。結果は[VALIDATION.json](VALIDATION.json)へ記録。
- 初回の全体試行は凍結実データfixture2点のコピー漏れ5件と、network deny下のlocalhost1件で失敗。fixtureを隔離copyへ追加し、localhostを分離して上記の最終成功を確認。稼働原本は修復/再構築していない。最初のpacket追試ではmacOSの`/tmp`と`/private/tmp`の別名をorigin検査が区別して失敗したため、driverで双方をresolveして再確認した。業務sourceの追加修正はない。

## 4. 保存先だけからの追試

```sh
env -i PATH=/usr/bin:/bin TZ=Asia/Tokyo PYTHONDONTWRITEBYTECODE=1 \
  /usr/bin/sandbox-exec -f deny.sb \
  /Users/hirotomookawasaki/stock_swing/venv/bin/python -I -B \
  verify.py --output /tmp/functional-safety-replay.json
```

[verifier](verify.py)はmanifest全file/hash/modeとPython/依存versionを先に確認し、source import先が使い捨てcopyであることを検査する。保存source/設定・baseline・合成HTTP/時計だけを使う。これは全体suiteの再実行ではなく、重点75・旧版47・CLI10・限定診断5の再現。全体suiteに使った金融fixtureはpacketへ複製せず、hashだけを保存した。manifestは公開署名ではない。

## 5. 次の作業・復帰境界

1. **10/30 18:00 JST**：エージェントがK01/K02のsizing後の購入額・pending/予約・競合政策を含む実入口受入仕様、K04の未使用/破損設定の最小是正仕様を提出。今回の候補を再実装しない。
2. **11/06 18:00 JST**：既存の最小隔離是正1バッチとしてK03候補を保持し、残りの完了/未完・実入口回帰・影響を提出。**11/13**の技術受入/条件付き適用案、既存P/S日程を維持。
3. **現時点の復帰**は未適用候補の撤回だけで、稼働コード/設定/台帳を戻す必要はない。将来適用する場合も、当時のsource hash/競合・nullable出力の消費先・新規BUY停止を含む復帰条件を再確認する。旧データbackupで後続記録を上書きしない。旧版に戻すと既知のBUY漏れが復活するため、機械的な逆patchを安全復旧と同一視しない。

**今回なし**：本番source/config/金融原本の変更、記録ON、scheduler変更、認証/注文/取消/CB操作、commit/push、利益比較/新候補選定。S3最大1案枠は未消費、主C11対U・Required・P4未完・F1未開始を維持。
