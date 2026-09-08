# volatility_adjusted_stop: multiplier_max=1.25 全履歴再検証（2026-09-08）

## 目的

2026-09-08中間レビューで初観測した `multiplier>1` のwiden悪化を抑える候補として、
`volatility_multiplier_max` を現行1.75から1.25へ制限した場合を日次パスで再検証した。
本番設定は変更していない。

## 実行

```bash
python scripts/simulate_daily_path_volatility_stop.py --multiplier-max 1.25
```

## 結果

- closed 357件を読込み、同日entry/exit 54件を除いた292件でPnL比較。
- baseline replay: **-$183,169.45**
- max=1.25: **-$174,941.71**
- 差分: **+$8,227.74**
- 改善22件（合計+$24,220.21）、悪化14件（合計-$15,992.47）、不変256件。
- baselineでstop_lossでなかったトレードへの新規誤stop: **0件**。
- exit reason変更: 3件。

最大改善はPLTR（+$7,989.75）、最大悪化はINTC 2026-05-12（-$8,199.12）。
max=1.25でもwiden由来の尾は残るため、集計値だけで安全性を断定しない。

## 判定

**9/22の正式評価候補として維持**。集計ではbaselineより改善し、新規誤stopも0件だった。
ただし日次終値リプレイのexit reason一致率は180/303（59%）であり、intraday価格・実fill・
run時ATRを再現しない。paper設定の変更は、9/22レビューの事前基準と
`docs/promotion_governance.md` に従い別途判断する。
