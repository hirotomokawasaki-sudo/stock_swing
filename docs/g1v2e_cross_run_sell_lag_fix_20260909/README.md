# G1-v2-e: run間 pending SELL 約定遅延による誤HALTの修正

**対応日**: 2026-09-09
**対象インシデント**: PATH SELL（2026-09-08 UTC）

## 事象

- 13:25:15: PATH 3,339株のSELLを送信
- 13:31:44: ブローカー側で約定
- 13:35: broker側からPATHが消えた一方、trackerは未消費で
  `tracker_only=PATH` となり、circuit breakerが誤HALT
- 13:45:07〜08: 次runでfillを取り込み、trackerを更新
- 14:03および21:37のsnapshot: `mismatch_count=0`

従来のlag除外は当該runのメモリ上のsubmissionしか参照しなかったため、
run間で約定したSELLを既知の同期遅延として識別できなかった。

## 修正

SELL送信時に既に永続化され、fill消費後に削除される
`data/tracking/pending_exit_reasons.json` を利用する。

1. `read_recent_pending_exit_symbols()` が未消費SELLの銘柄を読む
2. `written_at` から **30分以内** のレコードだけをlag除外に渡す
3. `apply_lag_exclusion()` がcurrent-run SELLと同様にpresence/qty差を一時猶予する

安全性:

- 30分を超えた不整合は猶予しない
- 未来時刻、欠損、破損JSON、別銘柄は猶予しない
- 読み取り失敗時は空集合を返し、既存guardrailを厳格なまま維持する
- mismatch閾値、発注ロジック、戦略設定は変更しない

## 復旧

`snapshot_20260908_213739.json` で `mismatch_count=0` を確認後、
`reset_circuit_breaker.py` に理由を記録して `recovery_pending` へ移行した。
次回のclean scheduled paper runが正常なら既存ロジックで `ok` に戻る。

## 回帰テスト

- PATHの実インシデント形状（current-run submissionなし、recent pending SELLあり）
- pending SELLと異なる銘柄の不整合を猶予しない
- run間partial-fill qty差
- TTL境界、期限切れ、未来時刻、破損store
