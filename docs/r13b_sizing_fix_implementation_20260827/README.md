# R13-B sizing側: confidence_multiplierバグの正式実装（2026-08-27）

## 経緯

08-26の`docs/r13b_sizing_confidence_multiplier_fix_validation_20260826/README.md`
で以下が判明済みだった:
- `position_sizing.py`の`confidence_multiplier`はhigh-confidence側（1.2倍）が
  数学的に絶対発火しない構造バグ（`cap`が`base_final_shares`と同一式で
  再計算されるため）
- メカニズム検証（n=58）は完了、修正案（リスク予算に事前適用）も設計済み
- PnL影響の検証（n=2）は統計的に無意味なサンプルサイズで判断不可

08-26の結論は「現時点でpaper A/Bに進める根拠は不十分、本番コード変更は行わない」
だった。

## 本日の実装内容

修正自体は「意図した仕様が動いていない実装バグ」であり「儲かるかどうか未知の
新機能」ではないという08-26の性質評価に基づき、**PnL影響が未検証な間はデフォルト
無効の環境変数フラグの下で修正コードを実装**した（`STOCK_POSITION_SIZE_
MULTIPLIER`/`PAPER_DEMO_USE_INTRADAY`/`ENTRY_FILTER_STOCK_REDUCED`と同じ
「リスクを伴う変更はopt-inフラグの背後に実装する」既存パターンに準拠）。

- `src/stock_swing/risk/position_sizing.py`に
  `SIZING_CONFIDENCE_MULTIPLIER_RISK_BUDGET_FIX_ENABLED`フラグ
  （環境変数`SIZING_CONFIDENCE_MULTIPLIER_RISK_BUDGET_FIX`、デフォルト`false`）
  を追加
- `PositionSizingPolicy.size()`をフラグ分岐に変更:
  - **デフォルト（フラグ無効）**: 旧挙動を完全保持（バグそのまま、
    confidence_multiplier>1.0は引き続きno-op）
  - **フラグ有効時**: `shares_by_risk`にconfidence_multiplierを事前適用してから
    4-way min（`shares_by_notional`/`shares_by_exposure`/`shares_by_sector`と
    比較）を取る修正版ロジック
- 新規テスト5件追加（`tests/unit/test_position_sizing_policy.py`）:
  1. `test_confidence_boost_is_noop_by_default`: デフォルトでバグが保持されて
     いることの回帰確認
  2. `test_confidence_boost_increases_shares_when_fix_enabled`: フラグ有効時に
     リスク予算が支配的な場合にboostが実際に機能することの確認
  3. `test_confidence_cut_unaffected_by_fix_flag`: 0.7倍カット側がフラグの
     有無に関わらず既存動作を完全維持することの確認（非対称バグの「機能して
     いた側」への回帰なし）
  4. `test_confidence_boost_still_noop_when_notional_is_binding`: notional等
     の他キャップが支配的な場合はフラグ有効時でもboostが正しく無効のままで
     あることの確認（意図した挙動、バグではない）

## 現在の本番への影響

**ゼロ**。フラグはデフォルト`false`のため、`SIZING_CONFIDENCE_MULTIPLIER_
RISK_BUDGET_FIX`環境変数を明示的に`true`に設定しない限り、既存の（バグを
含む）本番挙動は一切変わらない。

## テスト結果

- `pytest tests/unit/test_position_sizing_policy.py`: **19 passed**
  （既存14件+新規5件）
- フルテストスイート実行中（結果は本ロードマップ次回更新時に反映）

## 次のアクション

1. **フラグを本番で有効化するかはPnL影響のエビデンスが揃うまで保留**
   （R13-A/Bの既存基準: attributable trades ≥ 30〜90件目安）。
   `decision_id`→closed trade紐付けの標本が自然に増えるのを待つ、または
   paper A/B環境での先行運用（shadow的にconfidence_multiplier発火頻度・qty
   差分を蓄積）を検討
2. 09-08 Pre-Launch Gate Review、またはそれ以降の定期レビューで、
   attributable標本サイズを再確認しフラグ有効化の可否を判断
3. 本修正はコード変更を伴うため、フラグを有効化する際は改めてxhigh
   reasoningでの事前検証・ユーザー承認を経ること（本番データ書き換えは
   伴わないが、sizing挙動を変えるためR0-v2安全制約に準拠）

## 再現方法

```bash
cd ~/stock_swing && source venv/bin/activate
pytest tests/unit/test_position_sizing_policy.py -v
# フラグ有効化時の挙動を手動確認する場合:
SIZING_CONFIDENCE_MULTIPLIER_RISK_BUDGET_FIX=true python3 -c "
from stock_swing.risk.position_sizing import PositionSizingPolicy, PositionSizingInputs
policy = PositionSizingPolicy()
result = policy.size(PositionSizingInputs(
    account_equity=1_000_000, current_price=100, current_total_exposure=0,
    symbol='AVGO', risk_per_share=1, max_risk_per_trade_pct=0.0001, confidence=0.9,
))
print(result)
"
```
