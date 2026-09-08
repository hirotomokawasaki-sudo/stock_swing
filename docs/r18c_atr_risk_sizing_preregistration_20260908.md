# R18-C ATR定額リスクサイジング — 事前登録（2026-09-08）

**状態**: 結果未確認時に固定した探索計画。

**本番影響**: なし。既存closed tradeのqty/PnLを読み取り専用で再計算する。
**ガバナンス**: `docs/promotion_governance.md` に従い、本検証だけでpaper・本番へ昇格しない。

## 仮説

非決算ギャップ/セクター急落による大口損失は、全銘柄を概ね同じ5%想定損失幅で
サイズするより、エントリー時ATRから想定損失幅を定めて**1トレードの最大リスク額を
揃える**方が、PF・下方尾・最大ドローダウンを改善する。

## 対象と時系列分割

- 対象: `data/tracking/pnl_state.json` のclosed trade（entry price/qty/PnLが有効なもの）。
- ATR: エントリー日までの14営業日True Range平均。エントリー当日の未確定情報は使わない。
- development: `exit_time < 2026-08-08`
- holdout: `exit_time >= 2026-08-08`
- ATR欠損行は除外し、coverageを必ず報告する。holdoutの結果を見てパラメータを変更しない。

## 固定した計算式

```text
risk_width_pct = max(ATR_multiple × ATR_pct_at_entry, 5%)
risk_budget_usd = baseline_equity × risk_budget_pct
target_qty = floor(risk_budget_usd / (entry_price × risk_width_pct))
counterfactual_qty = min(actual_qty, target_qty)  # 今回は縮小のみ
counterfactual_pnl = actual_pnl × counterfactual_qty / actual_qty
```

縮小のみとする理由: 同時点の総exposure/sector capを完全再構築できないため、低ボラ銘柄の
増額を許すと既存ハードキャップを越えた非実在ポートフォリオになる。増額側は本検証の
対象外とし、必要ならR13-C engine上で別途事前登録する。

## バリアント

| ID | risk budget | ATR multiple | 位置づけ |
|---|---:|---:|---|
| **P0** | **0.30%** | **2.0×** | **事前登録した主候補** |
| S1 | 0.30% | 1.5× | 感度分析のみ |
| S2 | 0.50% | 2.0× | 感度分析のみ |
| S3 | 0.50% | 1.5× | 感度分析のみ |

全バリアントで5%床、ATR window=14、baseline equityは
`pnl_state.json.baseline_equity`（欠損時はfail-closed）を使用する。

## 事前固定した判定基準

P0を「paper A/B候補」と呼べるのは、以下を**すべて**満たす場合のみ:

1. ATR coverage >= 90%。
2. development と holdout の双方で Net PnL差 > 0。
3. development と holdout の双方で PFが悪化しない。
4. holdoutの損失側CVaR 5%（最悪5%平均）が改善する。
5. 影響件数がholdoutで10件以上（単一銘柄依存を避ける最低条件）。

満たしても昇格ではなく、`promotion_governance.md` に従う前向きpaper A/Bの候補に留める。
感度分析S1-S3がP0を上回っても、後付けで主候補へ差し替えない。

## 既知の限界

- actual PnLの線形縮尺であり、qty変更によるfill/slippageの二次効果は無視する。
- 同時保有・現金再配分は再投資しないため、リスク抑制効果だけを測る保守的検証。
- yfinance/ローカル日足は日次粒度で、intraday gapの発生時刻を再現しない。
- 既存closed集合への追加試行であるため、検証台帳とtrial registryへ全試行を記録する。
