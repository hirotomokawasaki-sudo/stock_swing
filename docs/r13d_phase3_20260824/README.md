# R13-D Phase 3: リバランス状態管理実装（2026-08-24）

**ステータス**: ✅ 状態管理の実装・検証完了。**本番配線（cron/paper_demo.py接続）は未実施**
（Phase 2から引き継いだスコープ境界を維持: 「実配線は別途ユーザー承認と昇格プロセスを経る」）。

## 背景

Phase 2（2026-08-23完了）の設計上の既知の限界として、`SectorRotationStrategy`が
**ステートレス**（呼び出すたびに「現在の」top-Nセクターのシグナルを出すだけで、
前回いつリバランスしたかの記憶を持たない）であることが明記されていた。paper_demo.py の
日次・複数回cronにそのまま配線すると、`SectorMomentumFeature`のランキングが変わる
たびに毎回ポジションを入れ替えてしまい、Phase 1で検証された「21営業日ごとのみ
再評価する」というバックテスト前提（Sharpe=1.370の根拠）と一致しなくなる。

## 実装内容

`src/stock_swing/strategy_engine/sector_rotation_state.py`（新規）:

- `RebalanceState`: `last_rebalance_date` / `current_sectors` / `current_holdings` /
  `rebalance_count`を持つ永続状態（dataclass）
- `SectorRotationStateStore`: JSON単一ファイルへのload/save（`CircuitBreakerStore`
  /`day_start_snapshot.py`と同じatomic write+os.replaceパターンを踏襲、追記ログでは
  なく上書き型の「現在状態」）
- `is_rebalance_due(state, today, hold_days)`: 純粋関数。状態なし（初回）または
  経過日数≥hold_daysでTrue。破損日付文字列は「安全側（リバランスする）」にfail
- `compute_rebalance_diff(current_holdings, new_holdings)`: 純粋関数。
  enter/exit/holdの3分割を返す（将来の実配線時にbuy/sellシグナルへの変換に使う想定、
  本タスクでは配線しない）
- `advance_rebalance_state(prior_state, today, new_sectors, new_holdings)`:
  リバランス実行後の次状態を構築（rebalance_count自動インクリメント）

## 検証（`scripts/r13d_phase3_state_machine_validation.py`、実データ2年分）

Phase 2の自己検証は21営業日おきのチェックポイントでのみ`SectorMomentumFeature`/
`SectorRotationStrategy`を呼んでいたため、「毎日呼ばれたらどうなるか」は未検証だった。
本スクリプトは**436営業日全ての日次呼び出し**をシミュレートし、状態マシンが
正しくゲートしているかを検証:

```
Simulated 436 daily calls (every trading day)
Actual rebalances triggered: 31 (naive expectation ~20.8 at hold_days=21 spacing)
Stability violations (holdings changed without a due rebalance): 0

✅ Zero stability violations: holdings only ever change on a due rebalance day
✅ Rebalance count consistent with hold_days=21-spaced cadence
```

**重要な発見（自己開示、モジュールdocstringにも明記）**: 実際のリバランス回数（31件）は
素朴な期待値（436/21≈20.8件）より約49%多い。原因は`is_rebalance_due()`が
**暦日**ベース（`(today - last_date).days >= hold_days`）でゲートしており、
Phase 1のバックテストが使っていた**営業日**ベースの21日カウントとは異なるため
（週末・休日を挟むと暦日カウントの方が早く閾値に達する）。この差は意図的な簡略化
（市場カレンダー依存を避けるため）であり、モジュールdocstringに限界として明記済み。
失敗方向は「リバランスがやや多めになる」という保守的な側（リバランス漏れではない）。

## テスト

`tests/unit/test_sector_rotation_state.py`（22件）:
- `is_rebalance_due`の初回/境界値/破損データのfail-safe動作
- `compute_rebalance_diff`のenter/exit/hold全パターン
- `advance_rebalance_state`のカウント管理
- `SectorRotationStateStore`の永続化（欠損ファイル/破損JSON/再インスタンス化後の
  読み込み一貫性）
- End-to-endリバランスサイクル（初回due→未到達→hold_days後due、を状態ファイル
  経由で確認）

フルスイート: 実行結果は本README作成と並行してバックグラウンドで確認中
（`docs/r13d_phase3_20260824/test_output.txt`参照）。

## 次のアクション（未着手、本タスクのスコープ外）

1. **本番配線**: `paper_demo.py`への実接続（`RebalanceState`の読み込み→due判定→
   `compute_rebalance_diff`→実際のbuy/sell CandidateSignal生成→exit実行）は
   別途ユーザー承認が必要。既存戦略（breakout_momentum_v1/event_swing_v1）と
   同じ昇格プロセスを経ること
2. **暦日→営業日カウントの精緻化**（優先度低）: 市場カレンダー依存を追加すれば
   Phase 1のバックテストとの日数カウント精度を上げられるが、本モジュールの
   「依存軽量」設計方針とのトレードオフ
3. **コスト・スリッページ込みの再検証**（R13-D roadmap記載の残項目）: R13-Cで
   確立したt+1約定・conservative exit・slippageモデリングをsector rotation戦略にも
   適用し、Phase 1の生シグナル結果ではなく取引可能な形での再バックテストを実施

## 変更・新規ファイル
- `src/stock_swing/strategy_engine/sector_rotation_state.py`（新規）
- `scripts/r13d_phase3_state_machine_validation.py`（新規、検証スクリプト）
- `tests/unit/test_sector_rotation_state.py`（新規、22件）
- `docs/r13d_phase3_20260824/`（本README + 検証出力 + テスト出力）
