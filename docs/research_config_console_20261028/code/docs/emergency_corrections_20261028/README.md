# 緊急売却・買戻しの隔離是正候補 — 2026-10-28

ユーザー「すすめてください」に基づく、提示済み3点（再実行重複防止・結果表示/終了コード・再起動/並行/部分約定の検証）。**本番コード/設定/金融原本・記録ON・scheduler/認証/CB・実注文/取消は未変更/未実行。** 前回統合候補を保持した、既存是正1バッチ内の限定候補である。新しい利益試行ではない。

## 結果

| 項目 | 確認したこと |
|---|---|
| 修正前の不具合 | 実スクリプト2件の回帰テストが修正前に失敗。ACK喪失後の再実行で同じSELL/買戻しを再送 |
| 再実行 | 同一口座-route/銘柄/解消種別の手動意図IDを保持し、prepared/unknown/accepted/rejectedを再送しない。照会404/不整合はunknown/held |
| 並行/強制終了 | 別プロセスの同時実行と受付後kill→再起動。比較元は3回の実行で3POST、候補は最初の1POSTだけ。各submit内のHTTP retryではなく、別runの重複の比較 |
| 数量 | signed保有から既存同方向注文の未約定残を差引く。5株−(6注文−2約定)=SELL1、short13株−残4=BUY9。pending_cancelは枠を解放せず、変更中/不整合/上限ページ等は保留 |
| 表示/終了 | 銘柄別accepted/unknown/rejected/held/flat等とJSON・終了コード。unknown/held/rejected/未対応小数残は非ゼロ。「完了/約定済み」を無条件表示しない。終了0も約定保証ではない |
| 回帰 | 重点355成功（新規60＋既存295）。全体2,959成功/3skip＋分離localhost1成功＝重複なし計2,960成功。既存collection warning1 |
| 実入口比較 | 74条件×修正前後＝148対照、別プロセス198起動。並行/強制終了4対照・12起動を別集計、合計152対照・210起動。通常CLI40ケースの注文/保留/記録結果も前回と一致 |

[受入・状態/失敗試験・残条件](ACCEPTANCE.md)、[テスト基準対応](TEST_CHECKLIST.md)、[機械集計](script_summary.json)、[通常CLI期待値](expected.json)。結果は合成外部HTTP/人入力/ファイル障害を使ったコピー上のもの。実provider受付・約定・利益・本番運用復帰の証明ではない。

## 重要な適用境界

- **同じ手動解消意図1件**の候補である。意図IDをrun/数量/新snapshotから作り直さず、reject後も自動再送しない。新しいポジション世代を自動認定/解除する機能やID切替フラグは追加していない。将来の別保有・追加の正当な解消には別途ライフサイクル資格が必要で、この候補では保留する。
- 小数株の従来の整数切捨ては変更しない。3.7→3、-13.7→13を維持し、0.7残を明示して非ゼロ終了。銘柄NOW/IBM/HPE、成行DAY、人のyes/noも維持。小数株対応/数量政策の採用ではない。
- 協調lockを使わない別プロセス/端末、外部発注、state全削除、電源断、実brokerのidempotency/atomic snapshot/鮮度は未認定。2回の一致した読取は原子的snapshotや判断時点資格の証明ではない。全callerの重複防止、reduce-only機能や最大損失保証とは呼ばない。
- 本番へ配備していないため、**稼働中の元スクリプトが修正済みという意味ではない**。

## 差分・追試

既存SubmissionGuard/TradeEventStore/client ID/照会/flock、BrokerClient、runtime readerを再利用。新SDK/DB/依存なし。[前回候補からの5runtimeファイル差分](delta.patch)、[原本からの累積21runtimeファイル差分](combined.patch)、[新規2テストファイル](tests.patch)、[版/byte/mode](source_changes.json)。通常CLIの判断方式を変更せず、共通guardには実HTTP拒否の検証可能な記録形式、adapterには観測したHTTP status付与だけを追加した。

```sh
/Users/hirotomookawasaki/stock_swing/venv/bin/python -B \
 /Users/hirotomookawasaki/stock_swing/docs/emergency_corrections_20261028/verify.py \
 --output /tmp/emergency_corrections_replay.json
```

manifestの全inventory/byte/mode/symlink、Python/依存版/SDK46ファイルを検査してから、packetだけの一時コピーで重点355・実scripts148・並行4・通常CLI40を再実行し期待値を比較する。ネットワークと本番repo書込はOS sandboxで拒否。全体回帰は2つの私有financial fixtureを必要とするため、packet-onlyでは繰返さず、実行済みログとpinを保存する。git patchは600等のprivacy modeを表さないので、順逆適用では明示pinも復元する。未使用コピーでの逆適用は、実注文後にjournalを消して旧版へ戻す運用の認定ではない。

最新計画は§3.43。既存17工程/全日時・主C11対U/Required/P0/cap30%・是正1バッチ・S3最大1案未消費/S4固定1バッチ、P4全体未完/T0未設定/F1未開始を維持する。10/30 18:00 JSTに残条件/政策、11/06に不足込み一次結論、11/13に技術受入/固定比較または未完を確認する。これは新規通知/自動実行の予約ではない。
