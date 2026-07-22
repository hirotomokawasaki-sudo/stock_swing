# stock_swing テスト基準書

**更新日**: 2026-07-22  
**目的**: 実装後に毎回個別指示なしで本番水準のテストを書くための行動規範。

---

## 0. 基本方針

- テストは「動くことの確認」ではなく「壊れないことの証明」
- 新しい関数・クラス・フローを追加したら、この基準書のチェックリストを埋める
- 既存テストの合計件数より「どのパスをカバーしているか」を優先する

---

## 1. 必須カバレッジ（すべて埋めること）

### 1-A: 関数単位
新しい関数を追加したら必ず以下をテストする：

| テスト種別 | 例 |
|-----------|-----|
| **正常系** | 期待する入力 → 期待する出力 |
| **境界値** | None / 空リスト / 0 / 最大値 |
| **ファイル欠損** | config YAML が存在しない → fallback を返す or 例外を明示 |
| **破損入力** | YAML パース失敗 / 不正 JSON → クラッシュしない / fallback を返す |
| **フォールバックの中身** | fallback の値が「フェイルクローズ」になっているか（例: enforce=True） |

### 1-B: ステートマシン
新しいステート・遷移を追加したら：

| テスト種別 | 例 |
|-----------|-----|
| **全遷移** | A→B、B→C など |
| **中断遷移** | 状態 B 中に別イベントが来たら → 期待する状態 |
| **逆方向ブロック** | B→A が禁止なら、その禁止を確認 |
| **永続性** | ファイルに保存して再ロードしても状態が維持されるか |
| **no-op ケース** | 既に目標状態にある場合は変化しない |

### 1-C: レイヤー伝播
値が複数層を通る場合（config → service → summary → renderer）：

```
config YAML
  ↓ read_xxx() で読み込む
  ↓ Service/ConsoleSummary に渡す
  ↓ to_dict() に入る
  ↓ ConsoleRenderer が描画する
```

**各レイヤーに1件以上のテストを置く**。「renderer で間接的に確認している」は NG。

### 1-D: Acceptance Criteria との対応
改善計画（console_improvement_tasks.md）に記載された acceptance criteria 1件につき
最低 1件のテストを書く。テスト名に `ac_` プレフィックスをつけるか、docstring に
「Acceptance: <criteria>」と明記する。

---

## 2. テストの質基準

### 2-A: テスト名規約
```
test_<対象>_<条件>_<期待結果>

例:
  test_clear_returns_recovery_pending_when_verification_required
  test_read_ledger_quality_gate_missing_file_returns_fallback
  test_invalid_ledger_console_shows_no_go
```

### 2-B: バグ再現テスト（回帰）
バグ修正・事後対応を実装したら、**そのバグを再現するテストを必ず追加**する。
テストコメントに発生日・commit・インシデント名を記載する。

```python
def test_buy_lag_excluded_from_mismatch_count():
    """
    Regression: 07-21 circuit-breaker false HALT (META+HPQ BUY lag at market open).
    Commit: 84e4532 / G1-v2
    Root cause: tracker recorded BUY immediately, broker API lagged → tracker_only → mismatch=2
    """
```

### 2-C: ヘルパーとフィクスチャ
- テスト内でオブジェクト生成が3行以上になる場合はヘルパー関数に切り出す
- `tmp_path` を使ってファイルテストを分離する（グローバルステートに依存しない）
- モックは「外部 I/O（Broker API / Finnhub）」のみに限定。内部ロジックはモックしない

### 2-D: アサーション
- `assert x` だけで終わらせない。失敗時のメッセージを書く
- `assert state.status == "recovery_pending", "halt during recovery_pending must re-halt"`
- 数値の比較は `==` でなく適切なマージンを持たせる（金額は `pytest.approx`）

---

## 3. テストを書くタイミング（実装フロー）

```
1. acceptance criteria を確認
2. テストを先に書く（or 実装と同時に書く）
3. 実装する
4. テスト全通過を確認
5. チェックリスト（Section 4）を埋める
6. commit
```

「実装後にテストを書く」場合、以下を必ず確認：
- テストが最初から PASS していないか（テストの書き方が間違っている可能性）
- テストを FAIL させてから実装で PASS させたか

---

## 4. 実装後チェックリスト（コミット前に確認）

```
[ ] 新しい public 関数に正常系テスト
[ ] ファイル欠損 / 破損入力のフォールバックをテスト
[ ] ステートマシンの全遷移をテスト（中断遷移含む）
[ ] 値のレイヤー伝播をテスト（config→service→summary→renderer）
[ ] acceptance criteria に対応するテストが存在する
[ ] バグ修正の場合、バグ再現テストを追加した
[ ] テスト名が「条件と期待結果」を説明している
[ ] python -m pytest --tb=short -q で全テストが PASS する
```

---

## 5. このプロジェクト固有の注意事項

### 5-A: paper_demo.py の統合テスト
paper_demo.py 本体の統合テストは複雑すぎるため unit テストではカバーしない。
その代わり、paper_demo が呼び出す **個別モジュール**（circuit_breaker / runtime / 
guardrails / pnl_tracker 等）を単体でテストする。
`tests/integration/` の統合テストは外部APIが必要なためスキップ扱い。

### 5-B: 既存テストの高品質サンプル（参考にすること）
- `tests/unit/test_g1v2_postrun_lag_exclusion.py` — class ベース・helper・incident 説明
- `tests/unit/test_f1_ledger_integrity.py` — state persistence・quarantine 境界値
- `tests/unit/test_circuit_breaker.py` — state machine 全遷移

### 5-C: テストカバレッジの確認
```bash
python -m pytest --tb=short -q   # 全テスト
python -m pytest tests/unit/test_<module>.py -v   # 対象モジュールのみ
```
