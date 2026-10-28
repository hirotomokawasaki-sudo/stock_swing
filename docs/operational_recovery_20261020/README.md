# 定期実行障害の復旧（2026-10-20）

## 範囲と事実

10/19 USセッションのpaper 4ジョブは、業務コマンドの起動前にモデルproviderの
DNSエラーで失敗した。10/20のnews canaryは旧モデル設定のまま成功しており、
DNS障害の継続やモデル名そのものの不具合を断定しない。

固定コマンドにLLM起動を必要としないよう、**既存OpenClawのnative command
payload**へ14ジョブを移行する。コア更新・独自scheduler導入ではない。
曜日・時刻・enabled・配送先・既存の売買フラグは維持する。

| 対応 | 内容 | 完了と見なさないもの |
|---|---|---|
| 起動経路 | news、価格補助、paper 4件、open照合、broker snapshot、日次/週次監査、benchmark、decile、quarantine、朝reportの14件 | payload更新だけでは各ジョブの本番成功を証明しない |
| 実行監視 | `scripts/cron/run_gateway_command.py`で完全ログ、終了コード、paperのJSON summaryを保存。失敗・summary欠損を成功扱いせず、自動再試行しない | process成功は戦略黒字の意味ではない |
| 観測監視 | `scripts/check_operational_recovery.py`で期待NYSEセッション/ET時刻とconsole・CB・RiskOffを照合。結果は別reportへ保存 | 診断/dry-run/再生でcanonical evidenceを更新しない |
| 収益性 | 既存 `check_economic_viability` を再利用 | PF条件を緩めない、コホートを差し替えない |
| R14 | [実装前契約・反証テスト・未登録項目](R14_READINESS.md)へ分解 | 設計文書の完成をhard capやsub-ledgerの実装完了と呼ばない |

## 安全境界

- runtimeはpaper、既存Circuit Breakerはhaltedのまま。売却・risk exit経路は維持。
- Economic Risk-Offはshadowのまま。実観測のないstate/historyは生成・遡及補完しない。
- 10/19の欠落runは欠落として残す。今のデータをその日の実観測へ付け替えない。
- 14コマンドの売買env/引数は元のもの。paperに加えるのは`--cron-summary-json`だけ。
- `scripts/cron/run_paper_demo.sh`は追加のPF閾値を持つため流用していない。
- broker/tracker実照合は不一致0。実ネットワークpaper canaryは隔離rootで実施し、
  submit/cancelを禁止、送信0件、live台帳・HALT・consoleのhash不変を確認した。
- R19は10銘柄の現在取得とshadow追記に成功したが、以前の失敗時点の詳細ログがなく、
  恒久的な価格provider障害の解消までは主張しない。

## 検証と再現

```bash
venv/bin/python -m pytest --tb=short -q
venv/bin/python scripts/check_operational_recovery.py --save
venv/bin/python scripts/check_operational_recovery.py --save --require-scheduled
```

最後のコマンドは正規runの新しい証跡が揃うまでexit 1になる。
consoleの非dry-run provenance、CBの最新評価、RiskOffの当日有効観測を確認する。
provenanceフラグだけでschedulerの起動元は証明できないため、レビューでは必ず
Gatewayの該当run ID・終了状態も突き合わせる。latched HALTは鮮度の合否と独立。

`ready_session_candidates`は有効な履歴から再構成可能な連続5営業日窓の**候補数**。
過去に実際にready判定が記録されたこと、状態遷移の独立再計算、資金移動照合、
機会損失、ユーザー承認を代替しない。14営業日分あれば最大10窓を作れるが、
単に10営業日経過しただけでは10 ready観測にならない。

初回全回帰ではlive cronの状態に依存する既存all-green unit fixtureだけが失敗した。
その1テストの外部CLI I/Oをfixture化し、実際のparser/health評価は維持した。
productionのGo/No-Go条件は変更していない。最終結果と適用証跡は下記へ追記する。

## 証跡・ロールバック

変更前の33ジョブ全payloadと対象state/configをowner-only backupへ保存:

`.run/ops-recovery-20261020T110430/automations.before.json`

適用/検証のJSON、全回帰ログ、隔離canaryの結果も同じディレクトリへ保存する。
credentialや口座IDを含み得るため、このバックアップや生成データはcommitしない。

戻す場合は変更した14 job IDについて、backupの同じIDの`payload`だけを
`automations(action="update", jobId=..., job={"payload": original_payload})`で戻す。
3つの既存レビューは元のpayloadへ戻し、今回明示化した2件の配送先だけも元へ戻す。
今後のschedule/配送先の変更を上書きしない。追加した単発検証だけを削除する。
台帳/state全体の巻き戻し、HALT解除、失敗runの履歴改変は不要であり実施しない。

## 適用結果

- 全回帰 **2431 passed / 2 skipped / 1 warning**（155.93秒）。warningは既存の
  TestSourceClient collection warning。今回のテスト追加23件。
- 14/14ジョブについてpayload argv・schedule・enabled・配送先の一致を確認した。
  旧失敗履歴は消去していないため、未実行ジョブのlastRunStatusはerrorのまま残る。
- Gateway native news canaryは11:18 JSTに356msで正常終了し、時間外guardで
  collectionをskip。起動経路の証明であり市場中の収集成功の証明ではない。
- Gateway native benchmark canaryは同11:18 JSTに成功。SMH/SOXX/QQQ/SPY/SOXQ
  全5銘柄63本ずつ、最新2026-10-19まで取得した。
- 今夜 **22:50 JST** のLLM非依存証跡チェックを登録・get確認済み:
  `649dfccc-3aa1-42b6-a3e4-de7d9ece6f44`。正常成功時のみ自動削除。
  **23:00 JST** の既存復帰レビューも、run ID照合・初回観測・HALT維持条件を追記。
- 11/2 RiskOffレビューはready候補と実ready観測を区別し、11/17 R14レビューは
  設計・実装・観測条件未達なら継続コスト評価のみ、と既存payloadへ追記した。
  3件とも既存時刻は変更せず、配送先を確認・明示した。
- OpenClaw config validationはvalid、Telegram接続probeはok。host CPUに関する
  event-loop degraded表示が一度あり、これを全ホスト無警告の証明とは扱わない。
  この表示時もGateway native実行とchannel probeは成功している。
- paper_demoコード、runtime/guardrail config、CB、台帳、canonical consoleが
  対応前backupとbyte一致。RiskOff forward stateは未生成のまま。

## 残る完了条件

1. 今夜10/20 22:25/22:35 JSTの正規paper runをGateway履歴とstateで確認する。
2. RiskOffは初回観測からwarm-up。11/2レビューは10連続ready観測が未達なら延期し、
   日数を理由にenforceへ昇格しない。
3. 収益性は今回再計算でもn=108、PF=0.653、期待値-$545.27でNO-GO。
   運用復旧がこの損益を改善したという主張はしない。
4. R14の設計条件・実装・前向き検証は別途必要。今回paper A/Bを開始しない。
