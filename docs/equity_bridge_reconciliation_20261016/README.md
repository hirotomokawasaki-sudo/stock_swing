# Equity bridge reconciliation (2026-10-16)

## Conclusion

The previously reported `$50,761.53` unexplained difference was not a current
position mismatch. It combined a clean broker/tracker difference of about
`$6.1K` with `-$44,670.42` of reconstruction-corrupt quarantine P&L.

The quarantine rows contain reversed chronology and split-scale values. In
particular, the KLAC row records a pre-split entry price against a post-split
exit price and contributes `-$39,341.89`. Raw quarantine P&L is therefore kept
visible but is no longer treated as economic truth without independent proof.

## Independent reconciliation

The new reconciliation uses a split-invariant accounting identity:

```text
broker gross realized P&L
  = filled SELL proceeds - filled BUY costs + current open cost basis
```

Live paper-account result:

| Component | USD |
|---|---:|
| Tracker realized | -56,841.92 |
| Broker order-cash realized | -50,635.06 |
| Audited realized adjustment | +6,206.86 |
| Historical broker fees | 94.58 |
| External cash after baseline | 0.00 |
| Raw quarantined P&L | -44,670.42 |
| Verified quarantine adjustment | 0.00 |

The independent account equation reproduced broker equity to `$0.01`:

```text
$1,000,000 baseline
+ $0 external cash
- $50,635.06 broker gross realized
- $11,916.01 broker unrealized
- $94.58 fees
= $937,354.35 expected equity
vs $937,354.36 broker equity
```

The largest realized-P&L source difference is KLAC (`+$5,462.20` broker minus
tracker), confirming that corporate-action/FIFO history dominates the old
bridge residual.

## Implementation

- `scripts/reconcile_equity_bridge.py` builds the reconciliation read-only by
  default. `--save` atomically updates
  `data/audits/equity_bridge_reconciliation.json` only after the independent
  account equation is within `$25`.
- `paper_demo` loads the artifact only when schema, baseline, account identity,
  account-check tolerance, and the closed-trade history fingerprint all pass.
  Rewriting historical tracker rows therefore invalidates the adjustment until
  the read-only reconciliation is rerun.
- The strategy ledger (`pnl_state.json`), trade attribution, orders, and
  performance cohorts are not rewritten.
- Raw quarantine P&L remains in the console as a reference value; only an
  explicitly verified `quarantined_pnl_adjustment` affects bridge arithmetic.

## Reproduction

```bash
cd ~/stock_swing
source venv/bin/activate
python scripts/reconcile_equity_bridge.py
python scripts/reconcile_equity_bridge.py --save
```
