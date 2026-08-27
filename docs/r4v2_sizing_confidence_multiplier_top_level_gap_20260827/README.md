# R4-v2/R13-B残課題調査中に発見: sizing.confidence_multiplierの永続化ギャップ修正（2026-08-27）

## 発見の経緯

「他に対応可能なことは」の調査で、R4-v2 confidence calibration readiness
（`scripts/check_confidence_calibration_readiness.py`、96/100件で僅かに
NOT_READY）とR13-Bのconfidence_multiplier検証結果を実データで再確認していた
ところ、実際の`data/decisions/*.json`をサンプル調査した際に不整合を発見した。

## 発見内容

`PositionSizingSnapshot.confidence_multiplier`フィールドは2026-08-14に
「gap #3」対応として追加され、`PaperExecutor._calculate_position_size()`で
正しく設定されている（`decision.sizing.confidence_multiplier = result.
confidence_multiplier`、`paper_executor.py:466`）。また`evidence["sizing"]`
辞書にも正しく含まれている（`paper_executor.py:431`、これは
`check_confidence_calibration_readiness.py`が読んでいる場所）。

しかし`paper_demo.py`の`_save_decisions()`関数がJSON永続化時に構築する
**トップレベルの`sizing`辞書には`confidence_multiplier`キーが一度も
含まれていなかった**——同関数内の他18フィールド（`final_shares`/
`shares_by_risk`/`confidence`等）は全て転記されているのに、この1フィールドだけ
転記漏れしていた。

実データで確認: `data/decisions/*.json`全2871件中、トップレベル
`sizing.confidence_multiplier`が存在する件数は**0件**。一方
`evidence.sizing.confidence_multiplier`は正しく記録されている
（例: `decision_PATH_20260825_010004_....json`で`evidence.sizing.
confidence_multiplier=1.2`が確認できるのに、トップレベル`sizing`には
このキー自体が存在しない）。

## 影響評価

- **R4-v2 readiness check** (`check_confidence_calibration_readiness.py`)
  と**R13-B検証**(`simulate_confidence_multiplier_sizing_fix.py`)は
  いずれも`evidence.sizing.confidence_multiplier`を読んでおり、
  **このギャップの影響を受けていなかった**（両スクリプトの過去の結論・
  数値は無効化されない）
- 影響を受けるのは、スキーマ上より発見しやすい場所であるトップレベル
  `sizing`ブロックだけを見る可能性のある**将来の**分析ツール・手動調査

## 修正内容

`src/stock_swing/cli/paper_demo.py`の`_save_decisions()`のトップレベル
`sizing`辞書構築部分に`"confidence_multiplier": d.sizing.confidence_
multiplier`を追加（既存フィールドの値は一切変更しない、純粋な追加のみ）。

テスト追加:
- `tests/unit/test_p6_join_fix006.py`に
  `test_top_level_sizing_includes_confidence_multiplier`を新規追加
  （`_decision_stub()`の`sizing`スタブにも`confidence_multiplier=1.2`を追加）

## テスト結果

- 関連テスト: `test_p6_join_fix006.py` / `test_p6_end_to_end.py` /
  `test_confidence_multiplier_recording.py` /
  `test_confidence_calibration_readiness.py`: **22 passed**
- フルスイート: **2240 passed / 2 skipped**（既存2239+新規1、regressionなし）

## 次のアクション

特になし（純粋な観測性ギャップの修正）。R4-v2 confidence calibration自体は
引き続き96/100件でNOT_READY（あと4件の自然蓄積待ち、外部要因）。
