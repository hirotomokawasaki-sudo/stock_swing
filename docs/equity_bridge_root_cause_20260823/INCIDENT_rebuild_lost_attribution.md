# インシデント記録: rebuild実行が49件のattribution（strategy_id/decision_id）を破壊し、即座に復元（2026-08-23夜）

## 何が起きたか

`fetch_all_filled_orders()`の部分約定フィルタ修正後、影響を検証するため
`python scripts/rebuild_pnl_state_from_broker.py --backup`を実際に本番`data/tracking/
pnl_state.json`に対して実行した。実行後、`tests/unit/test_r8v2_ml_readiness.py::
TestCheckReadinessRealData::test_real_data_matches_known_analysis`が失敗し、
`attributable_count`が49→0になっていることが判明した。

## 根本原因

`rebuild_pnl_state_from_broker.py`は`data/raw`のブローカー注文履歴のみから
`state['trades']`を**丸ごと再構築**する。再構築されたトレードは全て
`strategy_id='broker_reconstructed'` / `original_strategy_id='broker_reconstructed'`
で生成される（`match_buy_sell_orders()`内、4箇所）。

`--preserve-attribution`（デフォルトTrue）は`load_existing_attribution()`/
`apply_attribution()`経由で以下のみを再構築後のトレードに復元する:
- `exit_reason`（`exit_broker_order_id`または`(symbol, exit_time, pnl)`キーで復元）
- `entry_signal_strength`（`broker_order_id`キーで復元）
- `quarantined_trades`リスト全体（そのままコピー）

**`strategy_id` / `original_strategy_id` / `decision_id` / `run_id` / `experiment_id`
などの「どの戦略ロジックがこの取引を発注したか」を示すメタデータは一切復元されない**。

既存の`pnl_state.json`にあった49件のattributableトレード（`PaperExecutor`が
実際の発注時にリアルタイムで記録した、`decision_id`付きの正真正銘の本番トレード）は、
rebuild実行によって`broker_reconstructed`に上書きされ、その戦略起源情報が
失われた。PnL自体（金額）は保持されていたが、「このPnLがどの戦略判断に
起因するか」という、R13-A/B/CやPromotion Gateが依存する属性情報が消えた。

## 発見と即時対応

1. フルテストスイート実行で`test_r8v2_ml_readiness.py`が実データとの
   sanity check失敗として検知（`attributable_count >= 25`のassertion失敗）
2. 原因を`load_existing_attribution()`/`apply_attribution()`のフィールド
   範囲不足と特定
3. rebuild実行**直前**に`--backup`フラグで自動作成されたバックアップ
   （`pnl_state_backup_20260823_230103.json`）から即座に復元
4. 復元後、`diff`でバイト単位の完全一致を確認
5. フルテストスイート再実行: 2119 passed / 2 skipped（regressionなし）

## 現状

`data/tracking/pnl_state.json`はrebuild実行前の状態に完全復元済み。
`fetch_all_filled_orders()`の部分約定フィルタ修正（コード）は生きたまま
コミット・プッシュ済みだが、**その修正を反映した実際のrebuildは本番データに
適用されていない**（このインシデントにより、安全に適用する方法が
確立するまで見送り）。

## 教訓・今後の必須対応

`rebuild_pnl_state_from_broker.py`を本番`pnl_state.json`に対して実行する前は、
必ず以下を確認すること:

1. **`--dry-run`だけでなく`test_r8v2_ml_readiness.py`のようなattribution
   依存のテストも実行後に確認する** — PnL/件数の一致だけでは
   attribution破壊を検知できない
2. `--preserve-attribution`は`exit_reason`/`entry_signal_strength`/
   `quarantined_trades`のみを保護し、`strategy_id`/`original_strategy_id`/
   `decision_id`/`run_id`/`experiment_id`は保護しない、という制限を
   常に意識する
3. 恒久対応（未実施、次のアクション候補）: `load_existing_attribution()`/
   `apply_attribution()`を拡張し、`strategy_id`/`original_strategy_id`/
   `decision_id`/`run_id`/`experiment_id`も`exit_broker_order_id`または
   `broker_order_id`キーで保存・復元する。これが実装されるまで、
   `rebuild_pnl_state_from_broker.py`を本番`pnl_state.json`に対して
   実行するのは**推奨しない**

## 保存された証跡ファイル（削除しない、gitignore対象）

- `data/tracking/pnl_state_backup_20260823_230103.json`
  （rebuild実行直前、正しい状態、現在の本番と同一）
- `data/tracking/pnl_state_backup_before_crwd_fix_20260823_230251.json`
  （rebuild実行後・CRWD修正前、attribution破壊済みの中間状態）
- `data/tracking/pnl_state_broken_by_rebuild_20260823_230700_DO_NOT_USE.json`
  （CRWD修正後・復元前、attribution破壊が最終的に確定した状態。
  ファイル名どおり使用禁止、次の恒久対応実装時の検証データとして保持）
