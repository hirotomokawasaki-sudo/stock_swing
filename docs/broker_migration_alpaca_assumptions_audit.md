# A1: Alpaca 前提コード棚卸し（IBKR移行 Track A）

**作成日**: 2026-08-19
**位置づけ**: `docs/broker_migration_ibkr_plan.md` Track A-1。
IBKR用実装（Track B）に入る前に、現行コードが「Alpacaであること」を暗黙に
仮定している箇所を洗い出す。ここではコード変更は行わない（調査のみ）。

**凡例**:
- 🔴 HIGH: IBKR切替時に確実に壊れる／作り直しが必要
- 🟡 MED: 動作はするが前提が違う・検証が必要
- 🟢 LOW: コメント・ドキュメントのみ、または既に抽象化済み

---

## 1. 接続・認証層 🔴

| ファイル | 内容 | IBKRでの扱い |
|---|---|---|
| `src/stock_swing/sources/broker_client.py` | `base_url_paper = "https://paper-api.alpaca.markets"` / `base_url_live` がハードコード。認証ヘッダが `APCA-API-KEY-ID` / `APCA-API-SECRET-KEY` 固定 | IBKRはAPIキー方式ではなくTWS/IB Gatewayへのソケット接続（`ib_insync`/`ib_async`）かClient Portal Web APIのセッショントークン。**この層は丸ごと別実装が必要**（Track B A2/A3の対象） |
| `src/stock_swing/sources/broker_client.py:_fetch_market_data_endpoint` | `data.alpaca.markets` を別ホストとして直書き（bars/quotes専用） | IBKRは市場データもGateway/APIセッション経由。別ホスト概念自体が存在しない |
| `config/sources/broker.yaml` | `description: "Alpaca broker API — required for order reconciliation"` | ドキュメントのみだが、"broker=Alpaca"という命名の暗黙前提を示す一次資料 |
| `.env.example` | `BROKER_API_KEY` / `BROKER_API_SECRET` / `BROKER_BASE_URL` | IBKR用にはAPIキー/シークレット概念がない（Gatewayホスト:ポート + クライアントID等に変わる） |

## 2. runtime mode / config 🔴

| ファイル | 内容 | IBKRでの扱い |
|---|---|---|
| `config/runtime/current_mode.yaml` (コメント) | 「`ALPACA_MODE` must equal 'paper' at startup」「All order submissions go to **Alpaca** paper account only」と明記 | 記述自体がAlpaca名指し。IBKR移行時は `environment_id`（`alpaca_paper`/`ibkr_paper`/`ibkr_live`）ベースの表現に置き換える必要（A3で設計） |
| `src/stock_swing/core/runtime.py` | `ALLOWED_RUNTIME_MODES = {"research", "paper", "live_guarded", "live"}` | ブローカー種別を持たない4段階のみ。ブローカー軸を直交する形で追加する必要（`environment_id` 併用が現実的、`RuntimeMode` 自体の変更は不要） |

## 3. 実行層（PaperExecutor / Reconciler） 🟢 (I/Fは狭い、差し替え可能)

| ファイル | 内容 | 評価 |
|---|---|---|
| `src/stock_swing/execution/paper_executor.py` | `broker_client.fetch_account/fetch_positions/submit_order` のみ呼ぶ。Alpaca固有フィールド名への直接依存は `acct.get("equity")` / `pos.get("qty")` / `pos.get("current_price", pos.get("avg_entry_price"))` 程度 | 🟡 フィールド名はAlpacaのレスポンス形状に依存しているが、`BrokerClientProtocol`実装側でAlpaca形式に正規化して返せば呼び出し側は無変更で済む設計にできる |
| `src/stock_swing/execution/reconciler.py:_normalize_broker_status` | `status_map` が Alpaca 固有ステータス名（`new`/`accepted`/`pending_new`/`partially_filled`等）をハードコード | 🔴 IBKR注文ステータス（`PendingSubmit`/`PreSubmitted`/`Submitted`/`Filled`/`Cancelled`等）は名称体系が異なる。IBKR用の別マッピングが必要 |
| `src/stock_swing/execution/reconciler.py:_to_number` | 「Alpaca/paper APIs often serialize qty fields as strings」という前提でstr→numberの防御的変換 | 🟢 IBKRでも同種の防御は無害に効くため流用可 |
| `src/stock_swing/execution/live_guarded_executor.py` / `production_executor.py` | `broker_client: BrokerClient` を型ヒントで直接参照（ダックタイピングだが型注釈がAlpaca実装に固定） | 🟡 Protocol化すればここも型注釈を差し替えるだけで済む |

## 4. Fill / Ledger 層 🔴

| ファイル | 内容 | IBKRでの扱い |
|---|---|---|
| `src/stock_swing/tracking/fill_ledger.py:_fill_key` | 優先順位「1. `fill.id`（**Alpaca execution fill id**）」とdocstringに明記。`fill.get("id") or fill.get("fill_id")` | 🔴 IBKRは `execId` 単位で複数exec配信 + 別建てcommission report。**exactly-once消費ロジックをexecId前提に作り直す必要**（Track B必須項目） |
| `src/stock_swing/tracking/fill_ledger.py:_build_record` | `fill.get("filled_avg_price")` 等、Alpaca注文レスポンスのフィールド名前提 | 🟡 IBKR用アダプタ側でAlpaca互換フィールド名に正規化するか、fill_ledger側を汎用化するか要検討 |
| `src/stock_swing/tracking/pnl_tracker.py` | `broker_account_id`, `tracking_label=f"alpaca_account_epoch_{...}"` のようにAlpacaアカウントエポックという概念がラベルに焼き込まれている | 🟡 IBKR移行時に新たな `environment_id` ベースのラベル体系に置き換える設計が必要（A3） |
| `data/tracking/pnl_state.json` | `broker_account_id: "PA3SEQKOZ91C"`（Alpaca paper口座番号形式）が単一フィールド | 🔴 IBKR口座番号(`DU`prefixのpaper等)に置き換わるだけでなく、**Alpaca/IBKR混在期間の台帳分離設計がないと事故る**（シャドー運用期間に必須） |

## 5. Guardrail / Reconciliation 前提 🟡

| ファイル | 内容 | 評価 |
|---|---|---|
| `src/stock_swing/guardrails/postrun_mismatch.py` | 「broker position qty only reflects the fill once **Alpaca's** ... (several seconds)」という遅延特性の実測に基づくlag_excusedロジック | 🟡 IBKRの約定→ポジション反映レイテンシは未知数。**同じ遅延パターンが起きるかは検証が必要**（Track B シャドー期間の重要確認項目） |
| `src/stock_swing/guardrails/day_start_snapshot.py` | ブローカー名への直接依存なし（equity/unrealized_pnlを汎用的に受け取る設計） | 🟢 このモジュール自体はブローカー非依存。ただし呼び出し元 (`paper_demo.py`) の `broker.fetch_account()` がAlpaca実装依存 |
| `src/stock_swing/cli/paper_demo.py:1092` 周辺 | `get_prev_unrealized_for_guardrail` 呼び出し自体は汎用だが、equity取得元は`broker.fetch_account()`（Alpaca実装） | 🟢 Protocol化されればそのまま動く |

## 6. データ取得層（bars/quotes） 🟡

| ファイル | 内容 | 評価 |
|---|---|---|
| `src/stock_swing/sources/hybrid_data_fetcher.py` | 「Alpaca fetch_bars() stopped updating ALL symbols on 2026-04-22」という既知バグを前提にMassive優先・Yahoo fallback・Broker最終手段という設計 | 🟢 Massive/Yahoo優先の設計自体はブローカー非依存で継続可能。Broker最終手段パスのみIBKR用に差し替えが必要 |
| `src/stock_swing/normalization/broker_normalizer.py` | `bar.get("t")`, Alpacaのbarフォーマット（OHLCV JSON構造）前提でパース | 🔴 IBKRのhistorical dataレスポンス形式は異なる（`ib_insync`のBarDataオブジェクト等）。専用normalizerが必要 |
| `src/stock_swing/cli/collect_data.py:_make_broker_client / collect_broker / collect_broker_bars` | `BrokerClient`を直接import・生成 | 🟡 Protocol/ファクトリ経由に変えれば環境変数で切替可能 |

## 7. 運用スクリプト 🟡🟢

| ファイル | 内容 | 評価 |
|---|---|---|
| `scripts/sync_pnl_with_broker.py` | `fetch_alpaca_orders` / `fetch_alpaca_account` 関数名からURL直書きまで完全Alpaca専用 | 🟡 IBKR版が別途必要になるが、緊急時の手動復旧ツールのため優先度は低（Track B後半） |
| `scripts/rebuild_pnl_state_from_broker.py` | `tracking_label` に `alpaca_account_epoch_{baseline_date}` のフォールバック文字列 | 🟡 A3のenvironment_id設計に合わせて改修が必要 |
| `scripts/g1_investigate_mismatch.py`, `scripts/cleanup_alpaca_anomalies_20260511.py` 等 | 過去のAlpaca固有インシデント対応の使い捨てスクリプト | 🟢 IBKR移行に伴う改修不要（インシデント対応時のみ再利用される想定） |
| `scripts/secret_scan.py` | `"your-alpaca-api-key"` のようなプレースホルダー文字列をシークレットスキャンの許可リストに登録 | 🟢 IBKR用の同種プレースホルダーを追加するだけで済む軽微な対応 |

## 8. symbol_registry / 識別子設計 🔴（最重要・要設計）

| ファイル | 内容 | IBKRでの扱い |
|---|---|---|
| `config/reference/symbol_registry.yaml` | symbol文字列（`AAPL`, `ADBE`等）をキーにした asset_class/sector/benchmark 定義 | 🔴 IBKRは `conId` を正準識別子として扱う（同一symbolが複数取引所に上場する曖昧性を回避するため）。symbol文字列キーのままだと**取引所指定なしのconId解決が必要**になり、誤発注リスクの温床になりうる。Track BでconId↔symbolマッピング層の追加が必須 |
| `src/stock_swing/risk/position_sizing.py:SYMBOL_SECTORS` | symbol文字列ベースのセクター参照（`paper_executor.py`内で使用） | 🟡 symbol文字列運用を当面維持しつつ、conId解決層をIBKRアダプタ内に閉じ込める設計が現実的 |

---

## 9. 優先度まとめ（Track B 着手時の対応順序）

| 優先度 | 対象 | 理由 |
|---|---|---|
| 1 (必須・最初) | `BrokerClientProtocol` 定義＋IBKR実装（接続・認証層） | すべての土台。A2で先行着手中 |
| 2 | `fill_ledger.py` の execId 対応 | exactly-once保証が壊れると台帳が汚染される、過去のfill重複バグと同型リスク |
| 3 | `Reconciler._normalize_broker_status` のIBKR用ステータスマッピング追加 | reconciliation誤判定→circuit_breaker誤HALTの再発防止 |
| 4 | `environment_id` 対応（`pnl_state.json`・`tracking_label`・`broker_account_id`） | Alpaca/IBKR混在期間の台帳汚染防止（A3で設計） |
| 5 | conId↔symbol マッピング層 | 誤発注防止。ただし現状の単一取引所前提銘柄が多ければ緊急度は下がる可能性あり（Track Bで実データ確認） |
| 6 | `broker_normalizer.py` のbar/quoteパース | IBKR接続確定後、実データ形式を見てから実装（先に仕様だけ調べておくのは可） |
| 7 | `postrun_mismatch.py` の lag_excused ロジック再検証 | IBKRの約定反映レイテンシ実測後に調整（シャドー期間中に観測） |
| 8 | 運用スクリプト群（`sync_pnl_with_broker.py`等）のIBKR版 | 緊急時ツールのため優先度低、Track B後半で着手 |

---

## 10. まとめ

- **接続層・fill_ledger・reconciliation status mapping・symbol識別子**の4点が「作り直し必須」の🔴項目。
  これらはTrack Bで `BrokerClientProtocol` 実装と同時並行で着手する必要がある
- **PaperExecutor/day_start_snapshot/hybrid_data_fetcher（Massive/Yahoo部分）**は既に十分抽象化されており、
  Protocol化後はほぼ無改修で動く見込み（🟢）
- **postrun_mismatchのlag_excusedロジック**はAlpaca実測値に基づくため、IBKRで同じ遅延パターンが
  再現するとは限らない。シャドー運用期間中に必ず実測し、必要なら調整する（過去のG1-v2 race condition
  再発防止の教訓をそのまま活かす）
- 本棚卸しはコード変更を伴わない。次のステップ（A2）で `BrokerClientProtocol` を定義し、
  現行 `BrokerClient` をこれに適合させるリファクタ（挙動変更なし）を実施する

*作成: 2026-08-19*
