# R0-v2-C: Guardrail Metrics Analysis
**作成日**: 2026-07-21  
**Source**: config/guardrails/autonomous_stop.yaml + src/stock_swing/cli/paper_demo.py

---

## 現状サマリー

| configured rules | 供給中 | 不足 |
|-----------------|--------|------|
| 9件 | **4件** | **5件** |

`api_error_rate_pct` は供給されているが **0.0 ハードコード**（= 実測値なし）

---

## 9ルールの供給状況

| # | metric | 供給 | 備考 |
|---|--------|------|------|
| 1 | stale_price_event_count | ✅ 実測 | len(stale_symbols) |
| 2 | broker_tracker_mismatch_count | ✅ 実測 | _adjusted_mismatch (G1-v2) |
| 3 | api_error_rate_pct | ⚠️ 0.0固定 | → 実測値に要修正 |
| 4 | order_rejection_rate_pct | ✅ 実測 | submissions ≥4 のみ評価 |
| 5 | **daily_realized_loss_pct** | ❌ MISSING | |
| 6 | **daily_total_loss_pct** | ❌ MISSING | |
| 7 | **weekly_total_loss_pct** | ❌ MISSING | |
| 8 | **consecutive_losing_trades** | ❌ MISSING | |
| 9 | **token_spend_spike_pct** | ❌ MISSING | |

---

## 各不足 metric の取得源と計算方法

### M1: daily_realized_loss_pct

**取得源**: PnLTracker + daily_snapshot  
**ファイル**: `src/stock_swing/tracking/pnl_tracker.py`  
**計算**:
```python
today_iso = datetime.now(timezone.utc).date().isoformat()
daily_realized = sum(
    t.get('pnl', 0) or 0
    for t in pnl_tracker.get_clean_closed_trades()
    if str(t.get('exit_time', ''))[:10] == today_iso
)
start_equity = equity - daily_realized - unrealized  # 近似
daily_realized_loss_pct = abs(min(daily_realized, 0)) / max(start_equity, 1) * 100
```
**依存**: PnLTracker（既に paper_demo.py で利用中）

### M2: daily_total_loss_pct

**取得源**: PnLTracker + broker.fetch_account()  
**計算**:
```python
# daily_realized + unrealized 変化 / start_equity
# unrealized_change = current_unrealized - yesterday_unrealized
# → daily_snapshot から yesterday_equity を取得
daily_total_loss_pct = abs(min(daily_realized + unrealized_change, 0)) / start_equity * 100
```
**依存**: daily_snapshots（pnl_state.json に保存済み）

### M3: weekly_total_loss_pct

**取得源**: PnLTracker  
**計算**:
```python
from datetime import date, timedelta
today = date.today()
week_start = today - timedelta(days=today.weekday())  # last Monday
weekly_realized = sum(
    t.get('pnl', 0) or 0
    for t in pnl_tracker.get_clean_closed_trades()
    if str(t.get('exit_time', ''))[:10] >= week_start.isoformat()
)
weekly_total_loss_pct = abs(min(weekly_realized, 0)) / start_equity * 100
```

### M4: consecutive_losing_trades

**取得源**: PnLTracker  
**計算**:
```python
sorted_closed = sorted(
    pnl_tracker.get_clean_closed_trades(),
    key=lambda t: t.get('exit_time', '')
)
count = 0
for t in reversed(sorted_closed):
    if (t.get('pnl') or 0) < 0:
        count += 1
    else:
        break
consecutive_losing_trades = count
```
**注意**: R0-v2-B が完了するまでは hd_missing=245 のデータが混入する可能性。  
R0-v2-B 完了後に有効化推奨。

### M5: token_spend_spike_pct

**取得源**: paper_demo.py の ai section  
**計算**:
```python
# ai section の summary から
today_tokens = ai_metrics.get('input_tokens', 0) + ai_metrics.get('output_tokens', 0)
daily_budget = cfg.get('daily_token_budget', 300000)
token_spend_spike_pct = max(0, (today_tokens / daily_budget - 1) * 100)
```
**既存変数**: `ai_section` がすでに構築済み → 取得容易

### M6: api_error_rate_pct（修正）

**現状**: `"api_error_rate_pct": 0.0` ハードコード  
**修正**:
```python
_api_metrics = _build_api_metrics(latency_tracker)
api_error_rate_pct = (
    _api_metrics.get('error_count', 0) /
    max(_api_metrics.get('call_count', 1), 1) * 100
)
```
**既存変数**: `_api_metrics` は ConsoleSummary 構築時にすでに計算済み

---

## RiskSnapshot 設計案（R0-v2-C 実装時）

```python
@dataclass
class RiskSnapshot:
    """All guardrail metrics in one typed object."""
    stale_price_event_count: int
    broker_tracker_mismatch_count: int       # after lag_excused
    api_error_rate_pct: float                # from latency_tracker (not 0.0)
    order_rejection_rate_pct: float
    daily_realized_loss_pct: float
    daily_total_loss_pct: float
    weekly_total_loss_pct: float
    consecutive_losing_trades: int
    token_spend_spike_pct: float
    computed_at: str                         # ISO timestamp
```

**利点**: startup / pre-order / post-run で同じ型を使い回せる。テストが書きやすい。

---

## 実装優先順位

| Priority | Metric | 理由 |
|----------|--------|------|
| P0（今すぐ） | api_error_rate_pct 修正 | 1行の fix、リスクゼロ |
| P0（今すぐ） | token_spend_spike_pct | ai section 既存変数から容易 |
| P1（R0-v2-B後） | consecutive_losing_trades | 台帳クリーン後でないとノイズ |
| P2 | daily_realized_loss_pct | daily_snapshot 必要 |
| P2 | daily_total_loss_pct | unrealized変化の計算必要 |
| P3 | weekly_total_loss_pct | daily完了後 |

---

## テスト要件

```python
def test_all_configured_guardrail_metrics_are_supplied():
    """config の enabled=true な rule metrics が全て _post_metrics に含まれる"""
    ...

def test_api_error_rate_is_not_hardcoded_zero():
    """api_error_rate_pct が latency_tracker の error_count から計算される"""
    ...

def test_token_spend_spike_is_computed():
    """token_spend_spike_pct = (today_tokens / budget - 1) * 100 when over budget"""
    ...

def test_consecutive_losing_uses_pnl_tracker():
    """consecutive_losing_trades は tail of clean closed trades を反映する"""
    ...
```
