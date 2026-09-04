# コストモデル定義（R18-E）— 2026-09-05

**位置づけ**: 定義と試算まで（ユーザー承認済みスコープ）。
`check_go_no_go.py` へのコード変更・Required化は**行っていない**（§5の2段階案
のとおり、Required化はユーザー承認後の別タスク）。

計測スクリプト: `scripts/analyze_execution_costs.py`（読み取り専用）
エビデンス: `docs/r18e_execution_cost_analysis_20260905/`（full_run.txt / results.json）

---

## 1. paper環境のコスト構造（現状把握、2026-09-05 コードレベル確認）

- **手数料: $0**。Alpaca paperは手数料ゼロ。かつ `pnl_state.json` のtrade
  レコードに fee / commission / slippage フィールドは存在しない（全357 closed
  trade確認）。PnL = (exit_price − entry_price) × qty のみで、**いかなる
  コスト控除も入っていない**。`check_go_no_go.py` economic_viability・各反実
  仮想スクリプトのPnLも同様（＝全て「コストゼロ世界」のPF）。
- **fillの楽観性**:
  - 全注文はmarket注文（`decision_engine.py:213 order_type="market"`、
    limit発注パスは存在しない）。Alpaca paperのfillはスプレッド/板の
    インパクトをほぼシミュレートしない。
  - さらに Alpaca paper のバー凍結問題（2026-04-22〜）対策として、
    `paper_demo.py resolve_recorded_entry_price()` は broker fill が
    sizing_price（Massive最新close）から15%超乖離すると **sizing_price を
    entry_priceとして記録**する。記録価格の一部はfillですらない参照価格。
  - 実測でも 714 leg 中 **13 leg が当日[low,high]レンジ外**
    （stale/合成価格の疑い。分布からは除外済み）。
- **fill記録の現状**: `data/tracking/fill_ledger.jsonl` は124件のみで、
  closed 357件のうち `entry_fill_id` 付与は **0件**、`exit_fill_id` は10件。
  fill台帳経由の突合は現状不可能で、実測は pnl_state の記録価格ベースに限る。

## 2. 実弾移行で追加されるコスト項目

| 項目 | 概算（米国・流動性の高い大型株/ETF、小サイズ市場注文） | 備考 |
|---|---|---|
| スプレッド/2 | 片道 1〜3 bps | market注文は必ず片側を渡る。銘柄の板厚に依存 |
| スリッページ | 片道 1〜3 bps | 小サイズなら小。ボラ時・薄い銘柄で拡大 |
| SEC fee | 売り notional の約 0.3 bps 未満 | 売りのみ。料率は年次改定 |
| FINRA TAF | 売り $0.000166/株（上限$8.30程度） | 売りのみ。実質無視できる規模 |
| 手数料 | $0（Alpaca現物）/ IBKR移行時は別途 | IBKR Pro: 約$0.005/株 等 |
| 為替（将来JP） | JPY/USD往復スプレッド+換算タイミング差 | JP拡張時に別途定義（マルチ通貨PnL課題と同根） |

## 3. cost-adjusted PF の定義式

closed trade 集合 T に対し、片道コスト **X bps** として:

```
cost(t)    = (entry_notional(t) + exit_notional(t)) × X / 10,000
           where notional = qty × 記録価格
adj_pnl(t) = pnl(t) − cost(t)

cost-adjusted PF = Σ max(adj_pnl, 0) / |Σ min(adj_pnl, 0)|
cost-adjusted expectancy = Σ adj_pnl / n
```

**Xの決め方**: 実測（§4）+ 保守マージン。paper記録価格 vs 日次基準価格の
乖離は当日ドリフトが支配的で真のスリッページを直接測れないため、
**X = 5 bps/片道を保守的デフォルト**とする（§2のスプレッド/2 + スリッページ
上限 + fee ≈ 2〜6 bps を丸めた保守値）。感度は X ∈ {2, 5, 10, 15} で常に併記。

## 4. 実測値と試算（2026-09-05、closed 357件 / 714 legs、701測定・13除外）

### 4.1 実効スリッページ分布（記録価格 vs 基準価格、+ = コスト方向）

基準価格は日次バー（yfinance）のみ取得可能なため、**当日始値(ref=open)** と
**前営業日終値(ref=prev_close)** で測定。分足がないため値は
「fill品質 + 当日ドリフト」の混合であり、**真のスリッページの上限推計**。

ref=当日始値（bps、抜粋）:

| バケット | n | median | p75 | p90 |
|---|---:|---:|---:|---:|
| entry 09:2x-09:4x ET run（オープン直後・最もクリーン） | 107 | +48.8 | +124.4 | +203.1 |
| entry 12:00 ET run | 58 | +107.7 | +372.2 | +510.3 |
| entry 15:5x ET run | 42 | −130.8 | +27.5 | +412.3 |
| exit 全体 | 347 | +96.8 | +204.2 | +368.8 |
| exit 10-15時 ET（日中ストップ） | 194 | +138.9 | +270.5 | +522.6 |

**解釈**:
- オープン直後エントリーでも median +49 bps だが、これは9:25/9:35 run までの
  数分〜数十分の**モメンタム銘柄の順行ドリフトが支配的**（モメンタム条件を
  満たした銘柄は寄り後も上がりやすい）。真の執行コストとは区別すること。
- 日中ストップexitの +139 bps も「ストップは価格が落ちてから発火する」という
  構造上のドリフトであり、執行品質ではない。
- したがって**この分布から直接Xを読むのは不適切**。分布はコスト以前に
  「シグナル時点と記録価格の乖離」の実態把握（モニタリング基線）として使い、
  Xは§3の定義（スプレッド+小サイズスリッページの保守値=5bps）を採用する。
  実弾移行後は「注文送信時のNBBO mid vs 実fill」で真のスリッページを実測し、
  Xを実測値+マージンに置き換える（§5）。

### 4.2 cost-adjusted PF 試算

| X bps/片道 | 全期間 PF (n=357) | 全期間 Net | 直近コホート PF (exit>=08-14, n=45) | 直近 Net |
|---:|---:|---:|---:|---:|
| 0（現行=コストゼロ） | 0.888 | −$38,253 | 0.530 | −$24,810 |
| 2 | 0.873 | −$43,450 | 0.522 | −$25,355 |
| **5（保守的デフォルト）** | **0.853** | **−$51,246** | **0.511** | **−$26,172** |
| 10 | 0.819 | −$64,239 | 0.492 | −$27,534 |
| 15 | 0.787 | −$77,232 | 0.474 | −$28,897 |

**含意**: 片道5bpsで全期間PFは 0.888→0.853（−0.035）、直近コホートは
0.530→0.511。すでにPF<1のためGO/NO-GO判定は変わらないが、**将来PFが1.0を
僅かに超えた場合、コスト控除で1.0を割る可能性がある水準差**（PF≈1.0近傍では
±0.03〜0.07の影響）であり、昇格判断にはcost-adjusted PFの併記が必須。

## 5. 経済性ゲートへの組み込み（2段階案、要ユーザー承認）

1. **第1段階（補助指標として表示）**: `check_go_no_go.py` の経済性ゲート
   詳細セクションに cost-adjusted PF（X=5bps）を**表示のみ**追加する。
   合否判定には使わない。→ 実装はユーザー承認後の別タスク。
2. **第2段階（Required化）**: paper→実弾移行判断までに、
   `economic_viability` の合格条件を「cost-adjusted PF (X=5bps) > 1.0」に
   置き換える。Xは実弾での実測（注文送信時NBBO mid vs fill の小サイズ計測）
   後に実測値+保守マージンへ更新する。→ ユーザー承認後に実施。

いずれの段階でも X と定義式は本ドキュメントを唯一の正（single source of
truth）とし、変更時はここを先に更新する。

## 関連

- `docs/promotion_governance.md`（R18-D: 昇格判断はcost-adjusted PF併記）
- `docs/console_improvement_tasks.md` R18-E セクション
