# reduce_size 設計見直し案の検証（案B / 案C+A、2026-09-01）

**最終結論（2026-09-01、ユーザー判断）**: **見送り**。現行メカニズムを維持する。
余剰資金は reduce_size 自体の再設計ではなく、別戦略（余資活用の新規戦略検討）で
活かす方向性とする。以下は判断に至った検証の全記録。

## 背景

2026-09-01、ユーザーから「degraded状態で買いが止まり現金が長期間遊んでいるのは
機会損失ではないか」との問いを受けた。既存の調査（08-15/08-26、
`docs/r0v2_reduce_size_portfolio_level_20260826/README.md`）で判明していた
「reduce_sizeはポートフォリオ露出上限を丸ごと半減させる二値的ブロック機構」
という事実を踏まえ、4つの設計代替案を提示し、ユーザー承認を得て段階的に検証した:

- **案B**: 露出上限には一切触れず、新規注文1件あたりのサイズ（final_shares）を
  半減する
- **案C+A**: 連敗数に応じた段階的な上限縮小 ＋ 既存保有がどれだけ埋まっていても
  最低限の新規余地を必ず確保するフロア
- **B+Cブレンド**: 露出上限には触れず、per-order縮小率を連敗数で段階化

## Part 1: 案B・案C+A（v1）の全期間検証

`scripts/r0v2_reduce_size_design_alternatives_20260901.py`。08-26スクリプトと
全く同じR11-Bユニバース（69銘柄）・戦略・**本番と同一クラスのPositionSizingPolicy**
を使用し、baseline / current_mechanism / plan_b / plan_c_plus_a(v1) を単一
シミュレーションコード内で実行。baseline・current_mechanismの結果が08-26の
保存済み結果と完全一致することを確認済み（基盤の整合性確認）。

**結果（全期間、単一の連続2年間）**:

| metric | baseline | current_mechanism | plan_b | plan_c_plus_a_v1 |
|---|---|---|---|---|
| profit_factor | 1.4325 | 1.497 | **1.5093** | 1.4745 |
| net_pnl | $441,346 | $482,405 | **$488,775** | $472,190 |
| 完全ブロック日数（63日中） | — | 13 | **0** | 0 |
| ブロック率（reduce_size中） | — | 52.1% | **0%** | 20.6% |

この時点では案Bが全指標で現行を上回り、案C+A(v1)はブロック率緩和には成功した
ものの現行よりPFが悪化していた（mildティア0.75xが緩すぎたと推定）。

## Part 2: C+Aチューニング + B+Cブレンドの追加検証

`scripts/r0v2_reduce_size_design_alternatives_v2_20260901.py`。10メカニズムを
比較（tier閾値・乗数・floor幅を振った5種のC+Aバリエーション + B+Cブレンド2種）。

**主要な結果**:

| メカニズム | overall PF | net_pnl | 完全ブロック日数 |
|---|---|---|---|
| 現行メカニズム | 1.497 | $482,405 | 13 |
| plan_b_flat | 1.5093 | $488,775 | 0 |
| **plan_c_plus_a_v2_strict_mild**（0.5/0.35/0.15 + floor3%） | **1.5372** | **$508,292** | 0 |
| plan_bc_blend_v1（per-order段階化） | 1.4928 | $476,997 | 1 |

v2（mildティアを現行と同じ厳しさ0.5xに戻し、moderate/severeをさらに厳格化）が
全期間合算では最良の結果となった。仮説（v1のmildティアが緩すぎたことがPF悪化の
原因）はv4（floorなしバージョン）との比較で追加裏付けを得た。

## Part 3: train/validation/holdout頑健性チェック（過学習検証）

ユーザーから「狭い探索がこの特定期間への過学習ではないか」との指摘を受け、
`scripts/r0v2_reduce_size_segment_robustness_20260901.py`で、既存の
`scripts/r11b_param_search.py`が確立した同一の train(60%)/validation(20%)/
holdout(20%)日付分割（train: 2024-08-15〜2025-10-24 / validation:
2025-10-27〜2026-03-20 / holdout: 2026-03-23〜2026-08-14）で各メカニズムの
トレードを分割・再集計した。

**決定的な結果**:

| メカニズム | train PF | **validation PF** | holdout PF | overall PF |
|---|---|---|---|---|
| 現行メカニズム | 1.4938 | **0.6455** | 2.3716 | 1.497 |
| plan_b_flat | 1.548 | 0.6169 | 2.3864 | 1.5093 |
| plan_c_plus_a_v2_strict_mild | 1.5587 | 0.6406 | 2.3807 | 1.5372 |
| plan_c_plus_a_v1_original | 1.5122 | 0.6131 | 2.2707 | 1.4745 |
| plan_c_plus_a_v4_no_floor | 1.5031 | 0.6306 | 2.2972 | 1.4801 |
| plan_bc_blend_v1 | 1.5333 | 0.6126 | 2.3556 | 1.4928 |

**validation期間（実際の市場調整局面として既知）だけを見ると、現行メカニズムが
全候補中で最も高いPF（0.6455）**。全期間合算で「圧勝」に見えたplan_c_plus_a_v2も
validationでは僅差ながら現行を下回る（0.6406 < 0.6455）。

**頑健性判定**（validation・holdout両方で現行以上のPFを要求する厳格な基準）:
```
plan_b_flat                        -> PARTIAL（holdoutのみ勝ち）
plan_c_plus_a_v1_original          -> NOT ROBUST
plan_c_plus_a_v2_strict_mild       -> PARTIAL（holdoutのみ勝ち、validationは僅差負け）
plan_c_plus_a_v4_no_floor          -> NOT ROBUST
plan_bc_blend_v1                   -> NOT ROBUST
```

**全候補が「両セグメント独立で現行を上回る」という基準をクリアできなかった。**

## 最終解釈

Part 2で最良に見えたplan_c_plus_a_v2の優位性は、train期間とholdout期間
（いずれも相対的に容易な相場環境）に引っ張られた見かけ上のものであり、
**実際に防御が必要な調整局面（validation）では、現行の「連敗5回で露出上限を
丸ごと半減する」という一見過剰に見える保守的な仕組みが、むしろ最も機能していた**。
これは当初の仮説（「reduce_sizeは強すぎるのでは」）とは逆方向の結果であり、
「防御的な仕組みは、まさに防御が必要な局面でこそコストに見合う」という構造的な
洞察が得られた。ただし差は僅差（0.6406 vs 0.6455）かつサンプル数も少なめ
（n=201〜212）であり、「現行が優れている」と断定するほどの統計的有意性でもない
——「明確な改善案は見つからなかった」というのが正直な結論。

## ユーザー判断（2026-09-01）

**見送り**。reduce_sizeメカニズム自体は変更しない。現金が一時的に投資されない
状態が生じることは許容し、**余剰資金の活用は reduce_size の再設計ではなく、
別の新規戦略（既存ポジションと独立した資本配分先）を検討する方向で対応する**。

## 制限事項（正直な開示）

- `BASE_EXPOSURE_CAP`は静的0.68を使用（本番の`dynamic_exposure_cap`はsignal強度
  に応じたボーナスで0.68〜0.88まで変動するが、簡略化のため省略）
- sector_exposure_cap・correlation cluster cap・PortfolioAllocatorの
  allocation_band等、他の同時制約は本検証に含まれない（exposure cap機構のみを
  単離して測定）
- validation/holdoutのセグメントサンプル数（n=201〜305）は統計的に十分とは
  言えず、僅差の優劣判定には限界がある
- 全ての探索は同一の2年間・同一の69銘柄ユニバースに限定される。異なる市場
  レジーム・銘柄セットでの頑健性は未検証
- Part 2で探索したtier閾値・乗数・floor幅の組み合わせは網羅的なグリッド
  サーチではなく、狭い範囲（9パターン）の探索に留まる

## 本番コードへの影響

**なし**。`src/stock_swing/`配下の本番コードは今回の検証を通じて一切変更して
いない。全て`scripts/`配下の新規検証スクリプト3本と本ドキュメントのみ。

## 再現方法

```bash
cd ~/stock_swing && source venv/bin/activate
python scripts/r0v2_reduce_size_design_alternatives_20260901.py --save        # Part 1
python scripts/r0v2_reduce_size_design_alternatives_v2_20260901.py --save     # Part 2
python scripts/r0v2_reduce_size_segment_robustness_20260901.py --save         # Part 3
```

生データ: `results.json`（Part 1）/ `results_v2_tuning.json`（Part 2）/
`results_v3_segment_robustness.json`（Part 3）
