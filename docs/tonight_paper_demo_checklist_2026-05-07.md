# Tonight Check Checklist - 2026-05-07

## 目的
paper_demo cron 修正後の初回観測ポイントを短く確認する。

## 対象ジョブ
- `stock_swing_paper_demo_premarket`
- `stock_swing_paper_demo_market_open`

## 確認項目
### 1. 実行可否
- `status=ok` になっているか
- `exec approval / non-execution` 警告が消えているか
- `process` 追跡で完了まで見届けられているか

### 2. 実行時間
- premarket が大きく悪化していないか
- market_open が前回 `1164.6s` より短縮しているか
- timeout / background 取りこぼしが再発していないか

### 3. 実行内容
- decisions / actionable / orders submitted が取得できているか
- summary が簡潔に返っているか
- 異常な大量注文や想定外の挙動がないか

### 4. 判断基準
- 改善十分:
  - approval 警告なし
  - timeout なし
  - market_open の時間が明確に短縮
- 要追加対応:
  - approval 警告が残る
  - market_open が依然として長い
  - timeout / incomplete が再発

## 今夜の判断分岐
- 良好なら: T20 は観測継続のみ
- まだ重いなら: `universe / threshold / bar-limit` の cron 用軽量設定を検討
- T22 cautious regime 改善は、過剰最適化回避のため当面ペンディング維持
