# A3: environment_id 対応 — state/ledger スキーマ設計

**作成日**: 2026-08-19
**位置づけ**: `docs/broker_migration_ibkr_plan.md` Track A-3。
**本ドキュメントは設計のみ。実装はTrack B（D0以降、シャドー運用開始前）で行う。**
現時点でコード変更は行わない（`pnl_state.json`等の実データを触らない）。

---

## 1. なぜ必要か

現状 `data/tracking/pnl_state.json` は「単一ブローカー・単一口座」を暗黙の前提にした
フラットなスキーマになっている：

```json
{
  "broker_account_id": "PA3SEQKOZ91C",
  "tracking_label": "alpaca_account_epoch_2026-08-17",
  "performance_scope": "current_account_since_baseline",
  "trades": [ { "account_id": "9a0de1fb-...", ... } ]
}
```

`broker_migration_ibkr_plan.md` セクション4のTrack Bでは、D0+3〜6週の期間に
**Alpaca Paper と IBKR Paper を同時に並走させるシャドー運用**を計画している。
この期間、両ブローカーの取引が同じ `trades` リストに混在すると：

- PF/WR等の集計がAlpacaとIBKRのトレードを合算してしまい、どちらのブローカー起因の
  結果か分離できない（`docs/broker_migration_ibkr_plan.md` セクション5「評価指標の分離」
  の前提が崩れる）
- `broker_tracker_mismatch` などのguardrail判定が、参照すべきでない方のブローカーの
  ポジションと突き合わせてしまう可能性がある
- 既存の go_no_go / ledger_quality_gate の判定ロジック（overlap=0, reversed=0 等）が
  複数ブローカーの取引を区別せずにチェックしてしまい、シャドー期間中に無関係な
  INVALID判定を出しかねない

→ **`environment_id` を台帳の一級フィールドとして導入し、環境ごとに集計・検証を
分離できるようにする**。

## 2. environment_id の値域

```
alpaca_paper   : 現行運用（Alpaca paper-api.alpaca.markets）
ibkr_paper     : IBKR Paper account（Track B D0+1週〜）
ibkr_live      : IBKR Live account（Track B D0+X以降）
```

`alpaca_live` は本計画のスコープ外（Alpaca Live自体を使う予定がないため、値域には
含めるが実運用では使用しない想定）。将来的な拡張に備え固定enumではなく文字列で
持たせる（既存の `runtime_mode` の `ALLOWED_RUNTIME_MODES` と同様のパターン）。

`environment_id` は**ブローカー種別 × paper/live** の直交軸であり、既存の
`runtime_mode`（research/paper/live_guarded/live）とは別軸。両者の関係は：

| runtime_mode | environment_id（想定） |
|---|---|
| `paper` | `alpaca_paper`（現行）→ 将来的に `ibkr_paper` |
| `live_guarded` / `live` | `ibkr_live`（移行後） |

## 3. 影響を受けるファイル・スキーマ

### 3-A. `data/tracking/pnl_state.json`（PnLTracker）

**現状**: 単一の `broker_account_id` / `tracking_label` フィールドがファイル全体に1つ。

**変更方針**:
- トップレベルに `environment_id: str` を追加（デフォルト値 `"alpaca_paper"` で
  既存データとの後方互換性を維持。マイグレーション時に全既存レコードへ
  `environment_id="alpaca_paper"` を一括付与）
- 各 `trade` レコード（`TradeEntry`）にも `environment_id` を追加
  （既存の `account_id` フィールドとは別軸。`account_id` はブローカー内の口座ID、
  `environment_id` はブローカー×paper/live区分）
- `tracking_label` の命名規則を `f"{environment_id}_epoch_{baseline_date}"` に一般化
  （現状の `alpaca_account_epoch_{baseline_date}` ハードコードを置き換え）

### 3-B. `data/tracking/fill_ledger.jsonl` / `fill_consumed_ledger.json`（FillLedger）

**現状**: `fill_key` は `fill.id`（Alpaca execution fill id）または
`order_id:symbol:side` の組み合わせ。ブローカーをまたいだ場合、**異なるブローカーの
order_idが偶然衝突する可能性はほぼゼロ**だが、同じsymbolを両ブローカーで同時に
保有する期間（シャドー運用）では `order_id:symbol:side` フォールバックキーの
一意性がブローカー跨ぎで保証されなくなる。

**変更方針**:
- fill_keyの生成に `environment_id` をプレフィックスとして含める：
  `f"{environment_id}:{fid}"` / `f"{environment_id}:{order_id}:{symbol}:{side}"`
- これにより、Alpaca側とIBKR側で同一symbolの取引が同時に走っても衝突しない

### 3-C. `data/guardrails/day_start_snapshot.json`（day_start_snapshot）

**現状**: `market_date` ごとに1ファイル、equity/unrealizedはブローカー非依存の数値。

**変更方針**:
- ファイル名またはトップレベルキーに `environment_id` を含める形に変更
  （例: `data/guardrails/day_start_snapshot_{environment_id}.json`）
- シャドー運用期間中、Alpaca側とIBKR側で別々のday-start baselineを持つ必要があるため

### 3-D. `config/reference/symbol_registry.yaml`

**現状**: symbol文字列をキーにした asset_class/sector/benchmark 定義。

**変更方針**: **environment_idの影響なし**（symbol分類はブローカーに依存しない
論理的な情報のため、共通のまま維持）。ただしIBKR側のconId解決層（A1棚卸しの
セクション8参照）は別途、symbol_registry.yamlとは独立したマッピングテーブルとして
追加する（IBKR固有、Track B）。

### 3-E. `config/runtime/current_mode.yaml`

**現状**: `mode: paper` の説明コメントに Alpaca固有の記述（「ALPACA_MODE must equal
'paper'」）。

**変更方針**:
- コメントを environment_id ベースの表現に書き換え（例:
  「`environment_id` must be one of the paper environments at startup」）
- `go_no_go` / `ledger_quality_gate` セクションに、**判定対象の environment_id を
  明示するフィールドを追加**（例: `applies_to_environment_id: alpaca_paper`）。
  これにより、9/15のGo/No-Go判定が明示的に「alpaca_paper環境の戦略パフォーマンス」
  のみを対象にしていることをconfig上でも保証できる（`docs/broker_migration_ibkr_plan.md`
  セクション5の「評価指標の分離」をコードレベルで裏付ける）

## 4. 集計・検証ロジックへの影響

以下のモジュールは `environment_id` でフィルタしてから集計・検証する必要がある
（Track B実装時にこれらの関数シグネチャに `environment_id` フィルタ引数を追加）：

| モジュール | 現状の処理 | 変更方針 |
|---|---|---|
| `pnl_tracker.py: get_summary_by_account()` | 既に `account_id` でフィルタする仕組みがある（`trades = [t for t in state.trades if t.get("account_id") == account_id]`） | この既存パターンを踏襲し、`get_summary_by_environment(environment_id)` を追加すれば十分。**ゼロから作る必要はない**（既存のaccount_idフィルタと同型） |
| `closed_trade_validator.py` | 全trades対象にoverlap/reversed等をチェック | `environment_id`ごとに独立してチェックするよう変更（Alpaca側の既存ledger_quality_gateに、IBKR側シャドーデータの一時的な不整合を混入させない） |
| `risk_budget.py` / `promotion_gate.py` | 全trades対象 | 同上、environment_id分離 |
| `equity_bridge.py` | broker equity と tracker合計の突合 | environment_idごとのbroker equityと突合する必要（Alpaca equityとIBKR equityを合算してはならない） |
| `console_renderer.py` | 単一の集計値を表示 | シャドー期間中は「メイン環境（alpaca_paper）」の表示を主とし、IBKR側は別セクション
  または別ページで表示（既存の go_no_go 表示ロジックを汚染しない） |

## 5. マイグレーション手順（Track B実装時、D0+3週目安＝シャドー運用開始前）

1. `pnl_state.json` に `environment_id` トップレベルフィールド追加
   （既存データは一括 `"alpaca_paper"` を付与、`--backup --preserve-attribution`
   相当の安全策を踏襲）
2. 各 `trade` レコードに `environment_id="alpaca_paper"` を一括付与
   （`scripts/rebuild_pnl_state_from_broker.py` 等の既存マイグレーションパターンを参考に、
   専用の一回限りスクリプトを作成）
3. `fill_ledger.jsonl` の fill_key に `environment_id:` プレフィックスを追加
   （既存レコードは `alpaca_paper:` プレフィックスで一括変換）
4. `day_start_snapshot.json` を `day_start_snapshot_alpaca_paper.json` にリネーム
   （読み込み側のパス解決を `environment_id` パラメータ化）
5. 上記すべてに対し、既存の `check_ledger_invariants` 相当のテストを
   `environment_id` 別に再実行し、移行前後でAlpaca側の数値が一切変化しないことを
   確認（テスト基準書 2-B のバグ再現テストと同様、移行前後比較テストを追加）
6. IBKR Paper用の空の `environment_id="ibkr_paper"` レコード群を追加開始
   （シャドー運用のBUY/SELLがここに書き込まれる）

## 6. 未決事項（Track B実装時に確定させる）

- `trades` を単一配列のまま `environment_id` フィールドで区別するか、
  ファイル自体を `pnl_state_alpaca_paper.json` / `pnl_state_ibkr_paper.json` と
  物理的に分離するか。**現時点では単一ファイル+フィールド区別を推奨**
  （既存の `get_summary_by_account` パターンとの一貫性、ファイル数増加による
  運用複雑化の回避のため）。ただしIBKR Live昇格後、長期的にはファイル分離も
  検討の余地あり
- console dashboard でのIBKR側データの表示要否・タイミング（シャドー期間中は
  非表示・ログのみで十分という可能性もある）

---

*作成: 2026-08-19*
