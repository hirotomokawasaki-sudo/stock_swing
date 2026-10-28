# 10/28 追加前倒し：統合検証・直接発注経路・費用ログ

ユーザー「すべてすすめて」に基づく3項目の成果。**本番source/config/金融原本・記録ON・scheduler/認証/CB・実注文/取消は変更/実行していない。** 利益比較・S3の追加案ではない。

| 対象 | 実施結果 | 未認定/残条件 |
|---|---|---|
| provider/時間足/記録候補とK01〜K04・再送/分類候補の統合 | 同じ8909e79基準で統合。CLIの初期化競合1箇所は記録初期化と設定receipt初期化の双方を保持。重点295成功、全体2,899成功/3skip＋分離localhost1成功（重複なし合計2,900） | 旧P1/P2全候補の全面統合ではない。実provider/口座・当時利用可能時刻・確定窓/全入力資格・政策採用/本番配備は別 |
| 実CLI・記録ON/OFF | 19条件×OFF/ON＋保存先破損2＝40ケース。OFFは前回安全候補19条件と一致、ON/OFFの注文/数量/保留理由一致、ONはseal/ハッシュを読取検証 | capture_completeは保存成功。full_replay_readyは全件false。応答不明時のmain0/保存成功を取引健全とは扱わない |
| 緊急SELL・HPE買戻し実スクリプト | 23条件×安全候補/統合候補＝46ケース。内部submit/例外処理は実コード、外部HTTP/確認入力のみ合成 | 各submit1HTTPでも、同じ未更新保有の再実行で同一経済注文が再送される。SELLはエラー後も完了表示。小数株は切捨て。**是正済みではない** |
| API/AIログ・費用 | 5ファイル固定。現行240行/408,421記録tokens、API遅延1,399行。推定1,939decision/416,578tokensはJSON/CSV/旧archiveで重複、archiveのruntime31行も現行に重複。別計算で照合 | token欄は請求tokensではない。現行書込経路のcost0は固定値。実請求額/通貨/有料API総回数・OpenClaw費用は未確認。加算/外挿しない |

- [統合の境界・受入と再現](INTEGRATION.md)
- [直接発注経路の実測・残課題・最小是正仕様](OPERATIONS.md)
- [費用/使用量の根拠と不足](COSTS.md)／[集計](usage_summary.json)／[独立算術照合](usage_independent.json)
- [runtime累積差分](combined.patch)（原本対18ファイル）、[前回安全候補からの差分](delta.patch)（8ファイル）。新規runtime変更案ではなく既存候補の統合。テスト・検証driverはcode/と本packetに収録。

## 再検証

既存venv（Python3.13・environment.jsonの版/SDK46ファイル）を使用し、新しい依存は導入しない。manifestで全ファイルのbyte/mode/inventoryとsymlinkを検査してから、一時コピーのsourceに解決したimportかを確認し、重点295、監査10、CLI40、直接スクリプト46、費用集計一致を実行する。ネットワークと本番repoへの書込をOS sandboxで拒否する。全体回帰は私有financial fixtureに依存するためpacket-onlyでは繰返さず、実行済みログとfixture pinのみを収録する。

```sh
/Users/hirotomookawasaki/stock_swing/venv/bin/python -B \
  /Users/hirotomookawasaki/stock_swing/docs/integration_ops_cost_20261028/verify.py \
  --output /tmp/integration_ops_cost_replay.json
```

ログ/manifest/環境pinは改ざん検出と再現性確認であり、第三者署名や約定/利益の証明ではない。privacy modeは明示pinを復元する（git patch単体は600等の非実行権限を表さない）。

## 計画の扱い

最新は詳細計画§3.42。既存17個のP1〜P11/S1〜S6行と日時は維持。是正1バッチ、主C11対U/Required/P0/cap30%、S3最大1案未消費、S4固定1バッチ、P4全体未完・T0未設定・F1未開始を保持。10/30 18:00 JSTに実入力/政策/直接caller等の残条件、11/06 18:00に不足込み一次結論、11/13 18:00に技術受入/固定比較または未完を確認する。日付待ちそのものを作業条件にはしない。
