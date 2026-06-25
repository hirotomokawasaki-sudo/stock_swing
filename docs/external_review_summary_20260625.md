# stock_swing 改善計画 外部レビュー用サマリー
**作成日**: 2026-06-25  
**目的**: 実装済み改善の効果検証 + 未実施計画の優先度・妥当性評価

---

## 1. システム概要

### 何をするシステムか
- **ペーパートレード自動化システム**（Alpaca 紙取引 API 使用）
- 米国株・半導体 ETF を対象としたスイングトレード（保有期間 数日〜数週間）
- AI（GPT-5.4 / Claude Sonnet）が買い・売りの判断を行う
- 対象銘柄：44 銘柄（NVDA, MRVL, DELL, CRDO, AMAT など株式 + SOXX, SMH, SOXQ などの半導体 ETF）

### 実行スケジュール
| cron ジョブ | 時刻 | 目的 |
|---|---|---|
| paper_demo_premarket | 9:25 ET (平日) | 寄り前判断 |
| paper_demo_market_open | 9:35 ET (平日) | 寄り付き判断 |
| paper_demo_midday | 12:00 ET (平日) | 昼の判断 |
| paper_demo_market_close | 15:55 ET (平日) | 引け前判断 |
| reconcile_orders_market_hours | 10:00〜15:45 ET 15分毎 | 約定同期 |
| reconcile_orders_market_open | 9:30, 9:45 ET | 寄り後約定同期 |
| daily_audit | 6:00 JST | integrity 監査 |
| daily_report_morning | 9:00 JST (火〜土) | 日次レポート |
| news_collection | 4時間毎 | ニュース収集 |
| update_price_overrides | 22:00 JST | 価格補正更新 |
| update_benchmark_spy | 8:30 JST (火〜土) | SPY ベンチマーク更新 |
| weekly_full_audit | 7:00 JST (月) | 週次完全監査 |

全 12 ジョブ、全 `consecutiveErrors=0`（2026-06-25 現在すべて正常稼働）

---

## 2. 現在のパフォーマンス指標

### 運用概要（2026-05-12 開始〜2026-06-25）

| 指標 | 値 |
|---|---|
| 初期元本 | $1,000,000 |
| 現在 equity（確定分） | $1,028,250 |
| 未確定含み益 | +$60,150 |
| 推定総資産 | ~$1,088,400（+8.8%） |
| 確定実現 PnL | +$25,578 |
| 総トレード数 | 195 closed / 17 open |
| 勝率 | 50.8%（99W / 95L） |
| Profit Factor（全体） | **1.180** |
| 平均勝ちトレード | +$1,696 |
| 平均負けトレード | -$1,498 |
| Risk/Reward | 1.13 |

### 月次 PnL

| 月 | 実現 PnL |
|---|---|
| 2026-05 | **-$22,510** |
| 2026-06 | **+$48,087** |

### 資産クラス別成績

| 区分 | トレード数 | 実現 PnL | Profit Factor | 勝率 |
|---|---|---|---|---|
| ETF（半導体系） | 72 | +$48,733 | **2.270** | 62% |
| 個別株 | 123 | -$23,156 | **0.777** | 44% |

→ **ETF が利益の全てを稼いでおり、個別株はマイナス**

### ⚠️ 重要な観察：保有期間別成績

| 保有期間 | トレード数 | 平均 PnL | 勝率 |
|---|---|---|---|
| < 1日 | 84 | **-$363** | 43% |
| 1〜3日 | 6 | **-$620** | 50% |
| 3〜7日 | 40 | **-$1,799** | 15% |
| 7〜14日 | 28 | **+$988** | 71% |
| > 14日 | 37 | **+$2,813** | 92% |

→ **短期クローズほど損失、長期保有ほど利益**。7日以上保有すれば 71%+ 勝率。

### シンボル別 PnL（上位 / 下位）

**上位**
| Symbol | 実現 PnL | トレード数 |
|---|---|---|
| ANET | +$10,928 | 2 |
| CRDO | +$8,175 | 5 |
| CHPX | +$7,825 | 2 |
| CHPS | +$6,663 | 2 |
| QTEC | +$6,587 | 1 |

**下位**
| Symbol | 実現 PnL | トレード数 |
|---|---|---|
| IBM | -$8,394 | 2 |
| ORCL | -$8,306 | 3 |
| SHOC | -$6,213 | 6 |
| HPQ | -$4,768 | 2 |
| FICO | -$4,705 | 4 |

### Exit Reason 分布

| exit_reason | 件数 | 割合 |
|---|---|---|
| broker_fill | 195 | **100%** |

→ **Exit 戦略シグナル（breakeven stop / trailing stop）が一度も発火していない**  
→ 全クローズはブローカー主導（手動的な sell 注文の約定）

### 現在のオープンポジション（17件）

| Symbol | Qty | Entry Price | Peak Price |
|---|---|---|---|
| AMAT | 94 | $495.44 | $640.18 |
| ANET | 287 | $151.99 | $174.62 |
| ASML | 32 | $1,767.27 | $1,951.09 |
| CDNS | 128 | $390.71 | $389.50 |
| CRDO | 85 | $269.65 | $282.60 |
| DDOG | 172 | $227.41 | $233.22 |
| DELL | 73 | $379.29 | $434.27 |
| HPE | 618 | $47.93 | $49.55 |
| INTC（×2） | 234+235 | $131.71 / $135.49 | - |
| KLAC | 132 | $244.03 | $244.54 |
| LRCX（×2） | 133+88 | $325.28 / $370.34 | - |
| MU（×2） | 32+26 | $917.12 / $1,074.49 | - |
| NBIS（×2） | 100+89 | $218.86 / $277.68 | - |

---

## 3. アーキテクチャ概要

### ソースコード構成
```
src/stock_swing/
  cli/           paper_demo.py, reconcile_orders.py, daily_report.py
  strategy_engine/ simple_exit_v2_strategy.py, breakout_momentum*.py
  decision_engine/ メインの買い判断エンジン（AI呼び出し）
  risk/           position_sizing.py, correlation_cluster.py, risk_budget.py
  tracking/       pnl_tracker.py, trade_event_store.py
  analytics/      strategy_attribution.py, exit_replay.py
  experiments/    ExperimentContext, BucketAssigner, FeatureSnapshotStore（P6新規）
  guardrails/     GuardrailEngine, CircuitBreakerStore（P9新規）
  ...
```

### データフロー
```
Massive API (bar data) → feature_engine → decision_engine (AI) → paper_demo
                                                                       ↓
Alpaca API ←─────────────────── paper_executor (order submission)
      ↓
reconcile_orders → pnl_tracker (tracking)
      ↓
daily_audit / console
```

---

## 4. 実装済み改善フェーズ（P0〜P9）

### ✅ P0: 基礎ガードレール（2026-05-28）
- ETF buy ガードレール（後に解除 → 実測 PF=2.776 確認後 `PAPER_DEMO_ALLOW_ETF_BUYS=true`）
- Exit quality 改善（peak_price 永続化、breakeven stop）
- Risk budget ガードレール（warn 5% / block 8%）

### ✅ P1: Analytics Batch 1（2026-05-28）
- `strategy_attribution.py`：ETF/Stock 別 PF 分析
- `data_quality_audit.py`：signal_strength 欠損検出
- `risk_budget.py`：ポジションサイズ予算管理
- `exit_replay.py`：7 種類 exit ポリシー比較

### ✅ P2: Console Fetch Stability（2026-05-28）
- アトミック JSON 書き込み、TTL キャッシュ、ThreadingHTTPServer
- 監視コンソールの安定化

### ✅ P3: Exit 戦略強化（2026-05-27）
- Breakeven stop：peak +3% 到達後に return ≤0% で売却
- peak_price 永続化：セッション間でトレイリングが継続
- Entry 強度連動 exit 閾値（高/標準/低確信で stop を動的変更）
- exit_reason 追跡 (`pending_exit_reasons.json`)

**⚠️ 実績**: 実装後も exit_reason は全件 `broker_fill` → シグナルが実際には発火していない

### ✅ P4: リスク高度化（2026-06-23）
- Walk-Forward Exit Validation
- Correlation Cluster Risk Cap（同一クラスタ内で集中リスクを制限）
- Structured Console Summary
- Staged AI Context Packs（minimal/normal/expanded/emergency）

### ✅ P5: CI ガードレール + Signal Strength 計測基盤（2026-06-23）
- `secret_scan.py`：CI 用シークレットスキャン
- `entry_signal_strength` を trade レコードに保存開始

**⚠️ 現状**: `strategy_id` が全件 `broker_reconstructed`、`entry_signal_strength` の実績データはまだ蓄積中

### ✅ P6: 実験管理基盤（2026-06-25 本日）
- ExperimentContext + ExperimentRegistry（全決定に実験 ID・config_hash・git commit を付与）
- PromptRegistry（プロンプト SHA-256 追跡）
- FeatureSnapshotStore（AI 判断前特徴量の不変保存）
- BucketAssigner（A/B バケット安定割り当て、80/20 split）
- Experiment Performance Reporter

**統合状況**: モジュールは完成しているが、paper_demo への実際の呼び出しは未接続

### ✅ P7（→ P9 として実装）: 自律停止ガード（2026-06-25 本日）

*注: 計画ドキュメントの番号と対応 — 実装は P9 として完了*

- GuardrailEngine（YAML ルール → GuardAction: allow/reduce_size/block_buys/ai_pause/halt）
- CircuitBreakerStore（halt 状態を JSON で永続化、手動リセットに note 必須）
- pre_trade_check.py（startup/AI前/buy前/run後 の 4ポイントでガード）
- build_flatten_plan（緊急フラット化プラン生成）

**統合状況**: モジュールは完成しているが、paper_demo への実際の呼び出しは未接続

---

## 5. 未実施改善フェーズ

### 🔲 P7: 反実仮想検証 + Exit 戦略高度化（T26）
**背景**: 保有期間分析より「3〜7日クローズが最悪（avg -$1,799, WR 15%）」という明確なパターンあり

| サブタスク | 内容 |
|---|---|
| P7-A | 反実仮想検証：短期クローズ負けトレードを仮保有した場合の推計損益 |
| P7-B | 連続確認ウィンドウ（N 日連続 stop 割れでカット） |
| P7-C | MA20 割り込み確認（MA20 割れ + return<-5% + 2 日継続） |
| P7-D | A+B 組み合わせ条件を SimpleExitV2Strategy に統合 |
| P7-E | ATR ベース動的ストップ（ボラ適応） |

**依存**: P5-B の `entry_signal_strength` 実績データが一定量蓄積後

### 🔲 P8: シグナル強度の粒度化（S2〜S4）
**背景**: BUY シグナルの 73% が strength=1.0、閾値 0.85 が 86% を包含し識別力がない

| サブタスク | 内容 |
|---|---|
| P8-A | S2: breakout_momentum で一律 1.0 になる原因を修正（momentum/volatility/confirmation 組み込み） |
| P8-B | S3: 動的 cap 閾値 0.85 の識別力を実績データで検証 |
| P8-C | S4: strength 分布別 勝率・PF 計測 |

### 🔲 P10: ニュース感情フィーチャー（T25-feature）
| ステップ | 内容 |
|---|---|
| Step 1 | `analyze_news_impact.py` で n≥30 / \|r\|>0.3 を確認（前提: データ蓄積中） |
| Step 2 | ETF_SECTOR_MAP 追加（構成株 weighted 平均でセンチメント近似） |
| Step 3 | `news_sentiment_feature.py` 実装 + paper_demo 組み込み |

### 🔲 P11: Analytics Batch 2 + 高度可視化
| サブタスク | 内容 |
|---|---|
| P11-A | Entry Quality Scoring（buy 候補品質スコア） |
| P11-B | ETF Strategy Separation（ETF 専用戦略・独立メトリクス） |
| P11-C | Paper Trade Audit Trail（全 buy/sell/deny を外部監査可能な形式で記録） |
| P11-D | Backtest vs Paper Drift Monitor（ライブ乖離検出） |
| P11-E | Capital Heatmap |
| P11-F | Promotion Gate（ペーパーデモ卒業基準の定義） |

### 🔲 P12: Massive WebSocket リアルタイム配信
- intraday exit signal にリアルタイム価格を使用
- コンソールの live price 表示

### 🔲 P13: ML シグナル分類器（長期）
- XGBoost でシグナル品質予測（1000 件以上のデータが必要）
- Regime-adaptive 戦略

### 🔲 P16: Console Stability 完成（旧 P6）
- CF-2: frontend stable fetch wrapper
- CF-3: ポーリング間隔最適化
- Risk Budget deny ロジックの paper_demo 組み込み
- SPY Benchmark 自動更新

### 🔲 P17: Corporate Action 対応（旧 P9）
- Stock split 発生時の price/qty/audit 一貫処理（KLAC 10-for-1 split を経験済み）

---

## 6. 既知の問題・課題

### 🔴 Exit 戦略が機能していない（最重要）
- breakeven stop / trailing stop を実装済みだが、全 195 件が `exit_reason=broker_fill`
- システムが sell を出しているが exit_reason が記録されない可能性 OR 実際に exit signal が発火していない
- **結果**: exit 戦略の評価ができない状態

### 🔴 個別株 PF = 0.777（マイナス期待値）
- ETF が全利益を稼いでおり、個別株はマイナス
- ただし以前の測定（誤データ時）は逆だったため、要再測定

### 🟡 短期クローズが損失の主因の可能性
- < 3日 クローズ: WR 43〜50%、avg -$363〜-$620
- > 7日 保有: WR 71〜92%、avg +$988〜+$2,813
- 「短期カットが損失の原因」か「生存バイアス」かは未検証

### 🟡 Strategy ID が全件 `broker_reconstructed`
- entry_strategy / signal_strength が trade レコードに正しく記録されていない可能性
- P5-B で保存開始したが、実績として確認できていない

### 🟡 P6/P9 モジュールの paper_demo 統合未完
- ExperimentContext / GuardrailEngine は実装済みだが、実際の paper_demo ループへの呼び出しがない
- 実験追跡・ガードレール発動が実際には機能していない

### 🟡 CircuitBreaker の halt 条件 YAML 要チューニング
- `stale_price_event_count >= 3` → block_buys
- `broker_tracker_mismatch_count >= 1` → halt
- `daily_realized_loss_pct <= -2.0%` → block_buys
- これらの閾値は実績データなしで設定されており、実際の運用に合っているか未検証

---

## 7. テスト状況

| カテゴリ | 状態 |
|---|---|
| unit tests 全体 | 475 passed / 1 failed（既知） |
| 既知の失敗 | `test_runtime.py::test_read_runtime_mode`（runtime が paper モードなのに research を期待） |
| P6 新規テスト | 14 passed |
| P9 新規テスト | 21 passed |
| P1-P5 新規テスト | ~80+ passed |

---

## 8. 外部 AI へのレビュー依頼事項

以下の観点で評価・提案をいただけると助かります：

### A. 効果検証
1. **P3 の Exit 戦略強化**は実際に機能しているか？（全件 broker_fill の問題）
2. **ETF PF=2.270 / 個別株 PF=0.777** という現状に対して、改善の優先順位をどう見るか？
3. **保有期間別の勝率格差**（短期: -$363 avg vs 長期: +$2,813 avg）をどう解釈すべきか？

### B. 優先度評価
4. P7（Exit 高度化）vs P8（Signal Strength 粒度化）vs P16（Console Stability）の優先順位
5. P6/P9 モジュールの paper_demo 統合（次に実施すべきか？）
6. P11-F の「Promotion Gate（ペーパーデモ卒業基準）」の基準として何が適切か？

### C. 計画の妥当性
7. 現在の改善計画に抜け漏れはあるか？
8. 「exit reason が全件 broker_fill」に対する推奨対処法
9. 個別株の PF 改善に最も効果的と思われるアプローチ

---

## 9. ファイル・コード参照先

| 目的 | パス |
|---|---|
| 全体改善計画 | `docs/console_improvement_tasks.md` |
| Exit 戦略 | `src/stock_swing/strategy_engine/simple_exit_v2_strategy.py` |
| paper_demo メインループ | `src/stock_swing/cli/paper_demo.py` |
| PnL トラッカー | `src/stock_swing/tracking/pnl_tracker.py` |
| Guardrail ルール定義 | `config/guardrails/autonomous_stop.yaml` |
| Guardrail エンジン | `src/stock_swing/guardrails/rule_engine.py` |
| 実験管理 | `src/stock_swing/experiments/` |
| A/B バケット設定 | `config/experiments/ab_buckets.yaml` |
| AI ランタイム設定 | `config/ai/ai_runtime.yaml` |
| 日次ログ（最新） | `docs/daily_logs/2026-06-25.md` |
| トレードデータ（JSON） | `data/tracking/pnl_state.json`（212 trade エントリ） |

---

*このファイルは 2026-06-25 09:59 JST 時点の情報に基づいています。*
