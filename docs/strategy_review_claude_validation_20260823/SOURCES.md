# Sources and Scope

## Local primary evidence

パケット内の`source_files/`は、Git commit
`cf6bc75a1d3cb5e8eff5e3168cf89de74f8fd774`時点を基準に固定した検証対象です。

| 対象 | 主な確認事項 |
|---|---|
| `scripts/r11_backtest_engine.py` | signal window、同日close entry、固定notional、exit path |
| `reports/r11b_param_search_results.json` | train/validation、survivor 0 |
| `price_momentum_feature.py` | momentumの実際の定義 |
| `breakout_momentum_strategy.py` | entry条件、confidence、score算出 |
| strategy YAML 3件 | unused flags、holding horizon |
| `simple_exit_v2_strategy.py` | score-linked stop/trailing |
| `position_sizing.py` | confidence multiplierとclip |
| `check_go_no_go.py` | promotion母集団、freshness、paper日数 |
| `promotion_gate.py` | PF/top5閾値 |
| `dashboard_service.py` | top5の分母 |
| `paper_demo.py` / `console_summary.py` | dry-run provenance混在 |
| `system_adapter.py` | cron run JSONの解析とstatus未評価 |
| `console_improvement_tasks.md` | “edgeあり”という計画上の結論 |

## 外部一次・権威資料

### 1. FINRA Regulatory Notice 15-09

- URL: https://www.finra.org/rules-guidance/notices/15-09
- 支持する内容:
  - algorithmic strategyのdevelopment、deployment、post-implementation monitoring
  - independent testing、data/workflow validation、test record
  - limited-size pilotから結果確認後に拡大
- 支持しない内容:
  - 25%という具体的pilotサイズ
  - 20連続run、PF、DD等の具体的昇格閾値
  - この個人運用に同Noticeが直接適用されるという法的判断

### 2. SEC Investment Adviser Marketing Rule, IA-5653

- URL: https://www.sec.gov/files/rules/final/2020/ia-5653.pdf
- 特に関連する箇所: PDF p.203–225
- 支持する内容:
  - backtested performanceはhypothetical performanceである
  - hindsightでparameter/assumptionを変更し魅力的な結果を作れる危険
  - criteria、assumptions、risks、limitations、cash-flow差等を説明する必要性
- 支持しない内容:
  - R11が必ず無価値であるという結論
  - 個人の内部研究が同広告規則の直接規制対象であるという主張

### 3. Bailey et al., Pseudo-Mathematics and Financial Charlatanism

- URL: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2308659
- 書誌: Notices of the American Mathematical Society 61(5), 2014
- 支持する内容:
  - multiple testing/backtest overfittingによりin-sample成績が誇張され得る
  - out-of-sampleで劣化する可能性
- 留保:
  - 本システムのPBOを直接計算した資料ではない

### 4. Bailey et al., The Probability of Backtest Overfitting

- URL: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
- 支持する内容:
  - strategy variantsを多数試す場合のPBO評価枠組み
- 留保:
  - 現パケットはCSCV/PBOをまだ計算していない

### 5. Jegadeesh and Titman (1993)

- URL: https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1993.tb04702.x
- 支持する内容:
  - 過去のwinnerを買いloserを売るcross-sectional momentumの実証
  - 主なformation/holding horizonは3～12か月
- 支持しない内容:
  - 現行20-bar long-only individual-stock threshold戦略のedge
  - 現行stop/trailing/sizingの妥当性

### 6. Moskowitz, Ooi and Pedersen (2012), Time Series Momentum

- URL: https://fairmodel.econ.yale.edu/ec439/mosk.pdf
- 支持する内容:
  - 58のliquid futuresで1～12か月のtime-series momentumを報告
- 支持しない内容:
  - 個別株20-bar signalの直接的証明
  - 同じexecution/cost/risk profileでの再現

### 7. Huang et al. (2020), Time Series Momentum: Is It There?

- URL: https://www.sciencedirect.com/science/article/pii/S0304405X19301953
- 役割: momentum研究の反対・限定的証拠
- 要旨上の論点:
  - asset-by-assetではTSM予測力の証拠が弱いと報告
  - pooled inferenceの信頼性を問題視
- 用途:
  - momentum文献を肯定側だけに偏らせない

### 8. Daniel and Moskowitz, Momentum Crashes

- URL: https://www.nber.org/papers/w20439
- 支持する内容:
  - momentumには稀で持続的な負のreturn列があり得る
  - market decline、高volatility、reboundとのレジーム関係
- 支持しない内容:
  - 現行validation期間の不振原因が同じmechanismだという確定
  - 現行regime filterの具体的実装

## ソース利用上のルール

1. 学術的momentum premiumは、現行strategyのimplementation proofとして扱わない。
2. 規制資料は統制設計のbenchmarkとして使い、法的適用判断と混同しない。
3. 外部資料よりローカルコード・forward dataを現行システムの一次証拠として優先する。
4. 元レビューに不利なHuang et al.やvalidation PFも同じ重みで検討する。

