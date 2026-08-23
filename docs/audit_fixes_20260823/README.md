# 2026-08-23 監査対応: 修正パッチ集（未適用・レビュー用）

**作成経緯**: 2026-08-23 監査（`docs/console_improvement_tasks.md` R0-v2〜R11
ロードマップ + Go/No-Go 判定ロジックの実データ精査）で発見した6件の実バグに対する
修正コード。**ユーザー指示により、コードは作成するが本番への適用は別途行う**ため、
このディレクトリの `patches/*.patch` は現時点で `stock_swing` の作業ツリーには
適用されていない（`git diff` 形式で保存のみ）。

適用する場合:
```bash
cd ~/stock_swing
git apply docs/audit_fixes_20260823/patches/01_paper_demo_no_actionable_console_summary_and_equity_bridge.patch
git apply docs/audit_fixes_20260823/patches/02_collect_data_broker_bars_pagination.patch
git apply docs/audit_fixes_20260823/patches/03_pairwise_correlation_synthetic_filter_and_freshness.patch
git apply docs/audit_fixes_20260823/patches/04_check_go_no_go_freshness_cron_paper3day.patch
git apply docs/audit_fixes_20260823/patches/05_f8_expectancy_and_drawdown_fix.patch
git apply docs/audit_fixes_20260823/patches/06_test_check_go_no_go_update.patch
source venv/bin/activate && python -m pytest -q   # 全パッチ適用後 2065 passed / 2 skipped を確認済み
```
各パッチは独立して適用可能（01と04以外は互いに依存しない。04は03のexport
`check_data_freshness`に依存するため03を先に適用すること）。

---

## 01. paper_demo.py: 無シグナル/無アクション run が console_summary を更新しない

**発見**: `main()` の「no_signals」「no actionable decisions after exposure
preflight」の2箇所が即座に `return` していたため、その run では
`console_summary.emit()` / `record_daily_snapshot()` / reconciliation /
guardrail post-run 評価 / P6 join coverage report が**一切実行されない**。
`reports/console/latest_console_summary.json` は
`scripts/check_go_no_go.py` が**そのまま**読む唯一のデータソースであり、
実際に2026-08-21 04:50 JST の run を最後に3日近く更新が止まっていた
（08-22, 08-23 は decision ファイルが1件も生成されていない）。

**修正**: 両方の early-return を「フォールスルー」に変更。`decisions`/
`actionable` が空リストのまま後続のフィルタ・ループを通過しても副作用がない
ことを確認済み（空リストへの operations は no-op）。これにより無アクション
run でも console_summary / 日次スナップショット / reconciliation /
ガードレール評価が必ず実行される。

**影響範囲**: 挙動変更は「ログ・レポートが書かれるようになる」ことのみ。
発注ロジック・ポジションサイジング・ガードレール判定ロジック自体は無変更。

---

## 01（同ファイル）. equity_bridge の `quarantined_pnl=0.0` 固定値バグ

**発見**: `_build_equity_bridge()` が `quarantined_pnl=0.0` を固定していた。
コメントには「quarantined trades は data reconstruction errors であり実際の
broker fill ではない」とあったが、実データを確認したところ
`quarantined_trades` 101件全件が `broker_order_id` + `exit_broker_order_id`
を持つ**実際のbroker約定**だった（chronology/holding_days 不整合で台帳から
除外されただけ）。そのPnL（約-$156,476）は broker_equity には反映済みだが
tracker には一切反映されておらず、本来 `unexplained_diff` に現れるべき
$168,874 の差が、`tolerance_usd=100_000.0` という「常にパスするよう選ばれた
値」によって `within_tolerance: true` とマスクされていた。

**修正**:
- `quarantined_pnl` を `pnl_tracker.get_quarantined_trades()` の実合計に変更
- `tolerance_usd` を `config/runtime/current_mode.yaml` の
  `ledger_quality_gate.acceptance_criteria.broker_equity_bridge_tolerance_usd`
  から読み込み（そのYAMLが「唯一の許容差の正」であるべきなのに、実際には
  このコードとは無関係の$100,000が別途ハードコードされていた）。
  YAML値（現在$1）は歴史的ギャップを考えると非現実的に厳しいため、
  フォールバック/下限は$5,000（$100,000ではない）に設定。
- 修正後の実データ: `unexplained_diff` は $12,398 → **$168,874** に変化し
  `within_tolerance: false` に変わる。これは「悪化した」のではなく、
  **元々存在していた説明不能な差を隠さず可視化した**ことによる変化。

**次のアクション（実装とは別）**: この$168,874の差の内訳を運用者が精査し、
(a) quarantine された101件の再分類・再統合、または (b) 正当な許容差として
`broker_equity_bridge_tolerance_usd` を実態に合わせて明示的に引き上げる、
のいずれかを判断する必要がある。本パッチは判断材料を正しく見せるだけで、
その判断自体は行っていない。

---

## 02. collect_data.py: `collect_broker_bars()` のページネーション未処理バグ

**発見**: `client.fetch_bars(symbol, timeframe=timeframe, limit=5)` は
`start` を明示しないため `BrokerClient.fetch_bars()` 側のデフォルト
（`max(limit*3, 30)` = 30 暦日前）にフォールバックしていた。Alpaca v2 bars
エンドポイントは昇順（古い順）でbarを返し `limit` はハードなページサイズと
して働くため、「30日ウィンドウの先頭5本」は常に**そのウィンドウの最古の
約5営業日**になる。実際に `data/raw/broker/broker_*.json` の
`marketdata/bars` スナップショットを全件確認したところ、**収集日に関わらず
全て 2026-07-23〜2026-07-29 の同じ1週間**が返り続けており、レスポンスに
含まれる `next_page_token` は一度も使われていなかった。

このバグにより、`src/stock_swing/risk/pairwise_correlation.py` が前提と
していた「収集cronのたびに新しい日の1本が積み上がり、蓄積で長期系列が
再構成される」という設計は機能しておらず、pairwise correlation の
promotion gate 条件は**何ヶ月も同じ凍結された19営業日の窓**で計算され
続けていた。

**修正**: `start` を「`limit` 営業日相当をカバーする暦日数だけ遡った日時」
として明示的に渡すことで、単一の（ページネーション不要な）レスポンスが
`end`（デフォルトのnow）側で終わるようにした。`limit` 自体も余裕を持たせて
`limit+5` に拡大（休日等での見積もり誤差を吸収するため）。

---

## 03. pairwise_correlation.py: synthetic/不正タイムスタンプの混入 + 鮮度検知欠如

**発見1**: `build_daily_closes_from_raw_bars()` が `str(bar["t"])[:10]` で
日付を抽出していたが、2026-04-21 の一部スナップショットは `"t"` が
Unix epoch秒の生の整数（例: `"1776406508"`）であり、これも無条件に
「10文字の日付らしき文字列」として `{date: close}` 辞書に混入していた。
`is_synthetic` フラグが立っているレコードでもあった。

**修正**: `is_synthetic=true` のスナップショットを明示的にスキップし、
かつ抽出した10文字が実際に `YYYY-MM-DD` 形式（ハイフン位置 + 数字のみ）
であることを検証するよう変更。

**発見2**: 02番の修正前は全銘柄のデータが常に同じ古い週に凍結していたが、
それを検知する仕組みが一切なかった（"available"はデータ点数だけで判定
しており、鮮度は無関係）。

**修正**: `check_data_freshness()` を新規追加。全銘柄の最新bar日付の中で
最も新しいものが `max_staleness_days`（デフォルト5日）を超えて古い場合、
`summarize_high_correlation_pairs()` の `freshness` 引数経由で
`available=False` を返すようにした（`reason` に staleness 詳細を含む）。
`scripts/check_go_no_go.py`（04番のパッチ）から呼び出すよう配線済み。

---

## 04. check_go_no_go.py: 3つの独立した「実質形骸化」バグ

Required 条件7件のうち、実データで再検証した結果、以下3条件が
**実質的に恒久的にpassし続ける**設計になっていることが判明:

1. **`console_summary_freshness`（新規追加）**: これまで存在しなかった
   条件。`latest_console_summary.json` 自体の鮮度を一度もチェックして
   おらず、01番のバグにより凍結していても検知できなかった。
   `summary["run"]["timestamp"]` が30時間以内であることを要求する条件を
   新規追加（cronは最低4時間おきに走る前提のため、週末・市場休場日を
   考慮しても30時間は十分に保守的な閾値）。

2. **`cron_jobs_healthy`**: 従来は `health.get("status") == "OK"` を
   見ていたが、これは同じ `summary` 内に既にある `health.status` を
   そのまま再読するだけで、実質的に何も追加検証していなかった
   （cronジョブ個々の実行履歴は一切見ていない）。
   `console.adapters.system_adapter.SystemAdapter._check_cron_run_history()`
   （console自身の `/health` エンドポイントが使う同じ評価ロジック）を
   呼び出し、実際の有効cronジョブ全件の実行履歴パース結果で判定するよう
   変更。SystemAdapterが利用不可の場合のみ旧ロジックにフォールバック
   （fail-openにはしない）。

3. **`paper_3day_confirmation`**: 従来は
   `docs/go_no_go_report_20260731.md` という**単一の固定ファイル**を
   `"07-30 ok"` 等の固定文字列でgrepしていた。このファイルは07-31判定
   時点で書かれて以降更新されておらず、**一度trueになったら未来永劫
   true**という設計だった（日付が相対的でも動的でもない）。
   `data/tracking/pnl_state.json` の `daily_snapshots` を読み、
   直近7日間のローリングウィンドウ内に異なる日付が3件以上あるかを
   実データで判定するよう変更。

**テスト修正**: `tests/unit/test_check_go_no_go.py` の
`test_all_pass_when_real_mismatch_zero_despite_raw_nonzero` を、
新しい3条件（鮮度・cron履歴・paper_3日）が要求するfixtureを書き込むように
更新（旧テストは固定ファイルへの書き込みのみで新条件を満たせず失敗する
ため）。

---

## 05. f8_clean_records_analysis.py: expectancy 計算式のバグ + max_drawdown の分母誤り

**発見1（expectancy）**: `expected_value` の計算式が
`win_rate * avg_pnl + (1 - win_rate) * (net_pnl - win_rate * avg_pnl / win_rate)`
という、標準的な期待値定義のどれにも一致しない式になっていた。実データ
（252トレード、実際の平均PnL/トレード = -$81.64）に対しこの式は
**-$10,772.71** という、2桁以上乖離した値を返していた。

**修正**: 標準的な定義 `win_rate * avg_win - loss_rate * avg_loss` に置換
（これは代数的に `net_pnl / count` = `avg_pnl` と常に一致するべき値であり、
修正後は実際に一致することを確認済み: `expected_value == avg_pnl == -81.64`）。

**発見2（max_drawdown）**: `_max_drawdown()` が「累積実現PnLの高値」を
`peak`（初期値0.0）として使い、`(peak - running) / peak` でドローダウン率を
計算していた。この設計には2つの欠陥がある:
1. 累積PnLが一度もプラスに転じるまで `peak > 0` が成立せず、その間の
   実損失がドローダウンとして一切記録されない
   （最もドローダウンが重要な局面で欠測する）。
2. 累積PnLが小さくプラス（実データでは+$1,443.75）になった直後に
   分母として使われると、その後の通常規模の損失が「ほぼ100%の
   ドローダウン」という無意味な数字になる。

**修正**: `peak`/`running` の初期値を `baseline_equity`（デフォルト
$1,000,000、`pnl_state.json` の実値を使用）にすることで、実際のアカウント
残高を分母とした意味のあるドローダウン率に変更。修正後の実データ:
**11.58% → 9.28%**（より正確な値。数値自体は大きく変わらないが、算出根拠が
恣意的な累積PnLピークから実際の資本ベースに変わった点が重要）。

---

## テスト結果

上記6パッチを全て適用した状態でのフルスイート実行結果:
**2065 passed, 2 skipped**（regressionなし）。個別パッチのみの適用でも
各対応する既存テストファイルが全てPASSすることを確認済み
（`test_check_go_no_go*.py`, `test_pairwise_correlation.py`,
`test_promotion_gate.py`, `test_capture_promotion_gate_snapshot.py`,
`test_collect_data_*.py`, `test_broker_client*.py`,
`test_paper_demo_*.py`, `test_remediation_20260730.py`,
`test_guardrail_day_start.py`）。

## 適用時の注意

- 01番のequity_bridge修正は、適用直後の次回paper_demo runで
  `within_tolerance: false` が表示されるようになる。これは意図した挙動
  （隠れていた問題の可視化）だが、アラート設定がある場合は事前に運用者へ
  周知すること。
- 02番の適用直後の次回 `collect_broker_bars()` 実行から、
  `data/raw/broker/broker_*.json` の日付範囲が実際に最新化され始める。
  過去の凍結スナップショットは削除されないため、pairwise correlationの
  重複排除ロジック（既存実装）が引き続き正しく機能する。
- 04番のcron健全性チェックは `openclaw cron list --json` /
  `openclaw cron runs` をサブプロセスで呼ぶため、実行環境に `openclaw`
  CLIが必要（既存の `console/adapters/system_adapter.py` と同じ前提）。
