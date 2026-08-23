# R13-C 残項目（4・6・7）実装記録（2026-08-24）

**ステータス**: ✅ 実装・検証完了。本番影響なし（研究用スクリプト・モジュールのみ、
paper_demo.py / decision_engine 等の本番実行パスからは一切import されない）。

## 実装対象

| 項目 | 内容 | 実装 |
|---|---|---|
| item 4 | cash/gross exposure/sector/cluster cap の再現 | `scripts/r11_backtest_engine_v4.py`（新規） |
| item 6 | rolling walk-forward + embargo | `src/stock_swing/research/rolling_walk_forward.py`（新規） |
| item 7 | 全trial registry（過適合リスク可視化） | `src/stock_swing/research/trial_registry.py`（新規） |

item 6・7 は汎用モジュールとして`src/stock_swing/research/`配下に実装し、
今後の他スクリプト（r11b_param_search.py, r11c_candidate_backtest.py 等）からも
再利用可能にした。実際の統合例として `scripts/r13c_rolling_walk_forward_validation.py`
（新規）を作成し、v3エンジンの実トレード列に対してrolling walk-forwardを適用し、
各rollの結果をtrial registryに記録する一連の流れを実証した。

## item 4: exposure/sector/cluster cap 実装

`scripts/r11_backtest_engine_v4.py`はv3（t+1 fill + point-in-time universe +
conservative OHLC exit + slippage）をそのまま再利用し、エントリー側に3つのcapを追加：

1. **Gross exposure cap**: 全open positionの合計notionalが
   `gross_exposure_cap_pct * equity_base`を超えたら新規BUYをdrop
   （`position_sizing.py`のREGIME_LIMITS思想を移植）
2. **Sector cap**: `position_sizing.py`の実際の`SYMBOL_SECTORS`をそのままimportし、
   同一セクターのopen notionalが`sector_cap_pct * equity_base`を超えたらdrop
3. **Correlation cluster cap**: `correlation_cluster.py`の実際の
   `CLUSTERS`/`DEFAULT_CLUSTER_CAPS`をそのままimportし、同一クラスタの
   open notionalがcapを超えたらdrop

同日に複数シグナルが競合する場合はsignal_strength降順で埋める（優先度の単純化、
本番`PortfolioAllocator`の ETF/Stock リバランス優先ロジックとは異なる簡略化と明記）。

### 検証結果（実データ、69銘柄、2024-08-15〜2026-08-14）

**デフォルトcap（gross=75%, sector=55%、production `position_sizing.py`のデフォルトと同値）**:
```
v4 (caps ON):  n=621 WR=70.2% PF=1.854 net=$101,272
v3-equivalent (caps OFF): n=621 WR=70.2% PF=1.854 net=$101,272
capacity_dropped=0
```
→ **デフォルトcapは全期間通じて一度もbindしない**。この69銘柄・$10,000/tradeの
固定サイズでは、gross 75%（$750,000）/ sector 55%（$550,000）に達するほどの
同時ポジション数（75件以上）には現実的に到達しないため。

**タイトなcap（gross=30%, sector=20%、意図的に厳しくしてcapの動作自体を実証）**:
```
v4 (caps ON):  n=468 WR=69.9% PF=1.665 net=$63,271  (capacity_dropped=625: gross=617, sector:software=8)
v3-equivalent (caps OFF): n=621 WR=70.2% PF=1.854 net=$101,272
```
→ capを厳しくするとn=621→468（25%減）、PF=1.854→1.665、net=$101,272→$63,271に減少。
機会損失（見送られたトレードの多くはより良いPFだった可能性）が定量的に確認できる。
この設定は「もし本番の`position_sizing.py`のREGIME_LIMITS/max_sector_exposure_pctが
このバックテストの固定サイズ想定と同程度厳しかったら」という仮想シナリオであり、
実際の本番capが現在thisレベルで頻繁にbindしているかどうかは別途本番ログで確認が必要
（本タスクのスコープ外）。

### 限界（自己開示）
- 固定notional/trade設計を継承しているため、真の「capに合わせて部分サイズで約定」は
  未実装（drop = 完全に見送り、これは実際の挙動より**保守的**、つまり過小評価方向）
- ETF/Stock 85/15配分バンド（`PortfolioAllocator`）は対象外。gross/sector/clusterの
  3種類のみ
- equity_baseは固定定数（$1,000,000等）であり、実際のmark-to-market equity curveでは
  ない

## item 6: rolling walk-forward + embargo

`src/stock_swing/research/rolling_walk_forward.py`は、`all_dates`から複数の
train/embargo/test roll を生成する`generate_rolling_splits()`と、トレード列を
roll単位で仕分ける`partition_trades_by_roll()`を提供。embargoは
`SimpleExitV2Strategy.max_hold_days=20`と同じ日数をデフォルトにし、複数日保有戦略の
train/test隣接リークを防ぐ標準的な「purged/embargoed walk-forward」の簡易版。

### 検証結果（`scripts/r13c_rolling_walk_forward_validation.py`、4 rolls）

**Point-in-time universe有効時**: 全銘柄のintro_dateが2026年（このシステムの
銘柄追跡開始日プロキシ、真の歴史的universe選定日ではない）のため、trainウィンドウが
2026年より前のrollはn=0（既知の制約、r11_symbol_universe_intro_dates.pyのドキュメント
通り）。→ `--no-point-in-time-universe`で全2年ヒストリーを使う補完ビューを追加実装。

**Point-in-time universe無効時（全2年ヒストリー、item2のsurvivorship bias補正を
一時的に外した参考ビュー）**:
```
Roll 0: train PF=1.547 (n=794) -> test PF=1.142 (n=285)  [2025-09〜2025-12]
Roll 1: train PF=1.758 (n=903) -> test PF=0.815 (n=209)  [2025-11〜2026-03] ← 悪化
Roll 2: train PF=1.581 (n=870) -> test PF=2.857 (n=451)  [2026-02〜2026-06]
Roll 3: train PF=1.607 (n=882) -> test PF=1.679 (n=565)  [2026-04〜2026-08]

SUMMARY: 3/4 rolls had test-window PF > 1.0
```
**重要な発見**: Roll 1のtest期間（2025-11-26〜2026-03-17）でPF=0.815と唯一1を
割り込んだ。この期間は、2026-08-15のR11-B付鍘レビューで単一の60/20/20分割から
発見された「validation期間の不振」（2025-10-27〜2026-03-20、SPY/QQQ調整局面）と
**ほぼ重なる**。つまり、全く異なる手法（複数rolling window、embargo付き）で
再実行しても、同じ弱点（レジーム依存の不振期間）が再現された。これは
2026-08-15レビューが単一分割点のノイズではなく、実際に頑健な弱点を捉えていた
ことの独立した裏付けとなる。

### item 7との統合実証
上記のrolling walk-forward実行を`--record-trials`付きで実施し、trial registryに
8件（4 roll × train/test）を記録。`registry.count_trials(roadmap_item="R13-C-item6")`
で総trial数を確認可能（多重比較の開示に利用）。

## テスト

- `tests/unit/test_trial_registry.py`（18件）
- `tests/unit/test_rolling_walk_forward.py`（17件）
- `tests/unit/test_r11_backtest_engine_v4.py`（7件）
- 合計42件新規、フルスイート**2168 passed / 2 skipped**（regressionなし、
  baseline 2126 + 42 = 2168で一致確認済み）

## 変更・新規ファイル
- `src/stock_swing/research/__init__.py`（新規）
- `src/stock_swing/research/trial_registry.py`（新規、item 7）
- `src/stock_swing/research/rolling_walk_forward.py`（新規、item 6）
- `scripts/r11_backtest_engine_v4.py`（新規、item 4）
- `scripts/r13c_rolling_walk_forward_validation.py`（新規、item 6+7の統合実証）
- `tests/unit/test_trial_registry.py`（新規）
- `tests/unit/test_rolling_walk_forward.py`（新規）
- `tests/unit/test_r11_backtest_engine_v4.py`（新規）
- `data/research/trial_registry.jsonl`（新規、実行により生成されたtrial記録）
- `reports/r11_backtest_v4_results.json`（新規、実行結果）

## 次のアクション
- R13-Cは項目1・2・3・4・5・6・7すべて完了。R13-C全体をCOMPLETEとしてロードマップに
  反映
- rolling walk-forwardで再確認された「2025-11〜2026-03のレジーム依存不振」は、
  既存の09-10 Pre-Launch Gate Reviewの「レジーム依存性確認項目」（2026-08-15追加済み）
  にこの独立検証結果を追記する価値がある
- paper A/Bへの反映は引き続き見送り（R13全体の「やらないこと」方針を継承）
