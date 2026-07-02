# Go/No-Go Checklist for 2026-08-01 Live Switch

**Created**: 2026-07-02
**Decision date**: 2026-07-31
**Scope**: Paper to live transition readiness

Any critical item marked `NO-GO` blocks live trading until resolved.

---

## Critical Gates

| Gate | Status | Evidence | Result |
|---|---|---|---|
| Guardrail hard-halt enabled | READY | `config/guardrails/autonomous_stop.yaml`: `paper_warning_only: false` | GO |
| Circuit breaker status OK | CHECK ON 07-31 | `data/guardrails/circuit_breaker.json` status must be `ok` | TBD |
| Broker/Tracker mismatch | CHECK DAILY | latest console `broker_tracker_diff.mismatch_count == 0` | TBD |
| Reconcile job health | CHECK DAILY | all stock_swing cron jobs `lastRunStatus=ok` | TBD |
| Attribution completeness | READY | post-R1-B attribution reached 100% | GO |
| Exit strategy reviewed | READY | R3-B replay completed 2026-07-02 | GO |
| Emergency stop runbook | READY | `docs/runbooks/emergency_stop.md` | GO |
| Live switch runbook | READY | `docs/runbooks/live_mode_switch.md` | GO |

---

## Performance Gates

| Gate | Threshold | Result |
|---|---|---|
| Overall PF | >= 1.20 preferred | CHECK ON 07-31 |
| ETF PF | Separate from stock PF, no mixed-only decision | CHECK ON 07-31 |
| Stock PF | Must not silently dilute ETF performance | CHECK ON 07-31 |
| Post-R1-B closed trades | >= 20 preferred | CHECK ON 07-31 |
| Unknown exit attribution | 0 preferred | CHECK ON 07-31 |

---

## Safety Gates

| Gate | Requirement | Result |
|---|---|---|
| Initial size | 2026-08-01 to 2026-08-14 uses 50% size | TBD |
| Remote monitoring | R6-F or documented substitute available | TBD |
| Manual stop access | Operator can execute emergency stop steps | TBD |
| Telegram/notification path | Trade and halt notifications visible | TBD |
| Rollback path | Paper rollback command verified | TBD |

---

## Implementation State

| Area | State | Notes |
|---|---|---|
| R0 Guardrails | DONE | hard-halt enabled and calibration documented |
| R1 Exit attribution | DONE | broker_fill_unknown removed from current attribution |
| R2 ETF/Stock split | DONE | separate console metrics and entry filters |
| R3 Exit replay | DONE | staged trailing was best first-pass variant |
| R4 Signal strength | PARTIAL | Option A deployed; R4-C decile validation remains |
| R6 Console | PARTIAL | C1/C2/D/E done; R6-F remote web remains |

---

## Final Decision Record

Fill this on 2026-07-31.

```
Decision: GO / NO-GO
Decision time:
Operator:
Blocking issues:
Approved initial size:
Rollback owner:
Notes:
```
