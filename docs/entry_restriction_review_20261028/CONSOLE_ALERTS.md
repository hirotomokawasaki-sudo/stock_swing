# 再検証候補のコンソールアラート

2026-10-28「コンソール上でもアラートが出るようにして」への追加実装。
既存のアラート契約・カード・mtimeキャッシュを利用し、新しい通知基盤や依存ライブラリは追加しない。
R6-v2/H3/H9の表示経路の拡張であり、評価仕様や昇格ゲートの変更ではない。

## 表示

Webコンソールの **概要 → 要対応アラート（画面上部）** に次を表示する。

> **購入停止の再検証候補（要承認）**
>
> 購入停止の再検証候補: IBM。購入制限は継続中。固定期間の価格診断のみ。本来のExit検証と解除の手動承認が必要です。

銘柄と最終観測日時、手動承認が必要な旨を表示する。解除ボタン/API・自動解除・注文は追加しない。
同一銘柄の複数cohortは通知を重複させず、詳細JSONにはcohortごとの件数を別々に保持する。
CLIも同じ内容をALERTSに表示する。候補通知は正常な研究イベントなのでseverityは`info`。
通知だけを理由にrun healthをDEGRADED/HALTEDへ変更しない。既存のcritical/warningは引き続き優先表示する。

## データ契約

- 観測結果 → 共通の読み取り専用formatter → ConsoleSummary.alerts → CLI renderer。
- 実非dry-runの`reports/console/latest_console_summary.json` → DashboardService.get_alerts
  → `/api/dashboard`のalerts → 既存`Console.renderAlerts()`。
- Webではrun.mode=paper、dry_run=false、invocation_source=paper_demo_scheduled、非空run_id、
  timezone付きtimestampが必要。未来日時・24時間超のsnapshotは候補通知に使わない。
- 観測status=observing、eligible_to_trade=false、automatic_release=false、候補リストと
  確認済みreview_candidate行の一致、必要件数充足・Exit検証/手動承認必須フラグを確認する。
  formatterはPF/価格の再計算やcohort合算をしない。
- 最新snapshotの候補取下げ/disabled/error、欠損/破損/不正形状時は旧候補を維持表示しない。
  mtime変更を検知し、古い正常ファイルへのfallbackもしない。
- **通知が消えても購入制限の解除を意味しない。** 表示は前回観測の情報であり、売買許可ではない。
- UI更新に新しい市場データ取得・観測store更新・再評価を追加しない。既存APIの60秒キャッシュと
  画面の更新方式を利用する。必要ならページ再読込。新しいscheduler/別送通知は作らない。

## 検証記録

実観測の成熟結果からCLIのalertsまで伝播する既存テストを強化し、Webの独立経路にも回帰テストを追加した。
実CLIのinvocation_source契約も固定し、想定名と実際の保存名のずれを防止する。

チェックリスト（docs/testing_standards.md）:

- [x] 正常候補、候補なし/不足/不正行、複数cohort、解除不可フラグを確認。
- [x] 欠損/破損、未来/naive時刻、24時間境界、dry-run/live/誤provenanceを確認。
- [x] 候補→取下げ→再候補→破損→欠損でキャッシュに古い通知が残らない。
- [x] 実サービスのget_alertsからJSONを経て、実app.jsのHTML描画・escaping・解除ボタンなしを確認。
- [x] 隔離コピーの実ConsoleHandler/get_dashboard/API/既存UIをChromeで表示し、DOMとスクリーンショットを確認。
  broker資格情報なし、外部HTTP/subprocessのみfixture化。ローカル通信以外をOS側で禁止。
  テスト候補を稼働中のcanonical report/観測storeへ書き込んでいない。

全体テスト・反映・保全比較の結果は[CONSOLE_ALERT_VALIDATION.json](CONSOLE_ALERT_VALIDATION.json)。
非公開の変更前source・hash・テストログ・API/DOM/画面証拠は`.run/restriction-console-alert-20261028/`。
画面証拠は**隔離fixture**であり、実際の再検証候補や経済的有効性の証拠ではない。

## 復元

今回の表示追加commitだけをrevertし、console/manage.sh restartでWebサービスを再読込する。
このホストのツール実行からはbackground子プロセスが継続しない場合があるため、既存launchdの
`com.hirotomookawasaki.stock_swing.console.watchdog` を確認してkickstartし、別呼出しで
status/health/APIを検証する。起動メッセージだけを復元成功と扱わない。
購入停止設定・観測store・過去の観測実装は巻き戻さない。他のdirty差分を触らない。
