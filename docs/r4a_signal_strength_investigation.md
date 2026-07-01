# R4-A: Signal Strength 飽和 — 根本原因調査レポート
**調査日**: 2026-07-01  
**対象**: `breakout_momentum_strategy.py` / `_calculate_signal_strength()`

---

## 現象

- Open trades 24件中 16件（66.7%）が `entry_signal_strength = 1.0`
- Closed trades 6件中 6件（100%）が `entry_signal_strength = 1.0`
- 全 BUY シグナルの約 73% が強度 1.0 に飽和 → **識別力がゼロ**

## 根本原因

```python
# src/stock_swing/strategy_engine/breakout_momentum_strategy.py L151
strength = min(momentum / 0.10, 1.0)
```

- **飽和閾値**: momentum ≥ 10% で `strength = 1.0` に達する
- **現在の市場**: 半導体/テック株は 60 日間で 15〜30% 上昇（強気相場）
- **結果**: 大多数のシグナルが飽和 → 全シグナルが「最高確信度」扱い

## 確認データ（2026-07-01 時点 open trades）

| strength | n | 代表銘柄 |
|---|---|---|
| = 1.0 | 16 | KLAC, AMAT, MU, AMD, SOXX, SMH など |
| 0.9-1.0 | 1 | PTF |
| 0.8-0.9 | 3 | ANET, TSM, FRWD |
| 0.7-0.8 | 3 | SMHX, QTEC, PANW |
| < 0.7 | 1 | PSCT |

## 修正オプション

### Option A: 閾値を引き上げる（シンプル、リスク低）
```python
strength = min(momentum / 0.20, 1.0)   # 20% で飽和
```
- メリット: 1行変更、テスト維持
- デメリット: 依然として線形、強気相場では再び飽和する可能性
- 推定効果: `= 1.0` を 73% → 約 30% に削減

### Option B: 多因子スコア（バランス型、推奨）
```python
momentum_score = min(momentum / 0.20, 1.0)   # 0〜1
volume_score   = min(avg_volume / 2_000_000, 1.0)  # 流動性
atr_score      = min(atr / latest_close / 0.03, 1.0)  # ボラティリティ
strength = (momentum_score * 0.60 + volume_score * 0.20 + atr_score * 0.20)
```
- メリット: 分布が改善、過去データで検証可能
- デメリット: ATR/volume のデータが feature layer から取得必要

### Option C: パーセンタイルランク（最も堅牢、データ要件高）
- 過去 N 日間の momentum 分布に対してパーセンタイルランクを計算
- `strength = percentile_rank(momentum, historical_distribution)`
- デメリット: 十分な履歴データが必要、より複雑

## 推奨実装順序

1. **R4-A 完了（本日）**: 根本原因ドキュメント化
2. **R4-B（07-18〜07-28）**: Option A（閾値変更）を先に実装し分布を確認
3. **R4-C（07-28〜08-04）**: Option B（多因子）で更に改善、コンソール表示
4. **Post-launch**: 十分なデータ蓄積後に Option C 検討

## 注意事項

- `min_signal_strength = 0.65`（フィルター閾値）は R4-B 実装後に再調整が必要
- 現在の 0.5x stock size 乗数は強度によらず一律 → R4 完了後に強度連動サイジングへ
- Entry filter の rolling PF gate（R2-D）は signal strength 飽和を間接的に補完している
