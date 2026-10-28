# 購入停止銘柄の観測・再検証候補通知

2026-10-28、ユーザーの「整備して」に基づく観測専用の実装。
[事前固定仕様](SPEC.md)に沿い、**自動解除・注文・実取引PFの補正は追加していない**。

## 追加したもの

- 実際のentry filterでPF理由により除外されたBUYを、売買台帳とは別に記録。
  decision/run/strategy/version/実効設定を保存。過去ログからの観測補充はしない。
- 同じ銘柄の重複・重なった5営業日の値動きを独立サンプルとして数えない。
  取得済み日足のみ使用し、基準20bps/ストレス30bpsのround-trip費用を控除する。
- 30件以上、ストレスPF≥1.20/平均>0、前後半とも平均>0、期間内最悪安値≥-7%等を満たすと
  **再検証候補**になる。日数経過による解除はない。数値は調査着手の目安であり、有意性の主張ではない。
- Console JSON/テキストに状態・件数を表示。候補は既存`--telegram`サマリー冒頭へ追記する。
  新しい別送通知や毎回の追加送信はない。テストでは外部通知をfixtureに置換し、実送信していない。
- 同日の追加依頼で、CLIのALERTSとWebコンソールの「概要 → 要対応アラート」にも候補を接続。
  表示条件・鮮度・画面検証は[コンソールアラート](CONSOLE_ALERTS.md)を参照。
- 候補になっても`eligible_to_trade=false`。本来のExit戦略・実コスト・損失制御による別検証と
  ユーザー承認が済むまで解除しない。本実装は解除機能自体を持たない。

固定5日価格診断は、現行Exit/配分/リスク制御の完全な仮想運用ではない。
実運用のPFや失った利益と混同しない。注文前の後段ゲート通過も保証しない。
明示的購入禁止は再検証候補の対象外。既存PFゲートの再計算方式も変えておらず、
新しい永久停止ラッチを追加したわけではない。

## 保存・設定と障害時

- 保存先: `data/analysis/entry_restriction_review_v1.json`。
- 開始時に仕様と関連source hashを凍結し、checksum付きatomic replaceで保存。
  非blocking排他ロック。別の観測プロセスが停滞していてもSELL処理をロック待ちさせない。
- 通常ジョブでもopen/closeのentry設定が異なる。実効entry/signal設定をcohort識別に含め、
  設定間の成績を混ぜない。source/評価仕様が変わった場合は明示的新versionまで保留する。
- 破損・保存不能・欠損・未来/naive日時・矛盾した日足は候補ゼロとして保留。
  本来の購入停止やSELLの実行判断は変えない。完成結果は履歴価格が後日改訂されても書き換えない。
- `ENTRY_RESTRICTION_REVIEW_ENABLED=false`は観測だけを無効化。
  既存PF bypass/env/購入禁止リスト・Paperモードには一切触れない。
- dry-runは観測storeを作成/更新しない。新規依存ライブラリ・価格API・DBなし。

## 稼働確認と完了境界

既存4売買ジョブは稼働checkoutのvenvで毎回新規Pythonを起動するため、次回実行から読み込まれる。
手動のpaper_demo実行・発注・取消・broker API確認は行っていない。source importと
有効設定を確認した時点では本番storeはまだ存在せず、**実定期実行・前向きデータ蓄積は未確認**。
テストの合格は経済的有効性や解除承認の根拠ではない。

次の通常取引セッションは米国10/28（JST10/28夜〜10/29早朝）。
引けjobは10/29 04:55 JST、timeout7200秒+15分の確認猶予を含め、07:10 JST以降に読み取り検証する。
PF除外候補がゼロなら「起動確認」と「実候補の捕捉確認」を分け、証拠を捏造しない。
最新非dryログ/consoleのrun IDと実完了receiptを照合し、観測status/store checksum/件数を確認する。
将来の確認結果は `.run/entry-restriction-review-20261028/scheduled_review/` に分離し、canonical出力は上書きしない。
読み取り専用one-shot `bee2c2f4-9e2a-4166-8f1a-e243ac62f96b` を**10/29 07:10 JST**に登録・再取得照合済み。
この会話へ結果を返す。既存36ジョブの設定は変更せず、この確認1件だけ追加した。
なお現ターンのautomations runs取得は既存jobをnot-foundと返したため、履歴確認が済んだとは扱わない。

## テストと保全

最終件数・follow-up ID・稼働保護ファイル比較は[VALIDATION.json](VALIDATION.json)を参照。
非公開の実行ログ・変更前source・ジョブ設定・hashは `.run/entry-restriction-review-20261028/`。

チェックリスト（docs/testing_standards.md）:

- [x] public API正常/新規store/空入力/破損/不足/保存失敗/lock競合を確認。
- [x] 蓄積→候補/保留、欠損からの復帰、古い候補の取下げ、設定変更・別cohortの不合算。
- [x] config→観測→ConsoleSummary→JSON/renderer→実Telegram構築（送信だけ外部fixture）。
- [x] 29/30件、コスト・損失・期間一貫性、ET金曜/JST土曜、DST・祝日。
- [x] 実CLIは外部HTTP/SDKだけfixture化し、PF除外と発注ゼロ、取引履歴不変を確認。
- [x] 有効/無効/破損で実CLIの外部HTTP要求が完全一致。dry-runはstore非更新。
- [x] 全体テスト（外部通信禁止、localhost必要1件だけ分離）。既存collection warning1件。

## 復元

観測だけ止める場合は上記enabled envをfalseにする（通常の設定変更として既存設定を確認・保存してから適用）。
コードを戻す場合は本変更commitだけrevertし、他のdirty変更を巻き戻さない。
観測storeは証拠として保持し、削除・PF台帳への合算・自動リセットはしない。
新しい評価仕様やsourceで再開するときは旧storeを保存し、明示的にv2の保存先/仕様を定義してから
新しい前向き観測を開始する。既存の損失履歴や購入停止設定を消さない。
