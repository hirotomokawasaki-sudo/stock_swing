# Claude向け独立検証プロンプト

あなたは、アルゴリズム取引・バックテスト設計・統計検証・運用統制をレビューする
独立監査者です。このパケットを作成したレビュー担当者の結論は、正しいとも誤りとも
仮定しないでください。

## 目的

2026-08-23の戦略レビューについて、次を判定してください。

1. 各主張はコード・データから再現できるか。
2. 表現が証拠より強すぎないか。
3. 反対解釈や代替仮説があるか。
4. 提案された修正は、コスト・回帰リスクに見合う価値があるか。
5. 実資金昇格条件は妥当か。任意の政策値を客観的必須条件と混同していないか。

## 最初に行うこと

```bash
python reproduce_review_metrics.py
sh verify_bundle.sh
```

次に、`CLAIMS_MATRIX.md`、`IMPLEMENTATION_VALUE.md`、`SOURCES.md`、
`source_files/`を確認してください。数値は`evidence/review_metrics.json`だけでなく、
匿名化取引スナップショットから再計算してください。

## 必須の検証観点

- R11のsignal timestampとentry fill timestampにlook-aheadまたは実行不能な同値約定がないか。
- MOC等により同日close約定が正当化できる反証可能性。
- 現在の銘柄集合を過去全期間に使うことによるselection/survivorship bias。
- train、validation、holdoutの不安定性を「レジーム依存のedge」と呼べる証拠の強さ。
- attributableの定義が妥当か。49件と110件の母集団差。
- IID bootstrapの限界。必要ならblock bootstrapやsymbol-cluster法を提案。
- signal_strengthと実績の単調性、およびstop幅・trailing・sizingへの接続の妥当性。
- promotion PFが全closed tradesを使う設計意図と、現行戦略昇格目的との整合性。
- top5 concentrationの分母と40%閾値の意味。
- dry-run、scheduled paper run、generic daily snapshotが同じ運用証拠として混在していないか。
- 提案した100件、20bp、90%下限、DD 5%、20 runが適切な政策値か。

## 各claimの判定形式

各claimを次のいずれかで判定してください。

- `SUPPORTED`
- `PARTIALLY_SUPPORTED`
- `NOT_SUPPORTED`
- `NOT_TESTABLE_WITH_PACKET`

各判定には以下を添えてください。

- 参照ファイルと行
- 再計算値
- 最も強い反証または代替解釈
- 結論を変える追加証拠

## 実装価値の評価形式

各改善案を次の軸で1～5点評価してください。

- risk reduction
- evidence quality improvement
- expected performance benefit
- implementation effort
- regression/operational risk

そして`IMPLEMENT_NOW / PAPER_AB_FIRST / DEFER / REJECT`を付けてください。

## 禁止事項

- 元レビューを要約するだけで終えない。
- 学術的にmomentum premiumが存在することを、現行20-bar実装の有効性の証明にしない。
- FINRA/SEC資料をこの個人運用への直接の法的義務と断定しない。
- PF>1だけで統計的edge確定としない。
- この依頼ではコードや設定を変更しない。

## 最終成果物

1. Executive verdict
2. Claim-by-claim verdict table
3. 数値再現結果と差異
4. 元レビューの過大評価・過小評価
5. 実装価値ランキング
6. 修正版の最小改善計画
7. 実資金移行を許可・延期する条件

