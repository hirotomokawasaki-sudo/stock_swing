# DECISION_SCHEMA.md

Defines the final decision output after strategy, risk, and runtime checks.

## 1. Decision record
```json
{
  "decision_id": "uuid-or-hash",
  "schema_version": "v1",
  "generated_at": "2026-03-06T14:12:00Z",
  "mode": "research|paper|live_guarded|live",
  "strategy_id": "event_swing_v1",
  "symbol": "AAPL",
  "action": "buy|sell|hold|deny|review",
  "confidence": 0.72,
  "signal_strength": 0.81,
  "risk_state": "pass|deny|review",
  "deny_reasons": [],
  "requires_operator_approval": true,
  "time_horizon": "intraday|1d|2d|3d|1w",
  "evidence": {
    "feature_refs": [],
    "raw_refs": [],
    "notes": []
  },
  "proposed_order": {
    "symbol": "AAPL",
    "side": "buy",
    "order_type": "market|limit",
    "qty": 10,
    "time_in_force": "day"
  }
}
```

## 2. Rules
- `action=deny` must include at least one deny reason.
- `mode` must match runtime config.
- `proposed_order` must be null or absent when `action` is `deny` or `hold`.
- `requires_operator_approval` should default true in `live_guarded`.
- decision output is actionable only after decision-engine validation.
