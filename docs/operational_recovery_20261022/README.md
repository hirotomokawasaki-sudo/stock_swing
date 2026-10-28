# 2026-10-22: 保有ゼロ時の誤HALT修正

## 現在の結果

- 修正は稼働側の `paper_demo` ソースへ反映済み。通常リセットは **2026-10-22 15:29:33 JST** に成功し、状態は **`recovery_pending`**。
- **実際の定期実行による復帰は未検証**。10/22 **22:25 / 22:35 JST** の既存Paper定期実行で正常終了と `clean_run_verified` を確認する。時刻到来だけでは解除を保証しない。
- 22:50 JSTの読み取り専用ワンショット検証を登録・再取得確認済み（ID `3d3fde18-4e08-42aa-ab8f-bd832c6d79f5`）。結果は別の非公開証跡へ保存し、既存の本人通知先へ送る。検証ジョブは売買・再リセット・台帳修復・失敗ジョブの再実行をしない。
- Paper、強制停止、Economic Risk-Off shadow、既存のEXIT_ONLY設定は維持。実弾移行・経済性のNO-GOは解除していない。

## 原因と変更

取得成功の空配列 `positions=[]` が、long-onlyポジション辞書のtruthiness判定により `unrealized=None` のままになっていた。日初基準値の欠損が保存され、しきい値ルールが空でも欠損ガードによるHALTとなる。

既存のデータ取得・日初記録・ルールエンジン・通常リセットを再利用し、次の範囲だけを変更した。

| 対象 | 変更 |
| --- | --- |
| `guardrails/day_start_snapshot.py` | 生のbrokerポジションを検証して含み損益を合計。取得成功の空配列のみ0。short/fractionalも合計対象。 |
| `cli/paper_demo.py` | 日初記録、売買前、約定後、最終レポートで同じoptional値を使用。保存済み基準値が正常でも現在値の欠損をHALT対象にする。 |
| `reporting/console_summary.py` | 不明な含み損益・合計損益をJSONのnullとし、critical/missing_metricsを明示。 |
| `reporting/console_renderer.py` | 不明値はN/A表示。ゼロや整合済みequity bridgeを捏造しない。 |

非list、API失敗、不正な行・数量・銘柄・重複、含み損益の欠損/非数/無限大は不明のまま停止する。注文後の再取得失敗時も、古いポジションを診断表示に使うだけで正常復帰の根拠にしない。既存のexit経路・停止しきい値・売買設定は変更していない。

## 検証

- 旧ソースに対する実CLI回帰試験で、保有ゼロの初回実行・復帰実行の **2件とも実際の値の不一致で失敗**。修正版では合格。
- 新規回帰 **63件**：生payloadヘルパー30件、実CLI33件。外部HTTP/SDKのみ偽装し、実際の日初記録・リスク判定・breaker・レポートまで通す。
- 正常な空配列、同日不完全基準値の補完、short/fractional、API失敗、不正payload、欠損/非数/無限大、既存正常基準値ありの現在値欠損、dry-run、合成SELL後の取得失敗・不正行を確認。JSONはNaN/Infinityを許さず読み直す。
- 最終の焦点テスト **152件合格**。
- **最終全体テスト2,494件合格、2件skip**：外部ネットワーク・稼働data/config/reports/docsへの書き込みをOSで禁止した2,493件と、外部通信禁止/localhostのみ許可した認証テスト1件の非重複合算。既存のcollection warning1件あり。
- 既存collector試験1件が実FRED/稼働statusへ触れることを隔離で検出したため、そのfixtureのrootをtmp_pathへ、APIキーを空へ変更。セッションガードの実行自体は維持し、呼び出しも検証。製品collectorは変更していない。
- 独立コードレビューで停止条件、レポートへの欠損伝播、最終の異常行経路、範囲逸脱なしを確認。

全体試験の途中失敗や修正前の試験は、最終合格数に含めていない。新たな設定キー・既定値変更はない。正常/異常の境界、実CLIでの状態遷移、レイヤー間の値伝播、既存機能回帰を確認した範囲であり、収益改善・全戦略リプレイを証明するものではない。

## 稼働側での事前確認と通常リセット

15:29:31 JSTの新規broker GETにより、Paper口座のACTIVE、原台帳との口座一致、保有0、未約定0、台帳との不一致0、台帳不変条件合格を確認。現在の財務ルールはallow、発火なし。認証情報や口座IDは本文へ転記していない。

この新規証跡とコピーした既存台帳・設定を用い、実際の日初記録・ルールエンジン・breakerメソッドで `halted → recovery_pending → ok` をコピー上で確認した。ただし、これは完全なCLI/実定期実行ではなく、runtimeカウンターの実測正常性を証明しない。

続けて30秒以内の鮮度と保護ファイルhash一致を確認し、既存 `scripts/reset_circuit_breaker.py --note ...` の通常経路のみを使用。`force-ok` は不使用。結果は `recovery_pending / manual_clear`。保護対象の稼働データ変更はbreakerの通常リセット1ファイルだけ。日初基準値は手修正せず、次回の実定期実行で取得させる。

## 保存証跡と変更しないもの

非公開証跡は `.run/halt-flat-fix-20261022/`（ディレクトリmode700）に保存。

- 原ソース/設定/台帳/状態のバックアップとhash、作業前Git状態・全ジョブ定義。
- 旧ソース再現ログ、最終焦点/全体/localhost試験ログ。
- `preflight.json`、`canary.json`、`reset_receipt.json`、`reset_integrity.json`。
- ワンショット検証スクリプトと登録receipt、実行後の `scheduled_verification.json`。

原台帳・fill/event記録、売買/停止設定、Economic Risk-Off状態、canonical console、R22の隔離実装・既存のdirty差分は修正/復元していない。既存の売買ジョブのスケジュール・payload・通知先は変えない。手動の売買実行・発注・取消はしない。ソースは既存ジョブが起動する新規Pythonプロセスで読み込まれるため、サービス再起動は不要。

## ロールバックと残条件

コード差し戻しが必要な場合は、今回の所有する4ソースと3テストの変更だけを対象にし、停止状態を確認して進める。作業前コピーも非公開証跡に保存している。原台帳や過去breakerのバックアップを丸ごと戻さず、現在の口座・注文・停止理由を再確認する。古いソースでは同じ保有ゼロ不具合が再発するため、単なるリセットで代替しない。

ワンショット検証は、両定期枠の実scheduler receipt・ログ・正常終了・非dry provenance・canonical一致・当日broker基準値・台帳VALID/不一致0・最新breakerの正常復帰理由を照合する。いずれか未達なら復帰未確認として通知する。経済性・実弾移行・R22原台帳補正の承認は別条件のまま。

登録後、既存34ジョブの定義が不変であることと、新規1件の時刻・command payload・通知先・one-shot lifecycleを確認済み。検証器は正常なscheduler状態更新を許容し、不正証跡の51境界ケースを拒否した。実行ごとに更新される `updatedAtMs` は設定比較から除外し、`configRevision`・payload・schedule・enabled・deliveryは比較する。
