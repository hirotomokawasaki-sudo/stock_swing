# Claims Matrix

## C01 — 現在のforward/paper edgeは未確定

- 種別: データ上の事実＋推論
- 元主張: attributable 49件はPF 1.082だが不確実性が大きく、実資金edgeの証明には弱い。
- 証拠:
  - `evidence/review_metrics.json`
  - attributable: n=49、PF、expectancy
  - IID bootstrap 20,000回
  - leave-one-symbol-out
- 強い反証:
  - PFの信頼区間だけでなく、事前分布や階層モデルを使えば別の結論になり得る。
  - 個別trade IID bootstrapは依存構造を無視する。
- 支持条件:
  - 再計算が一致し、下側区間が1未満、かつ銘柄除外でPF<1となる。
- 反証条件:
  - 別の妥当なattribution定義で十分な件数と頑健な正のexpectancyが確認される。

## C02 — R11には同日終値の時系列バイアスがある

- 種別: コード上の事実＋実行可能性に関する推論
- 元主張: 当日closeを含むwindowでsignalを計算し、同じcloseをentry価格にしている。
- 証拠:
  - `source_files/scripts/r11_backtest_engine.py` 199–220行、269–290行
- 留保:
  - MOC注文をclose確定前に出せる戦略なら「同日close」自体は必ずしも不可能ではない。
  - ただし最終closeをsignal入力にした後で、その同じcloseに約定するのは時系列上説明が必要。
- 支持条件:
  - signal生成に確定closeが必要で、注文送信はその後になる。
- 反証条件:
  - productionとbacktestの双方で、close確定前に利用可能な情報だけを使うMOCロジックが証明される。

## C03 — R11の銘柄集合にはselection/survivorship biasの可能性がある

- 種別: 設計上の事実＋推論
- 元主張: 現在の銘柄集合を過去全期間に適用しているため、point-in-time universeではない。
- 証拠:
  - `source_files/scripts/r11_backtest_engine.py`
  - `source_files/docs/console_improvement_tasks.md` R11記述
- 強い反証:
  - 69銘柄が研究前に固定され、delisted/failed企業を含むルールベース集合だった可能性。
- 支持条件:
  - universeの構成日・構成規則がbacktest期間後に決まり、過去時点の構成履歴がない。
- 反証条件:
  - 研究前に固定したpoint-in-time inclusion/exclusion記録が提示される。

## C04 — R11の「edgeあり確認」は表現が強すぎる

- 種別: データ上の事実＋解釈
- 元主張: train PF 1.7755に対しvalidation PF 0.560、全16点survivor 0なので、
  「edge確認済み」より「仮説支持」に留めるべき。
- 証拠:
  - `evidence/r11b_param_search_results.json`
  - `source_files/docs/console_improvement_tasks.md` R11-B記述
- 強い反証:
  - holdoutが良好なら、validation不振はレジーム条件付きedgeの証拠になり得る。
  - ただしレジーム定義がvalidationを見た後の説明ならpost-hocである。
- 支持条件:
  - validationで全候補PF<1、事前定義されたregime gatingも未成功。
- 反証条件:
  - 事前登録された別期間rolling walk-forwardで一貫した正の結果が得られる。

## C05 — “breakout”という名称と実装契約が一致していない

- 種別: コード上の事実
- 元主張: 実装はwindow最初と最後のcloseのreturn thresholdであり、prior-high breakoutや
  volume confirmationを要求していない。
- 証拠:
  - `source_files/src/stock_swing/feature_engine/price_momentum_feature.py` 89–124行
  - `source_files/src/stock_swing/strategy_engine/breakout_momentum_strategy.py` 62–148行
  - `source_files/config/strategy/breakout_momentum_v1.yaml`
  - YAMLの`require_volume_confirmation`はsource search上、設定ファイル以外に利用箇所なし。
- 強い反証:
  - “breakout”を広義のmomentum thresholdの名称として意図している可能性。
- 支持条件:
  - volume/prior-high条件がentry pathに存在しない。
- 反証条件:
  - 別のproduction entry gateで実際に両条件を強制していることが示される。

## C06 — strategy-specific holding horizonが実装されていない

- 種別: コード・設定上の事実
- 元主張: entry metadataは2d/3d、YAMLも2/3日だが、共通SimpleExitV2の20日上限を使う。
- 証拠:
  - `source_files/config/strategy/breakout_momentum_v1.yaml`
  - `source_files/config/strategy/event_swing_v1.yaml`
  - `source_files/config/strategy/simple_exit_v2.yaml`
- 留保:
  - time_horizonがexit期限ではなく説明用metadataである設計なら、矛盾ではなく命名問題。
- 反証条件:
  - strategy ID別のexit capが別pathで適用されている。

## C07 — signal_strengthをrisk relaxationに使う根拠が弱い

- 種別: データ上の事実＋政策提案
- 元主張: scoreの実績が非単調なのに、高scoreほどstopを広げてtrailingを早めている。
- 証拠:
  - `evidence/review_metrics.json`のattributable score buckets
  - `evidence/signal_strength_decile.json`
  - `source_files/src/stock_swing/strategy_engine/simple_exit_v2_strategy.py` 304–348行
- 強い反証:
  - score別exit policy自体がoutcomeを変えるため、単純なbucket比較には内生性がある。
  - 小標本である。
- 支持条件:
  - forward較正で単調性がなく、risk relaxationの便益を示すA/Bもない。
- 反証条件:
  - preregistered paper A/Bでscore-linked exitsがuniform exitsよりCVaR/DDを改善する。

## C08 — high-confidence sizingの1.2倍は実質no-op

- 種別: コード上の事実
- 元主張: `base_final_shares`が既に全capのminで、その1.2倍を同じcapで再度clipするため増えない。
- 証拠:
  - `source_files/src/stock_swing/risk/position_sizing.py` 273–288行
- 強い反証:
  - 将来別のbase算定が入ること、またはcap以外の基準値を使う意図。
- 支持条件:
  - 任意の正の入力でconfidence>=0.8のfinalがconfidence=0.7より増えないことを単体計算で確認。
- 反証条件:
  - 現行production pathに、clip前baseとは異なる追加余力がある。

## C09 — promotion PFの母集団が現行戦略edge判定と不整合

- 種別: コード上の事実＋目的解釈
- 元主張: promotion gateは全closed 252件を渡し、現行attributable 49件に限定しない。
- 証拠:
  - `source_files/scripts/check_go_no_go.py` 279–315行
  - `evidence/review_metrics.json`
- 強い反証:
  - gateの目的が「口座全履歴の結果」であり「現行戦略の昇格」ではない可能性。
- 支持条件:
  - roadmapが現行戦略のpromotionを意図しているのに、203件のuntracked-originが支配する。
- 反証条件:
  - gate仕様が全口座履歴を意図すると明文化され、別途現行戦略gateが存在する。

## C10 — top5 concentrationの分母と閾値の意味が曖昧

- 種別: コード上の事実＋仕様解釈
- 元主張: weightはmarket_value/gross exposureで、40%と比較される。equity基準とは別物。
- 証拠:
  - `source_files/console/services/dashboard_service.py` 2219–2248行
  - `source_files/src/stock_swing/risk/promotion_gate.py` 134–160行
- 強い反証:
  - 40%が最初からgross exposureベースのtop5比率として意図された可能性。
- 支持条件:
  - 文書・他gateで40%がequity/cluster cap由来とされる。
- 反証条件:
  - gross基準として仕様・閾値根拠が明文化される。

## C11 — Go/No-Goのfreshnessはdry-runで更新できる

- 種別: コード上の事実
- 元主張: dry-run branchも共通latest console summaryへemitし、summaryにdry-run provenanceがない。
- 証拠:
  - `source_files/src/stock_swing/cli/paper_demo.py` 2150–2247行
  - `source_files/src/stock_swing/reporting/console_summary.py` 45–95行、261–313行
  - `source_files/scripts/check_go_no_go.py` 82–89行
- 強い反証:
  - run IDや外部cron metadataからdry-runを確実に識別している別path。
- 支持条件:
  - dry-run実行後に同じファイルのtimestampが更新され、freshnessがpassする。
- 反証条件:
  - scheduled non-dry summaryが別保存され、Go/No-Goがそちらだけを見る。

## C12 — cron healthは実行成功ではなくJSON parseabilityを確認している

- 種別: コード上の事実
- 元主張: `_fetch_one_job_runs()`はpayloadがdictなら成功扱いし、latest run statusを評価しない。
- 証拠:
  - `source_files/console/adapters/system_adapter.py` 541–614行
- 強い反証:
  - `openclaw cron runs`が失敗run時にcommand自体を非0終了させる仕様。
- 支持条件:
  - status=`error`を含む正常JSON payloadが`None`を返し、healthy扱いされる。
- 反証条件:
  - CLI仕様・fixtureで失敗runが必ず非0終了になることが確認される。

## C13 — 提案した昇格閾値は政策値であり、普遍的な正解ではない

- 種別: ガバナンス提案
- 対象: n>=100、20bp、bootstrap 90%下限、DD<=5%、20連続run、25% pilot。
- 根拠:
  - 誤検出と損失を保守的に抑えるための提案。
  - FINRAはlimited pilot、独立testing、monitoringを支持するが、具体的数値は指定しない。
- Claudeが検討すべき反証:
  - 取引頻度が低く100件に長期間かかる。
  - 20bpが実際のspread/impactと乖離する。
  - 5% DDが戦略volatilityに対して厳しすぎる。
- 必要な代替案:
  - risk budget、許容損失、期待取引頻度から閾値を逆算する。

## C14 — 独立戦略追加は長期的提案であり、現行edgeの証明ではない

- 種別: 改善提案
- 対象: ETF rotation、JP overnight spillover、shock mean reversion。
- 根拠:
  - 同一momentumへのfilter追加だけではalpha sourceの独立性が増えない。
- 反証:
  - 新戦略の相関、capacity、cost-adjusted edgeはまだpaperで確定していない。
- 判断:
  - リサーチ価値と実装・本番昇格価値を分けて評価する。

