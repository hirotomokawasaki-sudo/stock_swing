# RUNTIME_MODES.md

Runtime mode is a hard control surface. It is not a cosmetic label.
If runtime mode is unclear, inconsistent, or missing, the system must fail closed.

## 1. Modes
### `research`
Purpose:
- data collection
- normalization testing
- feature engineering
- report generation
- prompt experimentation
- backtesting support
- dry decision generation without execution

Allowed:
- source ingestion
- normalization
- feature computation
- strategy signal generation
- decision simulation
- reporting
- OpenClaw orchestration and summaries

Not allowed:
- broker order submission
- live order amendment
- any irreversible trade action

### `paper`
Purpose:
- end-to-end flow validation without real capital risk
- simulated trading behavior
- operator workflow rehearsal

Allowed:
- source ingestion
- normalization
- features
- signals
- decision generation
- paper broker submission
- paper reconciliation
- alerts and reports

Not allowed:
- live order submission
- mixing live and paper account truth

### `live_guarded`
Purpose:
- tightly controlled live execution with explicit guardrails

Required controls:
- explicit operator approval where configured
- active risk veto path
- duplicate-order suppression
- clear audit chain
- restricted strategy set
- pre-approved symbols and position rules

### `live`
Purpose:
- approved live trading operation under defined governance

Still required:
- risk vetoes
- reconciliation
- auditing
- runtime logging
- strict config discipline

## 2. Default behavior
If runtime mode is missing, unreadable, or invalid:
- execution must be denied
- the system should behave as if in a non-executable safe state
- an audit event must be emitted

Recommended default operational assumption: `research`
Recommended execution assumption: `deny`

## 3. Promotion rules
Preferred path:
`research -> paper -> live_guarded -> live`

Before promotion:
- schemas must be stable
- audit chain must be intact
- risk rules must be active
- source freshness checks must pass
- execution reconciliation must be verified
- operator approval policy must be explicit

## 4. Demotion rules
Demote or deny execution when:
- broker connectivity failure
- stale or missing critical data
- reconciliation mismatch
- duplicate decision ambiguity
- corrupted runtime configuration
- unresolved audit integrity failure
- risk module unavailable
- unknown runtime mode state

## 5. Initial recommendation
Enable only:
- `research`
- `paper`

Document `live_guarded` and `live`, but keep them operationally disabled until execution policy, risk policy, reconciliation, and recovery are validated.
