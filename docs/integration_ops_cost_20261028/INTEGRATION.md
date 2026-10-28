# 統合の実施範囲と受入

## 版と変更

基準HEAD8909e79c1a83e04d508715b132575625454b7856。前回advance_all候補にprovider_bar_fixes候補の8runtimeファイルと5テスト/fixtureを重ねた。BrokerClientは3-way clean merge。CLIはRunContext後の初期化が1競合し、`_config_receipts=[]`とopt-in `DecisionInputRecorder`初期化の両方を保持した。これ以外の新しいruntime判断は追加していない。[差分一覧・byte/mode pin](source_changes.json)、[前後適用/逆適用](patch_validation.json)。patchはruntimeだけ、既存金融data・.envは含まない。

保持したもの：unknown-risk BUY保留、実数量の購入後/予約込み上限、同銘柄競合BUY保留、POST/DELETE1回とGET再試行、安定ID/照会・fsync履歴/協調lock、使用設定異常時のBUY保留/既存missing-exit既定値での対象SELL継続**未採用案**、分類漏れ関連BUY保留。並びに時間足・fallbackルート、requested feed/adjustmentと応答adjusted、HTTP本文SHA/decoded JSON SHA、UTC受信時刻・版・canonical bar参照、記録seal。

**保持していない/未完**：実口座のfresh/atomic snapshot、異なる新decisionの経済的同一性、全callerへのjournal接続、非協調実行、state全削除/電源断、実providerのidempotency保証、全設定reader、詳細ETF look-through。旧P1/P2全記録候補を全面的にportしたとは主張しない。public-first/final/window_endは未証明/null、research資格はfalse。CLIが0でもDEGRADED/unknownを別に判定する。

## 検証

| 実行 | 観測 |
|---|---|
| 重点11ファイル | 295 passed |
| 全体、localhostの1nodeをdeselect | 2,899 passed,3 skipped,1 deselected、既存collection warning1 |
| 分離localhost（外向き通信不可） | 1 passed。全体との重複なし、合計2,900成功 |
| OFF19条件 | 前回安全候補の凍結expectedと数量/順序/警告/保留理由が一致 |
| ON19条件 | OFFと業務結果一致。provider_response/canonical_provider_bars/run_endを保存しload_input_runでseal/参照/ハッシュを検証 |
| 記録不可2条件 | 正常BUY61株、SELL1株＋BUY61株の判断は不変、main1、sealなし。記録失敗を成功にしない |

19条件は正常、SELL+BUY、ACK喪失/照会未発見・一致発見、分類3経路（新候補/保有/pending）、使用設定異常12条件。内部strategy/filter/allocator/executorは差替えず、外部HTTP/時計/ファイルだけ合成。照会不明時MSFTのPOST1回・次BUY保留、同一照会回復時の後続処理を確認。これは実注文/約定・全ての同時実行・将来観測の証拠ではない。

合成履歴のcapture_complete/declared_exit_success=trueは保存・終了の記録。unknownケースでもmain0/DEGRADEDがあり、全件full_replay_ready=false。保存資格と金融的成功を混同しない。

全体回帰で使った私有fixtureはpnl_state/klac_split_investigationの2つ。未コピーの原金融dataには書き込んでいない。packet-onlyは全体回帰の再実行ではなく、同じ重点295件＋CLI・scripts・auditを再実行する。
