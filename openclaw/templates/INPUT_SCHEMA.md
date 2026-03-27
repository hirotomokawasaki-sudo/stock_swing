# INPUT_SCHEMA.md

## Purpose
Defines the input contract passed from the application into OpenClaw-facing review prompts.

## Minimum shape
```json
{
  "version": "v1",
  "runtime_mode": "research|paper|live_guarded|live",
  "candidate": {
    "symbol": "AAPL",
    "strategy_id": "event_swing_v1",
    "signal_strength": 0.74,
    "evidence": []
  },
  "risk": {
    "risk_state": "pass|deny|review",
    "deny_reasons": []
  }
}
```
