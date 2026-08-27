# R13-D: 新headline設定の選定・walk-forward検証（2026-08-27）

## 背景

08-26のmin_members修正で旧headline（top_n=2, lookback=63d, hold=21d）が
MIXED判定に転落したことを受け、`docs/r13d_min_members_check_20260826/README.md`
は「top_n=1 または lookback=126dへの変更」を候補として挙げ、「後付けの良い
数値選びにならないよう選定根拠の明文化が必要」と明記していた。

**重要な過去の教訓（08-26発見）**: 「単一のheadline設定のみに依存したGO判定は
実装バグ1つで容易に覆りうる」——そのためパラメータ感度チェックは「バグ修正後も
同じ傾向か」の2段階目まで検証すべき、という結論だった。旧headlineの
robustness_checks.md（08-23作成）にはwalk-forward split（period1/period2）
検証があったが、これは**旧（バグ入り）headline設定に対してのみ**実施されており、
min_members修正後の新候補2つには一度も適用されていなかった。

## 実施内容

新規`scripts/r13d_new_headline_selection.py`で、min_members修正込みの
`run_rotation()`（`r13d_etf_sector_rotation_phase1.py`をimport、重複実装なし）
を使い、以下2候補を full-period + walk-forward（period1/period2、08-23と
同じ日付境界）の3段階で検証:

- **候補A**: top_n=1, lookback=63d, hold=21d
- **候補B**: top_n=2, lookback=126d, hold=21d

## 結果

| 候補 | Full Period | Period1 (2024-11〜2025-09) | Period2 (2025-10〜2026-08) |
|---|---|---|---|
| A (top_n=1, 63d) | GO (Sharpe 1.473 vs EW 1.255 / SPY 0.967) | **MIXED** (Sharpe 0.889 vs EW 0.991 / SPY 0.724 — equal-weightベースラインに負ける) | GO (1.900 vs 1.532 / 1.383) |
| **B (top_n=2, 126d)** | **GO** (Sharpe 1.415 vs EW 1.205 / SPY 0.990) | **GO** (0.985 vs 0.806 / 0.725) | **GO** (1.674 vs 1.532 / 1.383) |

## 結論・推奨

**候補Bを新headlineとして採用推奨**。理由:

1. 候補Aはfull-periodではより高いSharpe（1.473）を示すが、**period1単独では
   equal-weightベースラインに負ける（MIXED）**——08-26に発見した「単一
   headline依存の脆弱性」パターンが候補Aにも部分的に存在することを示す
2. 候補Bはfull-period・period1・period2の**3段階すべてでGO判定**——旧
   headline（08-23検証時点）が満たしていた頑健性基準を、min_members修正後の
   設定の中で唯一満たす
3. 選定根拠: 「単一のETFノイズを最も安定して除去する」という当初の代替案
   （top_n=1）ではなく、「より長いlookback（126日）でシグナルのノイズを
   平滑化する」アプローチが、時間分割に対してより頑健であることが実データで
   示された

## 次のアクション

- 09-08のR13-D本番配線判断レビューで、**候補B（top_n=2, lookback=126d,
  hold=21d, --enforce-min-members）を新headline**として正式採用するかを決定
- 本節はPhase1研究のみ（本番未配線コードへの影響なし）。テストスイート
  `pytest -k r13d`: 10 passed（regressionなし）

## 再現方法

```bash
cd ~/stock_swing && source venv/bin/activate
python scripts/r13d_new_headline_selection.py --save
```

生データ: `reports/r13d_new_headline_selection_results.json`
