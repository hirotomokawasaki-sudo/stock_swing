# 日本株拡張ロードマップ: 米国AI/半導体連動銘柄

**作成日**: 2026-08-19
**位置づけ**: `docs/broker_migration_ibkr_plan.md`（Alpaca→IBKR移行）とは**別トラック**。
IBKR移行が前提条件（日本株はIBKR経由でないと物理的に売買できない）だが、
検証・戦略設計自体はIBKR接続方式・D0確定を待たずに今から進められる。
9/15 Go/No-Go判定（既存米国戦略のパフォーマンス評価）とも独立。

**背景**: ユーザーより、IBKR移行後は日本株も売買対象になり、米国AI/テック/半導体
サイクルと連動する日本の半導体製造装置・材料・パッケージング銘柄が有力な拡張候補
ではないかとの発案。ロードマップ化し検証を進める指示（2026-08-19）。

---

## 0. 依存関係と前提

```
docs/broker_migration_ibkr_plan.md (Track B: IBKR接続確立)
        │
        ├── 必須前提: 日本株の実売買には IBKR 経由の接続が必要
        │             （現行 Alpaca では日本株は取引不可）
        │
        └── 独立して進行可能: 本ロードマップの Phase 1（相関検証）〜
            Phase 2（戦略設計）はデータ取得のみで完結し、ブローカー接続を
            必要としない。Phase 3（実運用配線）以降で IBKR 接続が必須になる。
```

## 1. 購入禁止リスト（インサイダー等の理由による除外）

**確定事項（2026-08-19ユーザー指示）**:
- **ソフトバンクグループ（9984）は購入対象外**（インサイダーに該当するため）
- **購入は禁止だが、検証・分析（相関測定・バックテスト等）はOK**
- 追って詳細な購入禁止リストがユーザーから提供される予定

**運用方針**:
- 禁止銘柄は既存の `pf_gate_skip_symbols` と対になる形で、新規に
  **`purchase_restricted_symbols`**（買い禁止リスト）を設計する
  （`config/reference/jp_symbol_registry.yaml` または既存
  `symbol_registry.yaml` 内に `purchase_restricted: true` フラグとして統合する
  案を Phase 2 で検討）
- **重要な設計原則**: 禁止銘柄はデータ収集・特徴量計算・バックテスト・
  シグナル生成の対象からは除外しない。**発注直前のフィルタ層でのみブロックする**
  （既存の `EntryFilterEngine` のフィルタ思想と同じレイヤーに置く。
  `pf_gate_skip_symbols` がPFゲートをバイパスする allow-list なのに対し、
  こちらは発注そのものをブロックする deny-list）
- ユーザーからの詳細リスト受領後、本ドキュメントのセクション6に反映し、
  実装（Phase 3）時に `EntryFilterEngine` または `PaperExecutor` の
  pre-submission checkに `purchase_restricted_symbols` チェックを追加する

## 2. 投資仮説

米国のAI関連capex（データセンター・AIアクセラレータ投資）は、TSMC等のファブ設備投資
を経由して日本の半導体製造装置・材料・パッケージングメーカーの受注に直結する。
また、東証とNY市場のセッションが重ならない（東証9:00-15:00 JST、NY22:30/23:30 JST〜）
ため、**前夜の米国半導体指数（SOX/SMH/SOXX）や主要AI銘柄（NVDA等）の大幅な値動きが
翌朝の東証寄り付きに継続しやすい（オーバーナイト・スピルオーバー）**という仮説を
検証する。

## 3. 候補銘柄（相関の強さ順、暫定）

| ティア | 銘柄 | コード(.T) | 位置づけ |
|---|---|---|---|
| Tier 1（直接連動） | Advantest | 6857 | HBM/AIチップ用テスト装置。AIアクセラレータ需要の代理指標 |
| Tier 1 | Tokyo Electron | 8035 | 露光・成膜装置。歴史的にSOX/SMHとの相関が高い |
| Tier 1 | Disco | 6146 | ダイシング・研削装置。HBM実装工程にも露出 |
| Tier 2 | Lasertec | 6920 | EUVマスク検査でほぼ独占。ボラ高いがcapex感応度強い |
| Tier 2 | Screen Holdings | 7735 | 洗浄装置 |
| Tier 2 | Sumco | 3436 | シリコンウエハー材料 |
| Tier 2 | Shin-Etsu Chemical | 4063 | シリコンウエハー材料（総合化学のため相関やや希薄化） |
| Tier 2 | Ibiden | 4062 | ICパッケージ基板（ABF基板） |
| Tier 2 | Shinko Electric Industries | 6967 | 同上 |
| Tier 3 | Fujikura | 5803 | AIデータセンター向け光ケーブル |
| Tier 3 | Furukawa Electric | 5801 | 光/銅ケーブル |
| Tier 3 | Yaskawa Electric | 6506 | ロボティクス（既存 `robotics_ai` セクター分類と親和性） |
| 🚫 除外 | ~~SoftBank Group~~ | ~~9984~~ | **購入禁止（インサイダー該当）。検証には含めてよい** |

ベンチマーク（米国側の比較対象）: `SOXX`, `SMH`, `NVDA`, `QQQ`（既存
`symbol_registry.yaml` の `benchmark_symbols` パターンを踏襲）

## 4. 段階計画

### Phase 1: 相関・スピルオーバー検証（データのみ、IBKR接続不要）

| 項目 | 内容 |
|---|---|
| データソース | Yahoo Finance（`.T`サフィックス、`yfinance`ライブラリで取得可能。実地確認済み: 2026-08-19、`8035.T`等で日足データ取得成功） |
| 検証1 | 米国半導体指数（SOXX/SMH）の日次リターンと、候補銘柄の**翌営業日**リターンの相関係数 |
| 検証2 | 「前夜のSOXXが±2%以上動いた日」条件付きで、翌朝の東証寄り付き（始値）ギャップ幅の分布 |
| 検証3 | NVDA単体の急変日（決算発表後等）と、Advantest/Tokyo Electron等の翌朝反応の個別ケース確認 |
| 出力 | `reports/jp_semiconductor_correlation_analysis.json` + サマリーMarkdown |
| 実施主体 | 本ロードマップ内で直ちに着手（本セッションで実施予定） |

### Phase 2: 戦略設計（コード実装、まだIBKR接続不要）

| 項目 | 内容 |
|---|---|
| 戦略アーキテクチャ | 既存 `BreakoutMomentumStrategy` の拡張、または新規
  `OvernightSpilloverStrategy` として独立実装するかを Phase 1 結果を見て判断 |
| 特徴量追加候補 | 「前夜のSOXX/SMHリターン」を`feature_engine`に追加する新規Feature |
| purchase_restricted対応 | `EntryFilterEngine`にdeny-listチェックを追加（設計のみ、配線はPhase 3） |
| JPX固有の技術対応 | 市場カレンダー（`MarketCalendar`のJPX拡張）、通貨（JPY建てPnL）、
  単元株（100株単位）の設計をこのPhaseでドキュメント化 |
| Go/No-Go | Phase 1相関が実用に足る強さ（目安: 相関係数0.4以上、または
  スピルオーバー方向一致率60%以上）であればPhase 3へ進む |

### Phase 3: 実運用配線（IBKR接続確立後）

| 項目 | 内容 |
|---|---|
| 前提条件 | `docs/broker_migration_ibkr_plan.md` Track B の IBKR Paper 昇格判定完了後 |
| 実装 | 日本株用の `IBKRBrokerClient` アダプタ拡張（TSE取引時間・通貨・単元株対応） |
| 運用開始 | 既存の「shadow → paper_ab → active」段階昇格パターンを踏襲。
  日本株もまず shadow mode（発注せず記録のみ）から開始 |
| リスク管理 | US半導体銘柄（AMAT等）とJP半導体銘柄（Tokyo Electron等）の
  **クラスター集中管理を統合**する必要あり（下記セクション5参照） |

## 5. リスク管理上の重要な注意点

**US-JP横断クラスター集中リスク**: 既存の `sector_shock_hold` やセクター別
エクスポージャー上限（`SYMBOL_SECTORS`, `symbol_registry.yaml`の`sector`）は
現状「米国半導体セクター」単体で管理されている。AMAT/AVGO等の米国半導体銘柄と
Tokyo Electron/Advantest等の日本半導体銘柄を同時に保有すると、実質的に
「グローバル半導体capexテーマ」への二重・三重エクスポージャーになる。

→ Phase 2で `symbol_registry.yaml` の `sector: semiconductor` 分類を
US/JP横断で統一管理し、既存のセクター集中上限ロジックがJP銘柄追加後も
正しく機能することを確認する（新規のsector追加ではなく、既存sectorに
JP銘柄を編入する設計を推奨）。

## 6. 購入禁止リスト（deny-list）

| 銘柄 | コード | 理由 | 登録日 |
|---|---|---|---|
| SoftBank Group | 9984 | インサイダー該当 | 2026-08-19 |

> ユーザーから追加の詳細リストが提供され次第、本セクションに追記し、
> Phase 3実装時の `purchase_restricted_symbols` 設定に反映する。

## 7. Phase 1 検証結果（2026-08-19実施済み）

**ツール**: `scripts/analyze_jp_semiconductor_correlation.py`（新規作成、テスト5件全PASS）
**データ源**: Yahoo Finance（`yfinance`）、期間 2年（約488営業日）
**出力**: `reports/jp_semiconductor_correlation_analysis.json`
**注記**: 6967.T（新光電気工業）は2023年にJIC Capitalによる非公開化（上場廃止）済みで
Yahooから取得不能を確認。候補から除外。

### 7-A. スピルオーバー相関（SOXX(t) vs JP(t+1)）— 仮説を強く支持

| 順位 | 銘柄 | コード | スピルオーバー相関 | 同日相関 |
|---|---|---|---|---|
| 1 | Tokyo Electron | 8035.T | **0.524** | 0.164 |
| 2 | Disco | 6146.T | **0.476** | 0.083 |
| 3 | Advantest | 6857.T | **0.470** | 0.177 |
| 4 | Fujikura | 5803.T | 0.450 | 0.101 |
| 5 | Lasertec | 6920.T | 0.448 | 0.061 |
| 6 | Ibiden | 4062.T | 0.441 | 0.140 |
| 7 | Screen Holdings | 7735.T | 0.440 | 0.176 |
| （参考）| SoftBank Group🚫 | 9984.T | 0.435 | 0.106 |
| 9 | Shin-Etsu Chemical | 4063.T | 0.422 | -0.006 |
| 10 | Yaskawa Electric | 6506.T | 0.398 | 0.090 |
| 11 | Furukawa Electric | 5801.T | 0.392 | 0.140 |
| 12 | Sumco | 3436.T | 0.373 | 0.106 |

**重要な発見**: 全銘柄で**同日相関（0.06〜0.18）よりスピルオーバー相関（0.37〜0.52）の方が
はるかに強い**ことが確認された。これはロードマップの仮説（前夜の米国半導体指数の値動きが
翌朝の東証寄り付きに継続しやすい）を実データで支持する結果。Tokyo Electron・Disco・Advantestの
Tier 1銘柄が上位3位を占め、事前の仮説を裏付けた。

### 7-B. 条件付きギャップ分析（|SOXX日次リターン| ≥ 2%）

| 銘柄 | US大きなUP日(n=90) 平均JPギャップ/方向一致率 | US大きなDOWN日(n=78) 平均JPギャップ/方向一致率 |
|---|---|---|
| Advantest | +2.93% / **90%** | -3.16% / 85% |
| Tokyo Electron | +2.43% / **90%** | -3.06% / 89% |
| Disco | +2.52% / 89% | -3.20% / **90%** |
| Ibiden | +3.29%（最大）/ 81% | -2.98% / 81% |
| Fujikura | +3.02% / 87% | -3.21% / **95%**（最高）|
| Lasertec | +2.37% / 89% | -2.96% / 89% |
| Screen Holdings | +2.54% / **93%** | -2.67% / 81% |
| Shin-Etsu Chemical | +1.12%（最小）/ 86% | -1.27%（最小）/ 76% |
| Yaskawa Electric | +2.04% / 88% | -1.69% / 76% |
| Furukawa Electric | +2.80% / 86% | -2.99% / 86% |
| Sumco | +1.97% / 83% | -2.92% / 85% |
| （参考）SoftBank🚫 | +2.42% / 84% | -3.33% / 87% |

**重要な発見**: 前夜SOXXが±2%以上動いた日の翌朝、**Advantest/Tokyo Electronは
UP方向一致率90%**、**FujikuraはDOWN方向一致率95%**と、方向性の一致率自体は非常に高い。
一方でギャップ幅の平均は約2〜3%と大きく、**既に大部分のファンダメンタル情報が
翌朝の寄り付き時点で反映済み**であることを意味する（寄り付いてから抜く戦略では遅い
可能性が高い）。実運用ではギャップ自体を取りに行く（寄り付き直前の指値注文等）か、
ギャップ後の継続（モメンタム）を狙うかで設計が分かれる（Phase 2で検討）。

### 7-C. Go/No-Go判定

ロードマップセクション4で設定した基準（相関係数0.4以上、または方向一致率60%以上）に対し：
- **Tier 1全銘柄（Advantest/Tokyo Electron/Disco）が相関係数0.47〜0.52、方向一致率85〜90%でクリア**
- → **✅ GO。Phase 2（戦略設計）に進む**

## 8. 次のアクション

- [x] Phase 1 相関検証実施済み（2026-08-19、GO判定）
- [ ] ユーザーからの追加の詳細購入禁止リスト受領後、セクション6を更新
- [ ] Phase 2（戦略設計、特徴量追加、JPX固有対応の設計）に着手

*作成: 2026-08-19*
