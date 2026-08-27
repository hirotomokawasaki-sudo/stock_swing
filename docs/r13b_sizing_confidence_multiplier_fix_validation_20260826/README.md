# R13-B sizing側: confidence_multiplier no-opバグ 実データ検証（2026-08-26）

## 背景

`docs/console_improvement_tasks.md` R13-Bで2026-08-23に「`position_sizing.py`の
`confidence_multiplier`はhigh-confidence側（1.2倍）が既存capでclipされno-op化して
いることが戦略レビューで判明済み」と記載されていたが、**未検証**のまま残っていた
（sizing変更は固定qty履歴に対して直接バックテスト不可なため）。

2026-08-26、equity_bridge対応の副産物として質問が浮上し、xhigh reasoningのまま
実データで検証・修正案設計・ヒストリカル効果測定まで着手した。

**本作業は本番コード（`src/stock_swing/risk/position_sizing.py`）を一切変更していない。**
すべて`scripts/simulate_confidence_multiplier_sizing_fix.py`による読み取り専用の
分析。

## バグの実証（既存コード読解＋実データ）

`position_sizing.py`の該当ロジック:

```python
base_final_shares = min(shares_by_risk, shares_by_notional, shares_by_exposure, shares_by_sector)
boosted = floor(base_final_shares * confidence_multiplier)
cap = min(shares_by_risk, shares_by_notional, shares_by_exposure, shares_by_sector)  # ← baseと同一式
final_shares = min(boosted, cap)
```

`cap`が`base_final_shares`と全く同じ4値のminで再計算されているため、
`cap == base_final_shares`が数学的に常に成立する。結果:
- `confidence_multiplier > 1.0`（confidence≥0.80、1.2倍）: `boosted > cap`となり
  常に`cap`側が採用される → **ブーストは絶対に発火しない（100%無効）**
- `confidence_multiplier < 1.0`（confidence<0.60、0.7倍）: `boosted < cap`となり
  `boosted`側が採用される → **カットは正常に発火する**

`data/decisions/*.json`のうち`confidence_multiplier`が明示的に記録されている
85件（2026-08-14の記録開始以降）で検証:
- cm=1.2（55件）: 全55件で`final_shares`が3-way cap（risk/notional/exposure）を
  超えていない → ブースト0%発火
- cm=0.7（7件）: 6/7件で`final_shares`が3-way capより小さい → カット86%発火

→ **非対称バグを完全に実証**（高確信を活かせない一方、低確信の縮小だけが効く）。

## 修正案（未適用、テストのみ）

confidence_multiplierを「4-way capで既に確定した後の数量」に掛けるのではなく、
**リスク予算（`max_loss_usd`、または同義の`shares_by_risk`）に事前に掛ける**方式に
変更する:

```python
# 現行（バグ）
base_final_shares = min(shares_by_risk, shares_by_notional, shares_by_exposure, shares_by_sector)
boosted = floor(base_final_shares * confidence_multiplier)
cap = min(shares_by_risk, shares_by_notional, shares_by_exposure, shares_by_sector)
final_shares = min(boosted, cap)

# 修正案
shares_by_risk_adjusted = floor(shares_by_risk * confidence_multiplier)
final_shares = min(shares_by_risk_adjusted, shares_by_notional, shares_by_exposure, shares_by_sector)
```

この修正の性質:
- notional/exposure/sectorの既存ハードキャップは**一切変更されない**
  （他のリスク管理策との整合性は保たれる）
- リスク予算（`shares_by_risk`）が実際にボトルネックになっている場合のみ、
  confidenceが真に数量を左右する
- notional/exposure/sectorの方が厳しい場合はブーストしても無効
  （これは意図した挙動であり、バグではない——他の独立したリスク上限を
  confidenceで突破させるべきではないため）

## 検証結果

### PART 1: メカニズム検証（全母集団n=58、qtyへの影響のみ、PnL不要）

`confidence_multiplier`が記録され且つ`final_shares > 0`（sizingでスキップされて
いない）58件の全件で検証:

| ケース | n | 修正後にqtyが実際に増える/減る件数 |
|---|---|---|
| ブースト（cm=1.2） | 39 | 25/39件でqty増加（残り14件はnotional/exposure/sectorが先にボトルネックのため無変化=正常挙動） |
| カット（cm=0.7） | 4 | 4/4件で現状通りqty減少を維持（回帰なし確認） |

→ **修正は意図通りに機能する**（risk-boundなケースの64%でブーストが実際に有効化、
notional等がボトルネックのケースでは正しく無効のまま、カット側の既存挙動は
完全に保持）。

### PART 2: トレード結果連動検証（⚠️小標本、参考値のみ）

`decision_id`が実際のclosed tradeに紐付き、かつ`confidence_multiplier`が記録
されている交差点は**わずかn=2**（INTC, MRVL、いずれもcm=1.2のブーストケース）。

| symbol | 実際qty | 修正後qty | 実際PnL | 修正後PnL推定 | 差分 |
|---|---|---|---|---|---|
| INTC | 389 | 466 | -$4,874.17 | -$5,838.98（推定） | -$964.81 |
| MRVL | 156 | 187 | +$1,944.37 | +$2,330.75（推定） | +$386.38 |

**この2件だけでは「修正が儲かるか損か」を判断する材料にならない**（符号が
一方は悪化、一方は改善で完全に相殺方向）。`decision_id`の永続化と
`confidence_multiplier`記録がいずれも2026-08-14開始という制約により、
サンプルが構造的に少ない。

## 判断（R13-A/B既存の判断枠組みに準拠）

- **メカニズムの実在・実証は完了**（PART 1、n=58で確認）。バグは実在し、
  想定した通りの非対称性（ブースト0%発火、カット86%発火）を持つ
- **修正の収益への影響は現時点で判断不可**（PART 2、n=2は統計的に無意味）
- R13-A/R13-Bの既存基準（attributable≥90件目安）に照らし、**現時点でpaper A/B
  に進める根拠は不十分**。R13-Cでattributable銘柄数が増えるのを待ち、
  再検証が必要
- 一方、このバグ自体は「意図した仕様が動いていない」という**実装バグ**であり、
  「儲かるかどうか未知の新機能」ではない。修正自体（confidenceの意図した非対称性を
  正しく双方向に効かせる）は低リスクだが、sizing変更のため本番反映は既存の
  R0-v2安全制約（paper A/B経由、ユーザー承認）に従う

## 次のアクション

- 現時点で本番コード変更は**行わない**
- decision_id→closed trade紐付けの標本が増える（自然な時間経過、または
  R13-Cのattributable改善策）のを待ち、PART 2相当の検証をn=30程度で再実施
- もしくは修正をpaper A/B環境（発注はするが本番資本には影響しない検証環境）で
  先行運用し、shadow的にconfidence_multiplier発火頻度・qty差分を蓄積する設計も
  検討可能（R14 dip-buy/R13-D sector rotationと同様のshadow-first パターン）

## 再現方法

```bash
cd ~/stock_swing && source venv/bin/activate
python scripts/simulate_confidence_multiplier_sizing_fix.py
```

詳細データ: `detail.json`（PART 2の全行）、`sanity_mismatches.json`（空、全件一致）
