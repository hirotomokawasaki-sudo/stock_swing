# R0-v2-B: Ledger Integrity Repair Runbook

**作成日**: 2026-07-21  
**実施予定**: 2026-07-23〜07-27  
**前提条件**: R0-v2-A 完了（current_mode.yaml 設定済み）  
**担当**: OpenClaw assistant  
**推定所要時間**: 2〜3時間  

---

## 背景・修正内容

### 確認済みの問題（実データ監査 2026-07-21）

| 問題 | 件数 | 根本原因 |
|------|------|---------|
| closed/quarantine overlap | 41件 | migrate_quarantine が state.trades から削除し忘れ |
| entry_time > exit_time (逆転) | 62件 (うち closed-only 39件) | rebuild FIFO lot 割当誤り |
| holding_days = None | 245件 | fix1後: 204件、entry/exit_timeから計算可能 |
| PnL 二重計上 | overlap 41件分 | overlap 除去で修正される |

### 修正後の予測値

| 指標 | 現在 | 修正後 |
|------|------|--------|
| closed trades | 259件 | 218件 (41件削除) |
| quarantine overlap | 41件 | 0件 |
| reversed chronology | 62件 | 0件 |
| holding_days missing | 245件 | 0件 |
| 公式 realized PnL | -$103,310 | **-$64,836** |

---

## 実施手順

### STEP 0: 事前確認（実施当日の朝）

```bash
cd ~/stock_swing

# 0-1. circuit breaker が ok であることを確認
cat data/guardrails/circuit_breaker.json | python3 -m json.tool | grep status

# 0-2. 本日の cron が全て完了していることを確認（market_close 後に実施）
# US market close: 16:00 ET = 05:00 JST 翌朝
# 実施推奨時間: 平日 06:00〜08:00 JST（daily_audit 完了後）

# 0-3. 現在の integrity status を確認
source venv/bin/activate
python3 scripts/verify_rebuild_integrity.py
# 期待結果: 3 issues (overlap=41, reversed=62, hd=245)
```

### STEP 1: バックアップ作成

```bash
cd ~/stock_swing && source venv/bin/activate

python3 scripts/backup_pnl_state.py 2>/dev/null || \
  cp data/tracking/pnl_state.json \
     data/tracking/pnl_state.backup_r0v2b_$(date +%Y%m%d_%H%M%S).json

echo "Backup created"
```

### STEP 2: fix1 — overlap 41件を closed から除去

```bash
python3 << 'EOF'
import json
from pathlib import Path

state = json.loads(Path('data/tracking/pnl_state.json').read_text())
trades = state.get('trades', [])
quar_ids = {t.get('trade_id') for t in state.get('quarantined_trades', [])}

before = len([t for t in trades if t.get('status') == 'closed'])
# overlap している closed を state.trades から除去
new_trades = [t for t in trades
              if not (t.get('status') == 'closed' and t.get('trade_id') in quar_ids)]
removed = len(trades) - len(new_trades)

# PnL を再計算（除去した分を引く）
removed_pnl = sum(t.get('pnl', 0) or 0 for t in trades
                  if t.get('status') == 'closed' and t.get('trade_id') in quar_ids)

state['trades'] = new_trades
state['cumulative_realized_pnl'] = round(
    state.get('cumulative_realized_pnl', 0) - removed_pnl, 2
)

import json, tempfile, os
tmp = Path('data/tracking/pnl_state_fix1.json')
tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False))
print(f"fix1 dry-run: removed {removed} overlap trades (pnl: ${removed_pnl:+,.2f})")
print(f"  closed: {before} → {len([t for t in new_trades if t.get('status')=='closed'])}")
print(f"  new cumulative_realized_pnl: ${state['cumulative_realized_pnl']:+,.2f}")
print(f"  Written to: {tmp} (review before applying)")
EOF
```

**確認後、適用**:
```bash
cp data/tracking/pnl_state_fix1.json data/tracking/pnl_state.json
echo "fix1 applied"
```

### STEP 3: fix2 — 逆転 closed-only 39件を quarantine に移動

```bash
python3 << 'EOF'
import json
from pathlib import Path
from datetime import datetime

state = json.loads(Path('data/tracking/pnl_state.json').read_text())
trades = state.get('trades', [])
quar_ids = {t.get('trade_id') for t in state.get('quarantined_trades', [])}

reversed_closed_only = []
for t in trades:
    if t.get('status') != 'closed' or t.get('trade_id') in quar_ids:
        continue
    et, xt = t.get('entry_time', ''), t.get('exit_time', '')
    if not et or not xt:
        continue
    try:
        e = datetime.fromisoformat(str(et).replace('Z', '+00:00'))
        x = datetime.fromisoformat(str(xt).replace('Z', '+00:00'))
        if e > x:
            reversed_closed_only.append(t)
    except Exception:
        pass

print(f"fix2: found {len(reversed_closed_only)} reversed closed-only trades")
for t in reversed_closed_only[:5]:
    print(f"  {t.get('trade_id')} {t.get('symbol')} entry={str(t.get('entry_time',''))[:10]} exit={str(t.get('exit_time',''))[:10]}")
if len(reversed_closed_only) > 5:
    print(f"  ... and {len(reversed_closed_only)-5} more")

# quarantine に移動
rev_ids = {t.get('trade_id') for t in reversed_closed_only}
for t in reversed_closed_only:
    t['quarantine_reason'] = f"r0v2b_reversed_chronology: entry_time > exit_time"
    t['status'] = 'quarantined'

state['quarantined_trades'] = state.get('quarantined_trades', []) + reversed_closed_only
state['trades'] = [t for t in state['trades'] if t.get('trade_id') not in rev_ids]

# PnL 再計算
removed_pnl2 = sum(t.get('pnl', 0) or 0 for t in reversed_closed_only)
state['cumulative_realized_pnl'] = round(
    state.get('cumulative_realized_pnl', 0) - removed_pnl2, 2
)

tmp = Path('data/tracking/pnl_state_fix2.json')
tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False))
print(f"fix2 dry-run: moved {len(reversed_closed_only)} trades to quarantine")
print(f"  pnl removed: ${removed_pnl2:+,.2f}")
print(f"  new cumulative_realized_pnl: ${state['cumulative_realized_pnl']:+,.2f}")
print(f"  Written to: {tmp}")
EOF
```

**確認後、適用**:
```bash
cp data/tracking/pnl_state_fix2.json data/tracking/pnl_state.json
echo "fix2 applied"
```

### STEP 4: fix3 — holding_days を entry/exit_time から計算

```bash
python3 << 'EOF'
import json
from pathlib import Path
from datetime import datetime

state = json.loads(Path('data/tracking/pnl_state.json').read_text())
trades = state.get('trades', [])

fixed = 0
for t in trades:
    if t.get('status') != 'closed' or t.get('holding_days') is not None:
        continue
    et, xt = t.get('entry_time', ''), t.get('exit_time', '')
    if not et or not xt:
        continue
    try:
        e = datetime.fromisoformat(str(et).replace('Z', '+00:00'))
        x = datetime.fromisoformat(str(xt).replace('Z', '+00:00'))
        hd = round((x - e).total_seconds() / 86400, 4)
        if hd >= 0:
            t['holding_days'] = hd
            fixed += 1
    except Exception:
        pass

still_missing = sum(1 for t in trades if t.get('status') == 'closed' and t.get('holding_days') is None)

tmp = Path('data/tracking/pnl_state_fix3.json')
tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False))
print(f"fix3 dry-run: computed holding_days for {fixed} trades")
print(f"  still missing: {still_missing} (acceptable if 0)")
print(f"  Written to: {tmp}")
EOF
```

**確認後、適用**:
```bash
cp data/tracking/pnl_state_fix3.json data/tracking/pnl_state.json
echo "fix3 applied"
```

### STEP 5: invariant 検証（全て PASS であることを確認）

```bash
python3 scripts/verify_rebuild_integrity.py
# 期待結果: "All checks passed" または warning なし
```

**PASS しない場合**: 即座に STEP 1 のバックアップに戻す:
```bash
# ロールバック
cp data/tracking/pnl_state.backup_r0v2b_*.json data/tracking/pnl_state.json
```

### STEP 6: console 再起動

```bash
cd ~/stock_swing && bash console/manage.sh restart
```

### STEP 7: 最終確認

```bash
# 7-1. integrity
python3 scripts/verify_rebuild_integrity.py

# 7-2. ledger quality report
python3 -c "
from stock_swing.tracking.pnl_tracker import PnLTracker
from pathlib import Path
import json
t = PnLTracker(Path('.'))
print(json.dumps(t.get_ledger_quality_report(), indent=2))
"
# 期待: negative_holding_days_in_clean=0, no_exit_attribution=3以下, attribution_coverage_pct≥98

# 7-3. PnL 確認
python3 -c "
import json
from pathlib import Path
s = json.loads(Path('data/tracking/pnl_state.json').read_text())
trades = s.get('trades', [])
closed = [t for t in trades if t.get('status')=='closed']
print(f'closed: {len(closed)}')
print(f'cumulative_realized_pnl: \${s.get(\"cumulative_realized_pnl\",0):+,.2f}')
print(f'sum(closed.pnl): \${sum(t.get(\"pnl\",0) or 0 for t in closed):+,.2f}')
"
# 期待: closed≈218, PnL≈-$64,836, sum=cumulative(差分$0)
```

---

## 受け入れ基準

| 基準 | 期待値 | 確認方法 |
|------|--------|---------|
| closed/quarantine overlap | **0件** | verify_rebuild_integrity.py |
| reversed chronology | **0件** | verify_rebuild_integrity.py |
| holding_days missing | **0件** | verify_rebuild_integrity.py |
| PnL consistency | **diff ≤ $1** | verify_rebuild_integrity.py |
| closed trade 件数 | **≈218件** | python3 確認スクリプト |
| attribution coverage | **≥98%** | get_ledger_quality_report() |
| console health | **OK** | curl localhost:3335/health |

**全て満たした場合のみ R0-v2-B = VERIFIED_COMPLETE**

---

## 懸念1・2の対処（2026-07-21 実装済み）

### 懸念1: rebuild が再び attribution を破壊しないか

**対処**: `--preserve-attribution` をデフォルト True に変更 (commit ef3b17f+)
- `--no-preserve-attribution` には `--force` が必要
- 誤って attribution を消すことはできなくなった

### 懸念2: invariant が外側のテストにしかない

**対処**: `verify_rebuild_integrity.py` に4つの invariant check を追加 (commit ef3b17f+)
- `check_closed_quarantine_overlap`
- `check_reversed_chronology`
- `check_holding_days_missing`
- `check_pnl_consistency`
- rebuild スクリプトが必ず verify を呼ぶ

---

## ロールバック手順

問題が発生した場合:
```bash
# 1. バックアップに戻す
ls -lt data/tracking/pnl_state_backup_r0v2b_*.json | head -1
cp data/tracking/pnl_state_backup_r0v2b_XXXXXXXX_XXXXXX.json data/tracking/pnl_state.json

# 2. console 再起動
bash console/manage.sh restart

# 3. integrity 再確認
python3 scripts/verify_rebuild_integrity.py
```

---

## 実施時の注意事項

1. **US market close 後に実施** (日本時間 05:00 JST 以降)
2. **daily_audit cron 完了後** (06:00 JST 以降)
3. **各 STEP の dry-run ファイルを必ず確認してから本適用**
4. **STEP 5 で invariant が全て PASS しない場合は即ロールバック**
5. **修正後に attribution coverage が 98% 以上であることを確認**
