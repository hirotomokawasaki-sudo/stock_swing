# equity_bridge quarantine 根本原因: 第2のバグを発見・修正（2026-08-23夜）

## 経緯

08-23午後に`fetch_orders()`のページネーション不備を修正（`fetch_all_orders()`新規追加、
commit `adad1db`）。しかし`--dry-run`で検証したところ、ページネーション修正だけでは
新たに9件の時系列逆転トレード（entry_time > exit_time）が発生することが判明した。

## 発見した第2の根本原因

`fetch_all_filled_orders()`が`status == 'filled'`のみでフィルタしており、
**「部分約定後にキャンセルされた注文」**（`status='canceled'`だが`filled_qty > 0`）を
完全に除外していた。

実データで確認: 2026-06-01付で以下4銘柄が該当（合計402株の実約定が欠落）:
- ADBE: buy qty=242 canceled、filled_qty=101（$270.00で約定）
- MSFT: buy qty=160 canceled、filled_qty=143（$449.42で約定）
- CDNS: buy qty=160 canceled、filled_qty=49（$407.54で約定）
- AVGO: buy qty=144 canceled、filled_qty=109（$484.10で約定）

これらは全て、後に出現する売り注文の**本来の買いレッグ**だった。ADBEの例では
2026-06-03の101株売りに対応する買いがフィルタで除外されていたため、FIFOマッチャーが
無関係な後日（2026-07-28）の買いと誤マッチングし、entry_time > exit_timeという
物理的にあり得ない取引を生成していた。

## 修正

`scripts/rebuild_pnl_state_from_broker.py`の`fetch_all_filled_orders()`のフィルタ条件を
`status == 'filled'`から`float(filled_qty or 0) > 0`に変更。旧フィルタの厳密な上位集合
（`status=='filled'`の注文は必ず`filled_qty > 0`）であるため、既存の正常系には影響しない。

## 効果検証（`--dry-run`、本番データ未変更）

| 状態 | 時系列逆転トレード数 |
|---|---|
| 修正前（ページネーションのみ修正） | 9件 |
| 部分約定フィルタ修正後 | **1件** |

残る1件（CRWD）は`data/corporate_actions.json`に既に記録されている**既知の限界**:
2026-07-02のCrowdStrike 4:1分割時、Alpaca paper口座がqtyを自動調整しない仕様のため、
過去に手動でトラッカー側の該当ポジションを「再オープン」する介入を行った記録があり、
この手動介入は自動FIFOマッチャーでは再現できない。新規バグではない。

## テスト

`tests/unit/test_fetch_all_filled_orders.py`（新規7件）:
- canceled かつ filled_qty>0 の注文が含まれることを確認
- canceled かつ filled_qty=0 の注文が除外されることを確認
- 旧フィルタ（status=='filled'）で含まれていた注文が全て引き続き含まれることを確認
  （regressionガード）
- filled_qty欠損時のフォールバック確認
- ADBEの実シナリオを合成データで再現し、FIFOマッチャーが正しいペアを選ぶことを確認

フルスイート: 2119 passed / 2 skipped（regressionなし）

## 未実施（次のアクション、別途承認要）

このコード修正はこれまでどおり**将来のrebuild実行**にのみ効く。既存の101件quarantine
トレード自体の再統合（本番`pnl_state.json`書き換え）は未実施。`--backup`付きで
`rebuild_pnl_state_from_broker.py`を実行する必要があり、本番財務データの書き換えを
伴うため、明示的な別途承認を得てから実施する。
