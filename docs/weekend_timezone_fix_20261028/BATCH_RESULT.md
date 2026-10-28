# 2026-10-28: 米国金曜を週末と誤判定する不具合の修正

Status: PARTIAL — コード反映・全体試験PASS。実定期実行の確認のみ未完了。

## 原因と最小修正

10/24 01:00 / 04:55 JST（米国10/23金曜12:00 / 15:55 ET）に、
`paper_demo` が `datetime.now()` のタイムゾーンなし日本時刻を渡していた。
共通市場判定はこの入力をETへ変換せず、土曜日としてBUY候補を除外した。
以前の7月修正はaware入力だけを変換しており、naive入力経路が残っていた。

既存の標準ライブラリ `datetime` / `zoneinfo` と共通市場判定を再利用する。
新しいカレンダー、外部サービス、依存パッケージは追加しない。

| 変更ファイル | 内容 |
| --- | --- |
| `src/stock_swing/cli/paper_demo.py` | 市場表示・BUY/SELLフィルターへの現在時刻をaware UTCにする。 |
| `src/stock_swing/utils/market_calendar.py` | `is_market_open` / `is_regular_market_hours` のnaive入力を既存JST時刻契約として明示的にlocalizeし、ET日付へ変換。ホストのTZに依存しない。 |
| `tests/unit/test_market_calendar_naive_jst_regression.py` | 60回帰ケース。実インシデント・夏冬時間・開始終了境界・週末・祝日・同一瞬間の4表現・BUY/SELL伝播を確認。 |
| `tests/unit/test_market_calendar_good_friday.py` | 既存fixtureの「祝日の正午」をaware ETで指定。naive JST正午はET前日なので、曖昧な時刻指定だけを修正。祝日停止のassertは維持。 |

`is_us_holiday` の日付関数、`previous_trading_close_utc` のnaive-as-ET契約、
`market_guard.is_us_trading_day`、`weekend_gap_guard.to_us_eastern` の契約は変更しない。
これらは個別の入力契約を持つため、全naive日時の一括置換はしていない。

## 実データとテスト

- 修正前のソース（基準commit `2eb041e`）では、新規60ケースのうち **10失敗 / 50合格**。
  実際の曜日・判定・フィルター出力の不一致で失敗した。
- 修正後の関連テスト **152合格**（ホストTZ=UTC）。新規60ケースは
  TZ=America/Los_Angelesでもすべて合格。JSTの実インシデント時刻でも判定を再確認。
- 10/24の両実行から保存済みdecision JSONを各4件コピーし、実際の共通市場判定と
  BUYフィルターへ通した。各実行の誤ったカレンダー除外は **4→0**。
  PF・配分・資金・risk等の他ゲートは迂回も再実行もしておらず、購入成立を意味しない。
- これは限定的な履歴入力canaryであり、完全CLI・外部broker・実定期実行ではない。
  通信・稼働data/config/reports/docsへの書き込みをOSで禁止し、発注0・取消0・通知0。
- 最終全体試験は **2,554合格 / 2skip**。外部・localhost通信を禁止した
  `python -m pytest --tb=short -q -k 'not test_remote_readonly_rejects_query_token_and_accepts_header'`
  の2,553合格 / 2skipと、localhost認証試験1件の合格を非重複で合算。
  後者も外部通信・稼働保護ディレクトリへの書き込みは禁止。
  既存のcollection warning1件あり。最初のlocalhost許可付き全体試験は外部I/Oの
  retry待ちで中断し、最終合格数に含めていない（製品のretry挙動は変更なし）。
  詳細は `VALIDATION.json` と非公開ログに保持する。

### 必須テスト基準チェック

- [x] 正常系・境界値・acceptance：米国金曜/JST土曜、夏冬、09:29/09:30、16:00、実週末、祝日。
- [x] 新規public API / ファイル欠損・破損fallback：該当なし。public API追加・ファイル読込変更なし。
- [x] 状態遷移：該当なし。breaker/永続状態の遷移は変更なし。
- [x] レイヤー伝播：実BUY/SELLフィルターで市場時刻判定を確認。新しいconfig/summary値なし。
- [x] バグ再現：docstringに2026-10-24インシデントと修正前commitを記載し、旧コードで失敗を確認。
- [x] フェイルクローズ維持：時間外BUY停止、非破局的SELL繰り延べ、緊急SELL許可、祝日・週末停止。
- [x] 全体試験：上記の分離実行で全2,556ケースを確認（2,554合格・2skip）。

## 反映・実運用確認

既存4売買ジョブは当該checkoutのvenvから毎回新しいPythonプロセスを起動し、
この変更済みソースを読み込む。サービス再起動・再インストール・手動売買は不要。
次回の通常ジョブからコードが使われるが、**実定期実行の確認は未完了**。

読み取り専用の確認を **10/31 07:10 JST** に予約・再取得確認済み。
ID: `f2e3c444-f106-4b01-bd71-3a100fce8222`。
米国10/30金曜のmidday / near-close（JST10/31 01:00 / 04:55）の
receipt・正常終了・非dry・新しいログ・市場表示・設定不変を照合し、この会話へ返す。
各ジョブの最大7200秒に15分を加えた完了猶予の後に確認する。
候補がなくBUYフィルターまで通らなかった場合は、起動/市場表示の確認と区別する。
一回限りの確認1件だけを追加し、既存35ジョブの設定は不変。

## 変更しないもの・残条件

- Paperのまま。PF購入フィルター、クールダウン、EXIT_ONLY、停止閾値・breaker状態、配分は変更しない。
- 原台帳・約定・イベント・canonicalレポート・config・既存ジョブを上書きしない。
- 手動発注・取消・broker API・リセット・停止解除・過去注文の追いかけ実行をしない。
- この修正は購入を保証しない。IBM/NOW等のPF制限は引き続き独立して適用される。
- 経済性・戦略採用・実弾移行の判定は含めない。

## 証跡・rollback

非公開証跡: `.run/weekend-timezone-fix-20261028/`（ディレクトリmode700）。
旧ソース、ジョブ定義前後、稼働保護対象hash、before/afterテストログ、コピー上の
`canary.json`、確認ジョブreadbackを保持する。公開review用にはコードとテストの差分のみを含める。

rollbackはこの修正の2ソース・2テストだけを差し戻す。既存dirty差分や稼働状態は戻さない。
将来必要な場合は、記録した変更commitのrevertか `before/` の所有ファイルを使い、
定期実行中でないことと最新差分を確認する。誤週末判定は再発するため、設定緩和で代替しない。
