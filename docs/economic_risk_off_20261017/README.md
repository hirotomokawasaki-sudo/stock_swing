# Economic Risk-Off Separation (2026-10-17)

## Decision

The operational circuit breaker remains the manually latched safety control
for broker/tracker mismatches and missing critical evidence. Economic drawdown
is implemented as a separate, recoverable state machine.

Phase 1 is **shadow-only**. It does not clear the current HALT, change order
quantities, or block a BUY. The legacy daily/weekly loss rules remain enforced
until a later explicit promotion decision.

## Metric

`rolling_session_total_loss_pct` uses:

```text
(latest broker equity
 - equity at the start of the oldest session
 - cumulative external cash-flow change)
/ equity at the start of the oldest session * 100
```

- Window: five consecutive NYSE sessions, not UTC calendar days.
- Broker equity includes both realized and unrealized PnL.
- External cash flow comes from the audited equity-bridge reconciliation and
  must match the active broker account.
- A missing session, invalid equity, corrupt state, or unavailable cash-flow
  evidence makes the metric unavailable instead of silently assuming zero.

## State Machine

| Entry threshold | State | Intended enforced action |
|---|---|---|
| above -4% | `normal` | allow |
| at or below -4% | `reduce_size` | 0.5x new-risk size |
| at or below -6% | `block_buys` | block new BUYs; risk exits continue |
| at or below -8% | `halt_new_risk` | suspend new risk; risk exits continue |

Recovery is deliberately slower than escalation:

- `halt_new_risk` requires two distinct sessions above -6.5%, then steps down
  only to `block_buys`.
- `block_buys` requires two distinct sessions above -4.5%, then steps down
  only to `reduce_size`.
- `reduce_size` requires two distinct sessions above -3.0%, then returns to
  `normal`.
- Multiple runs in one market session count only once.

The economic state never mutates or clears `CircuitBreakerStore`.

## Historical Replay

The first and last broker-account observations for 2026-10-12 through
2026-10-16 were replayed:

```text
window-start equity: $1,006,668.06
window-end equity:     $930,072.28
cash-flow adjustment:       $0.00
metric:                    -7.6088%
new state:              block_buys
```

The old realized-only rule originally latched the operational circuit breaker
at -6.1043%. Under the new design the episode is still treated as serious, but
it remains an automatically recoverable economic risk state instead of an
operational-integrity incident.

## Observability

- State: `data/guardrails/economic_risk_off.json`
- Config: `config/guardrails/autonomous_stop.yaml`
- Console: `health.economic_risk_off` and the `ECONOMIC RISK-OFF` panel
- Dry runs preview the calculation but do not mutate the evidence state.
- The circuit breaker now preserves original trigger evidence and separately
  records `latest_decision_action` / `latest_triggered_rules` while latched.

## Promotion Gate

Initial review: **2026-11-02**, after ten scheduled NYSE sessions.
Automation: `stock_swing_economic_risk_off_shadow_review_20261102`
(`335e947e-a192-4c98-b3ab-3579ec9db3ba`, registration verified via API get).

Enforcement must not be enabled unless all of the following hold:

1. Ten consecutive sessions have `data_status=ready` with no account or
   cash-flow evidence mismatch.
2. Shadow state transitions match independent broker-equity replay.
3. Blocked-trade opportunity cost and drawdown reduction are reported
   together; drawdown reduction alone is insufficient.
4. Operational mismatch HALTs remain manually latched and independent.
5. A separate user approval changes `mode: shadow` to `mode: enforce`.

An interim review may continue observation without promotion when there are
too few independent drawdown episodes.

## Verification

- Dedicated state/config/history tests
- 2026-10-16 weekly-loss regression
- 2026-10-12 through 2026-10-16 broker-equity replay
- Persistence, corrupt-file, missing-session, holiday, cash-flow, escalation,
  recovery-hysteresis, console-contract, and renderer tests
