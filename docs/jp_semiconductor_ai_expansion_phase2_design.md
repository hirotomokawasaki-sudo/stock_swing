# Phase 2: 戦略設計 — 日本株AI/半導体拡張

**作成日**: 2026-08-19
**位置づけ**: `docs/jp_semiconductor_ai_expansion_plan.md` Phase 2。
Phase 1（相関検証、✅ GO判定）を受けて、実装設計を行う。
**本ドキュメントは設計のみ。IBKR接続が未確立のため、発注に関わる実配線（Phase 3）は
一切行わない。** JPX固有の設計・特徴量設計はコード実装するが、`paper_demo.py`本体には
配線しない（新規モジュールとして独立させ、Phase 3でIBKR接続後に配線する）。

---

## 1. 戦略アーキテクチャ判断

### 1-A. 既存`BreakoutMomentumStrategy`拡張 vs 新規戦略

**判断: 新規戦略として独立させる（`OvernightSpilloverStrategy`）**

理由:
- 既存`BreakoutMomentumStrategy`は「当日のモメンタムが閾値を超えたら買う」というザラ場中の
  シグナル生成モデル。Phase 1で検証したのは「前夜の米国ベンチマークの動き→翌朝のJP寄り付き」
  という**別の因果構造**であり、シグナルの入力（時間軸）が本質的に異なる
- 既存戦略に無理に統合すると、`strategy_id`ベースのPF/WR属性分析（既存の
  `get_asset_class_breakdown()`等）でUS株のモメンタム戦略とJP株のスピルオーバー戦略の
  パフォーマンスが混ざり、既存の分析基盤（`docs/testing_standards.md`が重視する
  レイヤー別テスト・属性追跡）を汚染するリスクが高い
- 新規`strategy_id = "overnight_spillover_v1"`として独立させれば、既存の
  `strategy_daily_snapshots`やPF属性分析パターンをそのまま流用できる

### 1-B. シグナル生成ロジック（暫定設計）

Phase 1のセクション7-Bで判明した通り、寄り付き時点で既に情報の大部分（平均2〜3%の
ギャップ）が反映されているため、「寄り付いてから買う」設計は避ける。2つの実行アプローチ
を候補とする：

| アプローチ | 概要 | 長所 | 短所 |
|---|---|---|---|
| **A: 寄り付き前指値** | 前夜の米国ベンチマーク変化率から翌朝の期待ギャップを推定し、
  寄り付き前（8:00-9:00 JST）に指値注文を出す | Phase 1で確認した高い方向一致率
  （85-90%）をそのまま活用できる | JPX寄り付き板の需給を正確に予測するのは難しく、
  約定しない/意図しない価格で約定するリスク |
| **B: 寄り付き後モメンタム継続** | 寄り付き後、実際のギャップ方向を確認してから
  数分〜数十分の値動き（続伸/反転）を見て判断 | 既存`BreakoutMomentumStrategy`の
  ザラ場中判定ロジックを部分的に流用できる | Phase 1で見た「情報の大部分は寄り付きで
  反映済み」という結果から、旨味の大部分を取り逃す可能性 |

**暫定推奨**: **アプローチA（寄り付き前指値）を軸にしつつ、Bを保険的セカンダリ
シグナルとして併用**。Phase 1データのUP日方向一致率90%（Advantest/Tokyo Electron）
はAアプローチの単純な期待値計算でも十分に優位性が見込める水準。ただし約定確度が
未検証のため、**Phase 3の shadow mode 期間で実際の板/約定挙動を観測してから正式決定**
する（既存プロジェクトの「shadow → paper_ab → active」段階昇格文化を踏襲）。

### 1-C. シグナル強度（signal_strength）設計

既存`BreakoutMomentumStrategy`のsignal_strength設計（momentum量に応じた0.0-1.0スケール、
07-02のR4-Bで0.40キャリブレーション等）を参考に、以下の要素で構成：

```
signal_strength = f(
    us_benchmark_return_magnitude,   # 前夜のSOXX/SMHリターンの絶対値（大きいほど強い）
    symbol_tier_weight,               # Tier1=1.0, Tier2=0.7, Tier3=0.5（Phase1相関の強さに比例）
    direction_consistency_prior,      # Phase1で計測した銘柄別の方向一致率を事前分布として反映
)
```

具体的な閾値・係数はPhase 3のshadow運用データで実測してからキャリブレーションする
（既存プロジェクトの「本番投入前に閾値を仮決めせず、実データで調整する」方針を踏襲。
`R4-v2`のconfidence calibration readiness gateと同じ考え方）。

## 2. 特徴量追加設計

### 2-A. 新規Feature: `us_overnight_benchmark_return`

`feature_engine`に新規Feature（既存`price_momentum`/`macro_regime`と同型パターン）:

```python
FeatureResult(
    feature_name="us_overnight_benchmark_return",
    symbol="8035.T",  # JP symbol
    values={
        "soxx_return_pct": ...,      # 前夜SOXX日次リターン
        "smh_return_pct": ...,       # 前夜SMH日次リターン
        "nvda_return_pct": ...,      # 前夜NVDA日次リターン（Tier1銘柄のみ意味を持つ可能性）
        "reference_us_close_date": ...,  # どのUS取引日を参照したか（JPX休場日対応で重要）
    }
)
```

**JPX/NYSE休場日の非対称性への対応**: 米国が休場でJPXが開いている日（逆に日本の祝日で
米国が開いている日）は「前営業日」の定義がずれる。単純な「前日」ではなく、
**「直近に確定したUS regular session close」を参照する設計**にする（既存
`MarketCalendar.previous_trading_close_utc()`と同型のロジックをJPX側にも実装する
必要がある、セクション3参照）。

### 2-B. 既存パターンとの整合性

`config/reference/symbol_registry.yaml`の`benchmark_symbols`フィールド（既存、
US銘柄向けにSMH/SOXX/QQQ等を紐付け済み）と同じ設計思想で、JP銘柄にも
`benchmark_symbols: [SOXX, SMH, NVDA]`を追加する形にする（新しい概念を持ち込まず、
既存スキーマを拡張）。

## 3. JPX固有の技術対応（設計）

### 3-A. 市場カレンダー拡張

既存`src/stock_swing/utils/market_calendar.py`の`MarketCalendar`はNYSE専用実装
（`FIXED_HOLIDAYS`, `is_us_holiday()`, DST処理等がUS前提でハードコード）。

**設計方針**: 既存クラスを直接改造せず、**`JPXMarketCalendar`を新規クラスとして
並立させる**（既存の`MarketCalendar`はUS専用のまま変更しない。既存コードへの影響ゼロ）。

```python
class JPXMarketCalendar:
    """JPX (Tokyo Stock Exchange) market calendar.

    JPX固有の要件:
    - 日本の祝日（内閣府「国民の祝日」+ 銀行休業日の年末年始 12/31-1/3）
    - 取引時間: 前場9:00-11:30、後場12:30-15:00 JST（昼休みあり、NYSEと違う）
    - タイムゾーン処理はJSTのみで完結（US側のようなET-JST変換・DST考慮は不要）
    """
```

祝日データソースの選定はPhase 3着手時に決定（`jpholiday`ライブラリ等の既存Pythonパッケージ
の利用、またはハードコード方式のいずれか。既存`MarketCalendar`がハードコード方式である
ことを踏まえ、依存追加を避けるなら同型のハードコード実装も可）。

### 3-B. 通貨（JPY建てPnL）対応

**設計方針**: `pnl_tracker.py`のTradeEntryに`currency: str = "USD"`フィールドを追加し、
JP取引は`currency="JPY"`で記録する。PnL集計は**通貨別に分離して表示**し、USD換算した
統合ビューは別途オプションで提供する（無理に単一通貨に統合せず、既存の
`environment_id`（IBKR移行A3設計）と同様に、`currency`を新しい分離軸として扱う）。

FXヘッジの要否（円建てポジションの為替リスクをヘッジするか）は、**Phase 3のポジション
規模が小さいうち（shadow/paper_ab段階）は非ヘッジで運用し、active昇格時に再検討**する
方針を推奨（早期の複雑化を避ける）。

### 3-C. 単元株（100株単位）対応

**設計方針**: `position_sizing.py`の`PositionSizingPolicy.size()`が返す`final_shares`
計算後に、JP銘柄向けの丸め処理を追加する:

```python
def round_to_jp_trading_unit(shares: int, unit: int = 100) -> int:
    """東証の単元株（原則100株）に丸める。floor方向（小さい方）に丸めて予算超過を防ぐ。"""
    return (shares // unit) * unit
```

これは既存の`shares_by_risk`/`shares_by_notional`/`shares_by_exposure`の`min()`計算
パイプラインの**最後に追加のガード**として挿入する設計（既存ロジックの改変ではなく
後段フィルタとして追加、既存US株のsizingには一切影響しない設計にする）。

## 4. purchase_restricted_symbols 設計（EntryFilterEngine拡張）

`docs/jp_semiconductor_ai_expansion_plan.md`セクション1の運用方針（発注直前でのみ
ブロック、データ収集・バックテストは対象外）を`EntryFilterEngine`に実装する設計：

```python
@dataclass
class EntryFilterConfig:
    ...
    # 新規フィールド（既存 pf_gate_skip_symbols と対になる deny-list）
    purchase_restricted_symbols: list = field(default_factory=list)
```

既存の`from_env()`パターンを踏襲し、`ENTRY_FILTER_PURCHASE_RESTRICTED_SYMBOLS`
環境変数（カンマ区切り、既存`ENTRY_FILTER_PF_GATE_SKIP_SYMBOLS`と同型）で設定。

**フィルタ位置**: 既存のGate 1-4（Volume/ADR/Rolling PF/stock-reduced）とは独立した
**Gate 0**として、他の全ゲートより先に評価する（インサイダー規制は他のリスク判断より
優先度が最上位であるべきため）:

```python
# --- Gate 0: Purchase restriction (highest priority, e.g. insider) ---
if symbol in cfg.purchase_restricted_symbols:
    deny_reason = f"purchase_restricted: {symbol} is on the insider/compliance deny-list"
    diag.setdefault("purchase_restricted_blocked", []).append(symbol)
    # Gate 1-4は評価しない（早期return）
```

**重要**: このゲートは**発注判定（`EntryFilterEngine`）にのみ適用**し、
`feature_engine`のシグナル生成・`analyze_jp_semiconductor_correlation.py`のような
リサーチツール・バックテストのいずれにも適用しない（ユーザー指示「検証はOK、購入だけ禁止」
を正確に反映する設計）。

現在の登録銘柄: `SoftBank Group (9984.T)`のみ。ユーザーからの詳細リスト受領後に追加。

## 5. US-JP横断クラスター集中リスク管理（最重要）

`docs/jp_semiconductor_ai_expansion_plan.md`セクション5で指摘した通り、既存
`SYMBOL_SECTORS`辞書（`position_sizing.py`）は`'semis'`セクターに米国半導体銘柄
（NVDA, AVGO, AMD, AMAT等）のみを登録している。

**設計方針**: JP半導体銘柄を**同じ`'semis'`セクターキーに編入**する（新しいセクター
`'jp_semis'`等を新設しない）。

```python
SYMBOL_SECTORS = {
    # 既存 US 半導体銘柄（変更なし）
    'NVDA':'semis', 'AVGO':'semis', ..., 'AMAT':'semis', 'LRCX':'semis', 'KLAC':'semis', ...
    # 新規 JP 半導体銘柄（同じ 'semis' セクターに編入）
    '6857.T':'semis',  # Advantest
    '8035.T':'semis',  # Tokyo Electron
    '6146.T':'semis',  # Disco
    '6920.T':'semis',  # Lasertec
    '7735.T':'semis',  # Screen Holdings
    '3436.T':'semis',  # Sumco
    '4063.T':'semis',  # Shin-Etsu Chemical (化学全体ではなく半導体材料事業として編入)
    '4062.T':'semis',  # Ibiden
    # 光ケーブル・ロボティクスは別セクターとして新設検討（半導体ほど直接的ではないため）
    '5803.T':'jp_networking',  # Fujikura（暫定、Phase3で要再検討）
    '5801.T':'jp_networking',  # Furukawa Electric（同上）
    '6506.T':'jp_robotics',    # Yaskawa Electric（既存robotics_aiセクター分類と整合）
    ...
}
```

これにより、既存の`max_sector_exposure_pct`（デフォルト55%）のロジックが**変更なしで
US+JP半導体の合算エクスポージャーを正しく制限する**（`PositionSizingPolicy.size()`
の`current_sector_exposure`計算・`remaining_sector_capacity`計算は既存のまま流用可能）。

**追加の注意**: `current_sector_exposure`の計算は`paper_executor.py`の
`_calculate_position_size()`内で`broker.fetch_positions()`から取得したポジション一覧を
セクターごとに合算する実装になっている。JP側のポジションが別ブローカー接続
（IBKR、`environment_id=ibkr_paper`等）にある場合、**US側とJP側のポジション取得を
統合するロジックが必要**（IBKR移行のA3設計・`environment_id`と密接に関連する。
Phase 3実装時に`docs/broker_migration_environment_id_design.md`と整合させる）。

## 6. Go/No-Go（Phase 3着手可否の判断基準）

Phase 2の設計完了時点で、以下が揃えばPhase 3（IBKR接続後の実配線）に進む：

| 条件 | 状態 |
|---|---|
| Phase 1相関検証がGO判定 | ✅ 完了（2026-08-19） |
| Phase 2アーキテクチャ設計完了（本ドキュメント） | ✅ 完了（2026-08-19） |
| purchase_restricted_symbols実装（先行着手分） | ✅ 完了（2026-08-19） |
| JPXMarketCalendar実装（先行着手分） | ✅ 完了（2026-08-19） |
| IBKR接続確立（`docs/broker_migration_ibkr_plan.md` Track B） | ⚪ 未達（D0待ち） |
| ユーザーからの詳細購入禁止リスト受領 | ⚪ 未達 |
| US-JP横断セクター集中管理の実装・テスト | ⚪ Phase 3で実装 |

**Phase 3は IBKR接続確立（Track B完了）が事実上の前提条件**。それまでは、
本ドキュメントの設計に基づいた**コード実装（`JPXMarketCalendar`, 新規Feature,
`purchase_restricted_symbols`ゲート等）自体は先行して着手可能**
（発注に配線しなければ、既存の本番運用に一切影響しないため）。

## 7. 実装状況（2026-08-19実施済み）

### 7-A. `purchase_restricted_symbols`（EntryFilterEngine Gate 0）✅ 実装完了

- `src/stock_swing/risk/entry_filter.py`: `EntryFilterConfig.purchase_restricted_symbols`
  フィールド追加、`ENTRY_FILTER_PURCHASE_RESTRICTED_SYMBOLS`環境変数対応
  （既存`pf_gate_skip_symbols`と同型パターン）
- Gate 0として他の全ゲート（Volume/ADR/Rolling PF/stock-reduced）より先に評価、
  該当銘柄は即座にdeny（他ゲートを評価しない短絡動作）
- **重要**: このゲートは`EntryFilterEngine.filter()`（発注判定）にのみ適用。
  データ収集・特徴量計算・バックテスト・リサーチツール（`analyze_jp_semiconductor_correlation.py`
  等）には一切影響しない設計（ユーザー指示どおり「検証はOK、購入だけ禁止」を正確に実装）
- **注**: 本ゲートは既存`paper_demo.py`のパイプラインに未配線（`EntryFilterEngine`自体が
  現状`paper_demo.py`本体で呼び出されているかは別途確認要、Phase 3で日本株を実配線する際に
  合わせて配線する）
- テスト: `tests/unit/test_entry_filter.py`に7件追加（Gate 0のブロック確認、他ゲート短絡確認、
  デフォルト空リストで既存銘柄に影響しないこと、env変数パース、非buy actionは素通りすること等）
- フルスイート: 38 passed（entry_filter単体）

### 7-B. `JPXMarketCalendar` ✅ 実装完了

- `src/stock_swing/utils/jpx_market_calendar.py`: 新規独立クラス（既存`MarketCalendar`
  はNYSE専用のまま無変更）
- 日本の祝日を外部依存なし（`jpholiday`未インストールのため、既存`MarketCalendar._good_friday()`
  と同じ「正確な日付計算、外部依存なし」方針を踏襲）で実装：固定日祝日、ハッピーマンデー
  （成人の日/海の日/敬老の日/スポーツの日）、春分の日/秋分の日（国立天文台の近似式）、
  振替休日（後方探索アルゴリズムで多日連続の祝日チェーンにも対応）、年末年始休場
- 前場9:00-11:30・昼休み11:30-12:30・後場12:30-15:00のセッション判定、
  `previous_trading_close_jst()`（直近確定後場終値の取得、休日クラスター対応）を実装
- **実データ検証**: 2024年・2025年の公知の祝日40件全てで完全一致を確認（成人の日の移動、
  振替休日の連鎖ケース「2025年5/4みどりの日が日曜のため5/6に振替（5/5こどもの日を
  スキップ）」等の複雑なケースも正しく処理）
- テスト: `tests/unit/test_jpx_market_calendar.py`新規68件全PASS
- **未配線**: `paper_demo.py`等の既存フローには一切接続していない（Phase 3で日本株実配線時に接続）

### 7-C. 回帰確認

フルテストスイート実行: **1983 passed, 2 skipped**（既存の無関係スキップのみ、regressionなし。
Phase 2着手前の1904+70件追加相当の増分）

## 8. 次のアクション

- [x] `purchase_restricted_symbols`のEntryFilterEngine実装（2026-08-19完了）
- [x] `JPXMarketCalendar`の実装（2026-08-19完了）
- [ ] ユーザーからの詳細購入禁止リスト受領後、`purchase_restricted_symbols`設定に反映
- [ ] IBKR接続確立後、Phase 3（実配線・shadow運用開始）に着手

*作成: 2026-08-19*
