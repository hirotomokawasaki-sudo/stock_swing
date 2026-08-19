# ブローカー移行計画: Alpaca → Interactive Brokers (IBKR)

**作成日**: 2026-08-19
**位置づけ**: `docs/console_improvement_tasks.md` の R0-R8/R9 ロードマップ（戦略パフォーマンス改善）
とは **完全に独立した別トラック**。9/15 のリアルトレード Go/No-Go 判定はシステム/戦略の
パフォーマンス評価であり、本ブローカー移行の可否とは無関係（ユーザー指示・2026-08-19）。

**移行理由**: 業務上の理由（会社都合）。移行自体は **マスト**（是非の議論対象ではない）。

**現状の未確定事項**（2026-08-19 時点）:
- IBKR 口座開設: 申請中。開設完了時期は**会社都合のため未定**
- 接続方式: **未定**（TWS/IB Gateway ソケットAPI経由 か、Client Portal Web API か）
- 移行開始日: **未定**

→ 本計画は絶対日付ではなく **D0（移行開始日、口座開設完了かつ接続方式確定の日）からの相対日程**
で組む。D0 が確定した時点で本ファイルの相対日程を実カレンダーに落とし込む。

---

## 0. 全体方針

1. **Alpaca Paper → IBKR Paper → IBKR Live** の順で段階移行する（ユーザー提案どおり、順序は妥当）
2. **IBKR Paper と IBKR Live の 2 口座運用を継続する**（Alpaca の paper/live 分離と同じ思想。詳細は
   セクション 6 参照）
3. **D0 より前に着手できる作業（Track A）と、D0 依存の作業（Track B）を分離する**。会社都合で D0 が
   ずれても Track A は無駄にならないようにする
4. **9/15 の Go/No-Go・R0-R9 の戦略改善作業とは変数を混ぜない**。IBKR 移行中に生じる問題（接続断・
   価格ズレ・約定モデルの違い等）を戦略パフォーマンスの問題と誤診断しないよう、評価対象を分離する
5. Alpaca 口座は移行完了後も一定期間ロールバック先として維持する（詳細セクション 7）

---

## 1. なぜ「軽い切替」ではないか（技術的背景）

- `src/stock_swing/sources/broker_client.py` の `BrokerClient` は Alpaca REST 専用実装
  （`APCA-API-KEY-ID` ヘッダ、`paper-api.alpaca.markets` / `data.alpaca.markets` の URL 構造が
  ハードコード）
- `config/runtime/current_mode.yaml` の `mode: paper` の説明コメントに
  「**ALPACA_MODE must equal 'paper'**」と Alpaca 前提が明記されている
- 過去のインシデント（MEMORY.md）は軒並み「ブローカー API の想定外の挙動」由来:
  - Alpaca positions API の stale price（CHPX +53%乖離など、2026-05-19）
  - `broker.get_account()` メソッド不存在 → equity=null → BUY 停止 2 日 11 時間（2026-07-31）
  - Alpaca paper trading の equity 計算バグ（$78,469 乖離、2026-05-11）
  - fill_ledger の exactly-once 設計は Alpaca の `fill_id` 前提
  → **ブローカー切替はこの種のバグの再発を最も誘発しやすいイベント**であり、
    「様子見期間を必ず置く」という本プロジェクトの文化的方針（07-09 hard-halt キャリブレーション、
    sector_shock shadow→paper_ab→active の段階昇格等）を踏襲すべき
- 救いは `PaperExecutor` / `Reconciler` が `broker_client` に対して呼ぶメソッドが
  `fetch_account / fetch_positions / fetch_orders / submit_order / get_order / cancel_order /
  fetch_bars / fetch_latest_quote` という**狭いダックタイピング I/F** に閉じている点。
  ここを正式な Protocol として固定化すれば、IBKR 用実装を差し替え可能にできる

## 2. IBKR 固有の注意点（Alpaca との差分）

| 項目 | Alpaca | IBKR | 影響 |
|---|---|---|---|
| 接続方式 | ステートレス REST + API キー | TWS/IB Gateway常駐（ソケットAPI）or Client Portal Web API（セッショントークン） | 常駐プロセスの運用（日次再起動・再認証）が新規に必要 |
| 識別子 | symbol 文字列 | conId 中心（symbol は補助） | `symbol_registry.yaml` / `pnl_state` / quarantine 等の symbol キー設計に影響 |
| 市場データ | 無料 IEX フィード込み | 取引所ごとの有料サブスクリプション（paper でも同様のことが多い） | paper/live でデータ鮮度が変わるリスク（過去に何度も踏んだ地雷と同型） |
| 約定モデル | order status + fill | execId 単位の複数 exec report + 別建て commission report | `fill_ledger.py` の exactly-once 設計を作り直す必要 |
| Paper 口座 | 独立して即座に使える | 既存/申請中の live 口座に紐づく形で発行されることが多い | 口座開設のリードタイムがそのまま発生（現状「会社都合で未定」の一因） |

## 3. インターフェース抽象化方針

現行 `BrokerClient` の呼び出し契約を `Protocol` として明文化し、`AlpacaBrokerClient` /
`IBKRBrokerClient` の両方がこれを満たす形にする（呼び出し側 `PaperExecutor` / `Reconciler` /
`paper_demo.py` は無変更で差し替え可能にするのがゴール）。

```
BrokerClientProtocol:
  fetch_account() -> RawEnvelope
  fetch_positions() -> RawEnvelope
  fetch_position(symbol_or_id) -> RawEnvelope
  fetch_orders(status, limit) -> RawEnvelope
  fetch_order(order_id) -> RawEnvelope
  get_order(order_id) -> RawEnvelope
  submit_order(symbol, side, order_type, qty, time_in_force, limit_price) -> dict
  cancel_order(order_id) -> dict
  fetch_bars(symbol, timeframe, start, end, limit) -> RawEnvelope
  fetch_latest_quote(symbol) -> RawEnvelope
```

加えて、環境（broker × paper/live）を明示するキーを state 全体に通す設計変更が必要
（現状 `pnl_state.json` 等は単一ファイル前提のため、IBKR paper / IBKR live / Alpaca paper が
将来混在しても破綻しないよう `environment_id`（例: `alpaca_paper` / `ibkr_paper` / `ibkr_live`）
を台帳スキーマに持たせる）。

---

## 4. スケジュール（D0 = 移行開始日、口座開設完了 かつ 接続方式確定の日）

### Track A: D0 非依存（今すぐ着手可能、会社都合の遅延に影響されない） — ✅ 完了（2026-08-19）

| # | 作業 | 状態 | 成果物 |
|---|---|---|---|
| A1 | Alpaca 前提コードの棚卸し | ✅ 完了 | `docs/broker_migration_alpaca_assumptions_audit.md` — 接続層/fill_ledger/reconciliation status mapping/symbol識別子(conId)の4点を🔴最優先項目として特定 |
| A2 | `BrokerClientProtocol` 定義 + 既存実装の適合 | ✅ 完了 | `src/stock_swing/sources/broker_client_protocol.py` 新規作成(`@runtime_checkable Protocol`)。`PaperExecutor`/`Reconciler`/`LiveGuardedExecutor`/`ProductionExecutor`/`HybridDataFetcher` の型注釈を `BrokerClientProtocol` に変更(挙動変更なし)。テスト23件追加、フルスイート1904 passed/2 skipped(regressionなし) |
| A3 | state/ledger の `environment_id` 対応設計 | ✅ 完了 | `docs/broker_migration_environment_id_design.md` — pnl_state.json/fill_ledger/day_start_snapshotへの`environment_id`(alpaca_paper/ibkr_paper/ibkr_live)導入設計、マイグレーション手順を文書化(実装はTrack B) |
| A4 | IBKR接続方式の比較資料 | ✅ 完了 | `docs/broker_migration_ibkr_connection_method_comparison.md` — TWS/IB Gateway vs Client Portal Web APIの比較(暫定推奨: CPAPI、現行httpxベース実装との親和性)。**web検索未実施のため、決定前にIBKR公式ドキュメントでの裏取り必須**と明記 |
| A5 | 日次運用負荷の見積り | ✅ 完了 | `docs/broker_migration_ibkr_operational_load_estimate.md` — Gateway常駐化・2FA自動化・Paper/Live 2プロセス運用の負荷を見積り。2FA自動化可否がプロジェクト最大のリスク要因と結論 |

Track A は D0 の遅延と無関係に完了済み。IBKR 用の実コード(IBKRBrokerClient 本体)は
接続方式が未定のため Track B 側(D0 以降)に置く。

### Track B: D0 依存（口座開設完了 かつ 接続方式確定後に開始）

```
D0        : 移行キックオフ（口座開設完了 + 接続方式確定）
D0+1週     : IBKR Paper 接続スパイク（隔離環境、paper_demo 本体には未接続）
             - 接続確立・認証フロー確認・test market/limit注文・positions/account取得
             - データフィード遅延・品質の確認（有料サブスク要否の実地確認）
D0+2〜3週  : IBKRBrokerClient 実装（Protocol準拠）+ 単体テスト
             - fill_ledger の exactly-once を execId ベースに作り直し
             - conId <-> symbol マッピング層の実装
D0+3〜6週  : シャドー運用期間（IBKR Paper を Alpaca Paper と並走、意思決定ロジックは共通・
             発注のみ両ブローカーに送る）
             - fill価格・執行タイミング・corporate action処理の差分を記録
             - 9/15 Go/No-Go指標（PF/WR/attribution/ledger）は Alpaca 側データのまま汚染しない
             - IBKR側は専用の `environment_id=ibkr_paper` 台帳に隔離記録
D0+6週     : IBKR Paper 昇格判定（ledger_quality_gate / broker_tracker_mismatch=0 / fill_ledger
             exactly-once 検証 / day_start_equity取得の安定性など、既存 go_no_go 方式を踏襲した
             専用ゲートを新設して判定）
D0+6週以降 : 昇格後、IBKR Paper を主運用に切替。Alpaca Paper は一定期間ロールバック用に並走維持
D0+X       : IBKR Live 口座 開設・確認（会社都合の口座開設完了時期に依存、Track Bのこの時点で
             既に完了している前提だが、Live取引許可が別途必要な場合はここで確認）
D0+X+2週   : IBKR Live Go/No-Go（既存 09-15 パターンを踏襲: 段階サイズ、初回は縮小サイズで開始）
D0+X+2週〜 : IBKR Live 稼働開始（初回サイズ縮小、既存の "50%サイズ→段階拡大" ロードマップ
             パターンを再利用）
```

> 週数は目安。会社都合で D0 自体が動く前提のため、D0+N 表記のまま `docs/daily_logs/` に
> 進捗を記録し、D0 確定時点でカレンダー日付に変換する。

---

## 5. 評価指標の分離（9/15 Go/No-Go との混同防止）

| 指標カテゴリ | 責任範囲 | 参照ドキュメント |
|---|---|---|
| 戦略パフォーマンス（PF/WR/attribution等） | R0-R9 ロードマップ | `docs/console_improvement_tasks.md` |
| ブローカー統合健全性（接続安定性・約定精度・reconciliation整合性） | 本ドキュメント | `docs/broker_migration_ibkr_plan.md`（本ファイル） |

IBKR移行期間中に発生した問題（接続断、価格乖離、fill遅延等）は**戦略のPF/WRに混ぜて評価しない**。
専用の `environment_id` 付き台帳で隔離し、ブローカー統合固有の健全性メトリクスとして別集計する。

---

## 6. 2環境運用（IBKR Paper + IBKR Live）の設計

- **賛成**: 既存の `runtime_mode`（research/paper/live_guarded/live の4段階）設計思想と一致。
  新機能・戦略変更を必ず paper で先に検証してから live に反映する既存パターン（Plan B/C/D/E の
  shadow→paper_ab→active 昇格と同型）をブローカーレベルでも維持できる
- **運用コスト増**:
  - IB Gateway/TWS プロセスを Paper 用と Live 用で **2つ** 常駐させる必要（同一Gatewayでの
    paper/live同時ログインは不可）。それぞれ日次再起動・2FA対応が必要
  → cron での自動再起動（IBC等のヘッドレスログインツール）が事実上必須
  - state/ledger を環境ごとに分離する必要（セクション3の `environment_id` 対応）
  - リアルタイムデータ購読コストが環境ごとに発生しうる
- **提案**: `live_guarded` は別アカウントを新設せず、IBKR Live アカウント内でリスク制限を
  厳しくした状態（既存の「初回50%サイズ」と同じ考え方）として扱う。**アカウントとしては
  Paper/Live の2つに留める**のが運用負荷的に現実的

---

## 7. Alpaca のロールバック維持方針

- IBKR Paper 昇格後も、Alpaca Paper は一定期間（目安: D0+6週から更に2〜4週）並走維持し、
  IBKR側で未知の問題が出た場合に即座に切り戻せる状態を保つ
- Alpaca Live 移行は本計画の対象外（Alpaca Live 自体を使う予定がなければ、Paperロールバック
  期間終了後にAlpaca Paperも解約/放置で問題ない）
- ロールバック判断基準は既存 `pre_live_checklist_20260820.md` の「E. ロールバック手順」と
  同型のテンプレートをIBKR用に用意する（Track B 内、IBKR Paper昇格判定と同時に整備）

---

## 8. 未決事項（ユーザー判断待ち）

| # | 事項 | 現状 | ブロックする作業 |
|---|---|---|---|
| 1 | IBKR 接続方式（TWS/IB Gateway vs Client Portal Web API） | 未定 | Track B 全体（IBKRBrokerClient実装） |
| 2 | IBKR 口座開設完了時期 | 会社都合、申請中 | D0 起点そのもの |
| 3 | IBKR Live アカウント開設・取引許可の別途要否 | 未確認 | D0+X（Live Go/No-Go）のタイミング |
| 4 | Alpaca Paper/Liveを移行完了後どこまで維持するか | 未定（本ドキュメントはロールバック用に一定期間維持を仮定） | Track Bの終盤スケジュール |

---

## 9. 次のアクション

- [x] Track A（A1〜A5）完了（2026-08-19）
- [ ] 接続方式の最終決定（A4比較資料を参考に、IBKR公式ドキュメントでの裏取りを含む）
- [ ] D0 確定後、本ファイルの「D0+N」表記を実カレンダーに変換し、
      `docs/daily_logs/` に進捗記録を開始
- [ ] 接続方式が決まり次第、セクション4 Track B の詳細スケジュールを確定日程に更新

---

## 10. ステータストラッカー（本ファイルを見れば今の状態が分かるように常に最新化する）

| 項目 | 状態 | 最終更新 |
|---|---|---|
| Track A（A1〜A5） | ✅ 完了 | 2026-08-19 |
| 接続方式（TWS/IB Gateway vs CPAPI） | ⚪ 未決定 | — |
| IBKR口座開設（Paper） | ⚪ 申請中（会社都合で完了時期未定） | — |
| IBKR口座開設（Live） | ⚪ 未着手 | — |
| D0（移行開始日） | ⚪ 未確定 | — |
| Track B | ⚪ 未着手（D0待ち） | — |

> この表は状況変化（口座開設完了、接続方式確定、D0確定等）があるたびに
> **すぐに更新する**。ユーザーからの明示的な指示を待たず、進捗情報を見択した時点で
> 本ファイル + `docs/daily_logs/YYYY-MM-DD.md` へ記録を行うこと（ユーザー指示：
> 2026-08-19、「移行が決まったら速やかに対応できるようにログと計画は記録に残して」）。

## 11. D0 到達時の即時実行チェックリスト

D0（口座開設完了 かつ 接続方式確定）が判明した時点で、以下をその日のうちに実施する：

1. 本ファイルのセクション10ステータストラッカーを更新（D0日付を確定値として記録）
2. セクション4 Track B の「D0+N」表記を実カレンダー日付に変換（例: D0+1週 → 実日付）
3. `docs/daily_logs/YYYY-MM-DD.md`（D0当日）にキックオフログを作成
4. ユーザーに確認上、最初の実作業であるTrack B 「IBKR Paper 接続スパイク」の着手可否を確認
5. 以降はD0+N進捗を `docs/daily_logs/` に逐次記録し、セクション10ステータストラッカーを適宜更新

*作成: 2026-08-19*
