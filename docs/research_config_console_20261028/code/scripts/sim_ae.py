import json, statistics
from datetime import timedelta
from dateutil import parser as dparser
import yfinance as yf

with open('data/tracking/pnl_state.json') as f:
    state = json.load(f)
trades = state.get('trades', [])
sl = [t for t in trades
      if t.get('status') == 'closed'
      and t.get('exit_reason') == 'stop_loss'
      and (t.get('pnl') or 0) < 0
      and t.get('exit_time')]

rows = []
for t in sl:
    sym = t.get('symbol', '?')
    ep  = t.get('entry_price') or 0
    xp  = t.get('exit_price')  or 0
    qty = t.get('qty') or 0
    pnl = t.get('pnl') or 0
    ret = (t.get('return_pct') or 0) * 100
    exit_date = dparser.parse(t.get('exit_time', '')).date()
    start = (exit_date + timedelta(days=1)).isoformat()
    end   = (exit_date + timedelta(days=65)).isoformat()
    try:
        hist = yf.Ticker(sym).history(start=start, end=end, interval='1d')
        if hist.empty:
            continue
        prices = [float(r['Close']) for _, r in hist.iterrows()]
        NEVER = 9999
        rec_day = NEVER
        for i, p in enumerate(prices):
            if ep > 0 and p >= ep:
                rec_day = i + 1
                break
        rows.append({
            'sym': sym, 'ep': ep, 'xp': xp, 'qty': qty,
            'pnl': pnl, 'ret': ret, 'prices': prices,
            'exit_date': str(exit_date),
            'recovery_day': rec_day,
            'has30': len(prices) >= 30,
        })
    except Exception:
        pass

judg = [r for r in rows if r['has30']]


def min_hold_days(ret):
    if ret > -5.0:
        return 7
    elif ret > -8.0:
        return 3
    else:
        return 1


def simulate(rows, trail_pct=None):
    total = 0
    details = []
    for r in rows:
        ret = r['ret']
        prices = r['prices']
        ep = r['ep']
        xp = r['xp']
        qty = r['qty']
        actual = r['pnl']
        wait = min_hold_days(ret)

        if wait <= 1 or len(prices) < wait:
            total += actual
            details.append({'sym': r['sym'], 'pnl': actual, 'mode': 'immediate', 'ret': ret})
            continue

        if trail_pct is None:
            p_exit = prices[wait - 1]
        else:
            peak = xp
            tf = peak * (1 - trail_pct)
            p_exit = prices[min(wait - 1, len(prices) - 1)]
            for i in range(min(wait, len(prices))):
                p = prices[i]
                if p > peak:
                    peak = p
                    tf = peak * (1 - trail_pct)
                if p <= tf:
                    p_exit = p
                    break

        trade_pnl = (p_exit - ep) * qty if ep and qty else actual
        total += trade_pnl
        details.append({
            'sym': r['sym'], 'pnl': trade_pnl, 'actual': actual,
            'mode': 'wait', 'ret': ret, 'wait': wait,
            'exit_date': r['exit_date'],
        })
    return total, details


actual_total = sum(r['pnl'] for r in rows)
a_total,   a_det   = simulate(rows, trail_pct=None)
ae3_total, ae3_det = simulate(rows, trail_pct=0.03)
ae5_total, ae5_det = simulate(rows, trail_pct=0.05)

print("=== A+E simulation (all %d trades) ===" % len(rows))
print()
print("  Current stop-loss       :  %+9.0f" % actual_total)
print("  Plan A  (min_hold only) :  %+9.0f  (gain: %+.0f)" % (a_total,   a_total   - actual_total))
print("  Plan A+E trail-3pct     :  %+9.0f  (gain: %+.0f)" % (ae3_total, ae3_total - actual_total))
print("  Plan A+E trail-5pct     :  %+9.0f  (gain: %+.0f)" % (ae5_total, ae5_total - actual_total))
print()

actual_j = sum(r['pnl'] for r in judg)
a_j,   _   = simulate(judg, trail_pct=None)
ae3_j, d3  = simulate(judg, trail_pct=0.03)
ae5_j, d5  = simulate(judg, trail_pct=0.05)

print("=== confirmed data only (%d trades) ===" % len(judg))
print("  Current stop-loss       :  %+9.0f" % actual_j)
print("  Plan A                  :  %+9.0f  (gain: %+.0f)" % (a_j,   a_j   - actual_j))
print("  Plan A+E trail-3pct     :  %+9.0f  (gain: %+.0f)" % (ae3_j, ae3_j - actual_j))
print("  Plan A+E trail-5pct     :  %+9.0f  (gain: %+.0f)" % (ae5_j, ae5_j - actual_j))
print()

# per-trade detail
print("=== per-trade: Plan A vs A+E(-3pct), wait-trades only ===")
print("%-8s %-10s %6s %4s  %+9s  %+9s  %+8s  %s" % (
    "Symbol", "ExitDate", "ret%", "wait", "Plan-A", "A+E", "diff", "verdict"))
for r in sorted(judg, key=lambda x: x['ret']):
    wait = min_hold_days(r['ret'])
    if wait <= 1:
        continue
    prices = r['prices']
    ep = r['ep']
    xp = r['xp']
    qty = r['qty']
    if len(prices) < wait:
        continue

    p_a = prices[wait - 1]
    pnl_a = (p_a - ep) * qty if ep and qty else r['pnl']

    peak = xp
    tf = peak * 0.97
    p_ae = prices[min(wait - 1, len(prices) - 1)]
    for i in range(min(wait, len(prices))):
        p = prices[i]
        if p > peak:
            peak = p
            tf = peak * 0.97
        if p <= tf:
            p_ae = p
            break
    pnl_ae = (p_ae - ep) * qty if ep and qty else r['pnl']

    diff = pnl_ae - pnl_a
    verdict = "AE-better" if diff > 200 else ("A-better" if diff < -200 else "same")
    print("  %-8s %-10s  %+5.1f%%  %2dd   %+9.0f   %+9.0f   %+8.0f  %s" % (
        r['sym'], r['exit_date'], r['ret'], wait,
        pnl_a, pnl_ae, diff, verdict))

print()
print("=== Worst-case comparison ===")
worst_actual = min(r['pnl'] for r in rows)
cands_a = [
    (r['prices'][min_hold_days(r['ret']) - 1] - r['ep']) * r['qty']
    for r in rows
    if r['ep'] and r['qty'] and len(r['prices']) >= min_hold_days(r['ret'])
]
cands_ae3 = []
for r in rows:
    wait = min_hold_days(r['ret'])
    if wait <= 1 or not r['ep'] or not r['qty'] or len(r['prices']) < wait:
        continue
    peak = r['xp']
    tf = peak * 0.97
    p_ae = r['prices'][min(wait - 1, len(r['prices']) - 1)]
    for i in range(min(wait, len(r['prices']))):
        p = r['prices'][i]
        if p > peak:
            peak = p
            tf = peak * 0.97
        if p <= tf:
            p_ae = p
            break
    cands_ae3.append((p_ae - r['ep']) * r['qty'])

print("  Current worst single trade  : %+.0f" % worst_actual)
print("  Plan A  worst single trade  : %+.0f" % (min(cands_a)   if cands_a   else 0))
print("  Plan A+E worst single trade : %+.0f" % (min(cands_ae3) if cands_ae3 else 0))
print()

wait_a   = [x for x in a_det   if x['mode'] == 'wait']
wait_ae3 = [x for x in ae3_det if x['mode'] == 'wait']
ae_better = sum(1 for a, ae in zip(wait_a, wait_ae3) if ae['pnl'] > a['pnl'] + 100)
a_better  = sum(1 for a, ae in zip(wait_a, wait_ae3) if a['pnl']  > ae['pnl'] + 100)
same_n    = len(wait_a) - ae_better - a_better
print("=== wait-trades %d: A vs A+E(-3pct) ===" % len(wait_a))
print("  A+E better: %d" % ae_better)
print("  A   better: %d" % a_better)
print("  same      : %d" % same_n)
