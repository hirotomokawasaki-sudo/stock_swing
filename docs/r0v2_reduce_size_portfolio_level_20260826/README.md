# reduce_size実効果の再測定: ポートフォリオレベル露出上限メカニズム（2026-08-26）

## 背景

ユーザーから「今夜Circuit Breakerがdegraded（reduce_size）なだけなのに、なぜBUYが
完全にゼロになるのか、想定より強すぎないか」との質問を受け、本番コードを実際に
読んで検証したところ、2026-08-15の既存シミュレーション（`r0v2_reduce_size_
effect.py`）が**reduce_sizeの実際のメカニズムを正しく再現していなかった**ことが
判明した。

**2026-08-15の前提（誤り）**: reduce_size発動時、新規エントリー1件あたりの
ノーショナルを半分に縮小する、という前提でシミュレート。結果は「validation期間の
損失を約10%緩和、226件中24件（11%）にしか影響しない」という穏当な結論だった。

**実際の本番実装（コード確認済み）**:
```python
# paper_demo.py
_reduce_size_multiplier = 0.5 if guard_decision.action == reduce_size else 1.0
_effective_exposure_cap = dynamic_exposure_cap * _reduce_size_multiplier

# position_sizing.py PositionSizingPolicy.size()
regime_limit = inputs.exposure_cap_override  # ← この半減後の値
max_total_exposure_usd = equity * regime_limit
remaining_capacity = max_total_exposure_usd - current_total_exposure
shares_by_exposure = floor(max(remaining_capacity, 0) / price)
```

reduce_sizeは「新規注文1件のサイズを半分にする」のではなく、**ポートフォリオ全体の
露出上限を半分にする**。既存の保有ポジション合計が既にこの半減後の上限を超えて
いれば、`remaining_capacity`が0（またはマイナス→0にクリップ）になり、**新規buyが
サイズ縮小ではなく完全ブロックされる二値的な挙動**になる。

実際2026-08-26夜、`current_total_exposure=$455,632`（equityの47.3%）に対し
reduce_size適用後の上限が`$399,452`（41.5%）となり、余裕枠がゼロになって
全候補が`insufficient_remaining_exposure`でブロックされていた。

## 検証方法

新規`scripts/r0v2_reduce_size_portfolio_level_check.py`で、R11-B baseline
シミュレーションに**実際の`PositionSizingPolicy`（本番と同一クラス、import使用）**
を組み込み、ポートフォリオレベルの建玉時価総額を追跡しながら、
`consecutive_losing_trades>=5`でexposure_cap_overrideを0.68→0.34に半減する
（本番の`_reduce_size_multiplier`ロジックをそのまま再現）シミュレーションを実施。

## 結果

| | baseline（reduce_sizeなし） | reduce_size適用（ポートフォリオレベルcap半減） |
|---|---|---|
| n | 1,141 | 1,115 |
| win_rate | 56.35% | 56.86% |
| profit_factor | 1.4325 | 1.4970 |
| net_pnl | $441,345.86 | $482,405.41 |

**reduce_size発動時の実際のブロック挙動**:
- reduce_size発動日数: 63日（2年間中）
- reduce_size発動中に発生した新規buy候補: 117件
- そのうち実際にブロックされた（`final_shares<1`）: **61件（52.1%）**
- 「その日の全候補が完全ブロックされた」日: 63日中13日（約21%）

## 結論: ユーザーの直感が正しかった

**2026-08-15の「reduce_sizeは穏当な効果（11%の候補にのみ影響）」という結論は、
実際のメカニズムを正しく再現していなかったため誤りだった**。ポートフォリオ
レベルの露出上限メカニズムで正しく再測定すると、reduce_size発動中の候補の
**52.1%が完全ブロック**されており、これは「サイズの部分的縮小」ではなく
「約半数が二値的にゼロになる」という、当初の想定よりはるかに強い制約である
ことが確認された。

**PFへの影響（今回の全期間シミュレーション）**: 意外にもPFはやや改善方向
（1.4325→1.4970）。これは08-15の結論と方向性は一致する（reduce_sizeは全体としては
無害〜やや有益）が、メカニズム自体の理解（「どの程度・どのように」ブロックする
のか）は大きく異なっていた。ブロックされた61件の候補が「たまたま損失回避に
働いた」可能性が高いが、これはbaselineの資本制約なし・reduce_sizeなしのケースと
比較しているため、市場環境（強気相場が多い2年間）による偶然の可能性も否定できない。

## 実務上の含意（今夜のケースとの整合性）

今夜（2026-08-26〜27）観測された「BUYが完全にゼロ」という状況は、バグではなく
**このメカニズムの正常な（しかし直感に反する）挙動**である。ポートフォリオが
既にある程度埋まっている（47%超）状態でreduce_sizeが発動すると、新規buyは
「半分の量で続く」のではなく「完全に停止する」。これは08-24の8連敗という異常事態
への対応としては保守的すぎるとは言えないが、「reduce_size」という名前から連想
される「サイズを減らして慎重に続ける」という運用者の直感的理解とは異なる、
より強い制約であることは明示的に認識すべき。

## 推奨される次のアクション

1. `docs/console_improvement_tasks.md`のR0-v2/R9付鍘(2)セクション（2026-08-15の
   誤った前提での結論）に本検証への参照を追記し、「reduce_sizeは穏当」という
   誤解が09-15 Go/No-Go判断に持ち込まれないようにする（本レポート作成と同時に
   実施済み、下記参照）
2. reduce_sizeの実際の挙動（ポートフォリオが埋まっている時は完全ブロックに
   近くなる）を運用者向けに明文化し、「degraded状態＝穏当な減速」という誤解を
   解消する
3. 必要であれば、「完全ブロック」ではなく「一定割合は許可する」という段階的な
   設計への変更を検討（本レポートは測定のみ、設計変更は範囲外）

## 制限事項（正直な開示）

- `dynamic_exposure_cap`の本番計算（strong buy件数に応じたボーナス、0.68〜0.88の
  範囲）は簡略化し、静的な0.68のみを使用。実際の本番はシグナル強度次第でベース
  自体が変動するため、本検証の数値は近似値
- sector_exposure/cluster_capなど他の同時制約は本検証には含まれない（exposure
  capのみ単離して測定）
- 2年分の単一市場レジーム（強気相場中心）での測定であり、レジーム依存性は
  未検証

## 再現方法

```bash
cd ~/stock_swing && source venv/bin/activate
python scripts/r0v2_reduce_size_portfolio_level_check.py --save
```

生データ: `results.json`
