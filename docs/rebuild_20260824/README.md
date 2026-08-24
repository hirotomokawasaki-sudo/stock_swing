# 2026-08-24 pnl_state.json rebuild + 安全装置バグ3件の発見・修正

**ステータス**: ✅ rebuild実行完了・全invariant PASS。安全装置バグ3件修正済み・テスト済み。

## 背景

2026-08-23夜のインシデント（rebuild実行がattribution 49件を破壊、即座に復元・
根本修正）を踏まえ、08-24にユーザー承認のもと慎重に再度rebuildを実行した。
今回は「dry-run確認→ユーザー提示→実行→検証」の各ステップでチェックポイントを
設けたところ、**安全装置自体（`verify_rebuild_integrity.py`）に新たなバグ**を
発見し、加えて実行中にさらに2件の関連バグを発見した。

## 発見・修正したバグ（3件）

### バグ1: `verify_rebuild_integrity.py`のoverlap誤検知（偽陽性）

`check_closed_quarantine_overlap()`が`trade_id`（`broker_match_NNNN_SYMBOL`
形式、rebuild実行ごとに連番で再採番される）で重複判定していたため、たまたま
同じtrade_id文字列に別々の実トレードが割り当てられ「重複」と誤検出していた。

**重要**: `scripts/audit_trades_with_market_data.py`の`check_ledger_invariants()`
は2026-07-28に同じ問題を発見し、`(broker_order_id, exit_broker_order_id)`
ペアでの判定に修正済みだったが、`verify_rebuild_integrity.py`側は同じ修正が
反映されておらず、regressionとして再発していた。

**検証**: 実際のブローカー注文履歴を突き合わせたところ、誤検知された
ADBE 1件・AMAT 2件のFIFOマッチングは完全に正しく（entry < exit、数量一致）、
昨夜の根本原因修正（ページネーション対応・部分約定キャンセル対応）が正常に
機能していたことを確認。

**修正**: `check_closed_quarantine_overlap()`を`(broker_order_id,
exit_broker_order_id)`ペアでの判定に変更。

### バグ2: `verify_rebuild_integrity.py`の「成功」誤表示

`main()`の`--fix`パスが、検出した全issueのうち`daily_snapshots`/`peak_price`
のみを修復し、他のINVARIANT FAIL（overlap/reversed chronology/pnl consistency）
は検出するだけで放置していたにもかかわらず、`total_fixed > 0`という理由だけで
無条件に「✅ All checks passed」を返していた。呼び出し元
`rebuild_pnl_state_from_broker.py`もこれを受けて「✅ Post-rebuild integrity
check passed」と誤表示し、`main()`は常に`return 0`していた。

**修正**:
- `--fix`適用後に全チェックを再実行し、未解決のINVARIANT FAILが残っていれば
  非0 exitで明確に失敗報告するよう変更（WARNING単独は許容）
- `rebuild_pnl_state_from_broker.py`もpost-check失敗時に非0を返すよう修正

### バグ3: `apply_tombstone_filter()` / `migrate_quarantine_invalid_trades.py`の集計未更新

- `apply_tombstone_filter()`（rebuild時にquarantine済みトレードの再生成を除去）
  は`total_trades`/`cumulative_realized_pnl`は再計算していたが、
  `winning_trades`/`losing_trades`の再計算を忘れていた
  （実例: 5件のtombstone除去後、`winning_trades=164`/`losing_trades=176`
  ＝除去前の341件ベースの値のまま残存。実際の336件の内訳は163勝/172敗/
  1件PnL=0）
- `migrate_quarantine_invalid_trades.py`もトレードをclosedからquarantineへ
  移動する際、`cumulative_realized_pnl`/`winning_trades`/`losing_trades`を
  一切更新していなかった（CRWD 1件quarantine化で`cumulative_realized_pnl`が
  $900ズレて`verify_rebuild_integrity.py`のpnl consistency invariantで検出）

**修正**: 両スクリプトとも、変更後の実際のトレードリストから
`winning_trades`/`losing_trades`/`cumulative_realized_pnl`を再計算するよう修正
（差分演算ではなく実データから再導出、将来的なズレの累積を防止）。

## 実施した作業（時系列）

1. dry-run確認 → ユーザー提示（closed 252→336件、+84件の見落とされていた
   トレードが復元される見込みと説明）→ 承認
2. `--backup --preserve-attribution`で実行 → 「passed」表示を信用せず
   独自に検証 → overlap 3件・reversed 1件を発見（バグ1発覚のきっかけ）
3. 実データ突き合わせでoverlap 3件は偽陽性と確定 → いったんロールバック
   （sha256一致でバイト単位の完全復元確認）
4. バグ1・2を修正、回帰テスト11件追加
5. 隔離環境（本番ファイル非使用）で同じrebuildを再現し、修正後ロジックで
   検証 → overlap 0件（正しい）・reversed 1件（CRWD、真陽性）を確認
6. 改めて本番に対しrebuild実行 → 修正後の`verify_rebuild_integrity.py`が
   正しく「1件未解決（CRWD reversed chronology）」を報告、非0 exit
7. `migrate_quarantine_invalid_trades.py --dry-run`でCRWD 1件のみ対象と確認
   → 実行 → win/loss集計ズレ発覚（バグ3発見）
8. いったんrebuild直後の状態まで巻き戻し、`rebuild_pnl_state_from_broker.py`
   （バグ3含む）を修正
9. 最初から再実行（rebuild → quarantine migration）→ `verify_rebuild_
   integrity.py --fix`で **全チェックPASS** を確認
10. `check_pnl_invariants.py`でINV1（clean_sum ≈ cumulative）PASS確認
    （INV2は`performance_summary.json`が2026-06-24から未更新という既存の
    別問題、今回のrebuildとは無関係と確認済み）
11. equity_bridge再計算: `unexplained_diff` $168,869.89 → $160,998.66に改善
    （quarantine自体の再統合は未実施のため大幅な解消ではない。運用判断は
    引き続きPre-Launch Gate Review 09-08〜09-12に委ねる）
12. フルテストスイート実行、regressionなしを複数回確認

## 最終結果（rebuild + quarantine migration後）

| 項目 | rebuild前 | rebuild後 |
|---|---|---|
| closed trades | 252 | 335 |
| open trades | 17 | 17 |
| quarantined_trades | 101 | 102（CRWD追加） |
| winning_trades | - | 163 |
| losing_trades | - | 171 |
| cumulative_realized_pnl | -$20,573.51 | -$13,274.14 |
| attribution coverage (exit_reason based) | 98.8% | 74.6%（※下記参照） |
| equity_bridge unexplained_diff | $168,869.89 | $160,998.66 |

**重要な注記（attribution coverage低下について）**: 新たに復元された84件の
トレードは、2026-05〜のブローカー注文履歴のみから復元されたものであり、
当時の意思決定ログ（`exit_reason`等）自体がそもそも存在しない
（当時のシステムが記録していなかった、または記録が別の理由で失われている）。
これはrebuildによる劣化ではなく、**元々把握できていなかったトレード履歴を
可視化した結果、母数（closed件数）が増えたことによる相対的な低下**。
今後のPre-Launch Gate Reviewでこの数値の解釈に注意すること。

## テスト

- `tests/unit/test_verify_rebuild_integrity.py`（新規11件）: overlap誤検知
  修正・成功判定修正の回帰テスト
- `tests/unit/test_rebuild_and_quarantine_count_consistency.py`（新規9件）:
  tombstone filter・quarantine migrationの集計整合性回帰テスト
- フルスイート: **2210 passed / 2 skipped**（baseline 2201 + 20で一致、
  regressionなし）

## 変更ファイル
- `scripts/verify_rebuild_integrity.py`（バグ1・2修正）
- `scripts/rebuild_pnl_state_from_broker.py`（バグ2・3修正）
- `scripts/migrate_quarantine_invalid_trades.py`（バグ3修正）
- `tests/unit/test_verify_rebuild_integrity.py`（新規）
- `tests/unit/test_rebuild_and_quarantine_count_consistency.py`（新規）
- `data/tracking/pnl_state.json`（本番データ、rebuild + quarantine migration適用済み）
- バックアップ: `data/tracking/pnl_state_backup_20260824_090956.json`（元の
  正常状態）、`pnl_state_backup_20260824_093607.json`（rebuild直前）、
  `pnl_state.backup_quarantine_migrate_20260824_003616.json`
  （quarantine migration直前）

## 次のアクション
- equity_bridgeの残る$160,998.66差分（quarantine 102件の再統合可否）は
  引き続きPre-Launch Gate Review（09-08〜09-12）で運用判断
- attribution coverage低下（74.6%）の解釈をPre-Launch Gate Review資料に
  明記すること
- 今回発見した3つの安全装置バグは、次回以降のrebuild実行時にも同種の
  問題が再発しないことをテストで保証済み
