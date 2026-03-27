# SYSTEM_OVERVIEW.md

## 1. Overview
`stock_swing` is a structured trading support and execution-control system for U.S. stocks and ETFs.
Its design goal is to create a system that remains understandable, auditable, and controllable while supporting:
- event-driven swing trading
- short-term momentum / breakout logic
- OpenClaw-assisted operational workflows
- deterministic risk and execution constraints

The system must remain functional even if OpenClaw is temporarily unavailable.

## 2. Core design stance
- LLMs are useful for interpretation, ranking support, summaries, and operator workflows.
- LLMs are not the source of trading truth.
- Market execution requires deterministic controls.
- Source data must be separated from derived decisions.
- Risk vetoes must be stronger than signal enthusiasm.
- Runtime mode must constrain behavior at all times.

## 3. Primary external inputs
### Broker / trading engine
Used for:
- prices
- bars / execution timing inputs
- order submission
- fill state
- position truth

### Finnhub
Used for:
- structured fundamentals
- earnings calendar support
- insider transactions
- filing sentiment
- event-support metadata

### SEC
Used for:
- filing truth
- filing text
- filing timing
- direct source confirmation

### FRED
Used for:
- macro data
- regime classification support
- economic condition context

## 4. High-level data flow
```text
External Sources
    ↓
Raw Ingestion
    ↓
Normalization to Canonical Schema
    ↓
Feature Computation
    ↓
Strategy Signal Generation
    ↓
Risk Validation
    ↓
Decision Engine
    ↓
Execution / Reconciliation
    ↓
Audit / Reporting / OpenClaw Summaries
```

## 5. Layer responsibilities
- Raw ingestion: collect source payloads and preserve them in source-specific raw storage.
- Normalization: convert heterogeneous source payloads into internal canonical forms.
- Feature computation: generate reusable metrics from normalized data.
- Strategy signal generation: produce candidate signals according to strategy definitions.
- Risk validation: evaluate whether a candidate may proceed.
- Decision engine: generate final actionable or denied decisions with explanations.
- Execution: submit orders, reconcile fills, and preserve execution truth.
- Reporting and OpenClaw support: generate summaries, operator notes, explanations, and review artifacts.

## 6. Why OpenClaw is separated from the core
OpenClaw is valuable for:
- operator interaction
- multi-agent orchestration
- structured prompt workflows
- report assistance
- contextual interpretation

However, OpenClaw should not own:
- broker truth
- execution safety
- canonical storage authority
- final live-trade permission

Therefore:
- core application logic lives under `src/`
- OpenClaw-facing assets live under project-root `openclaw/`
- runtime OpenClaw state lives under `~/.openclaw/`

## 7. Strategy scope
### In scope
- event-driven swing trading
- short-term breakout / momentum
- stocks and ETFs
- long-only or non-negative loss-bounded implementation paths

### Out of scope for initial build
- options as a core strategy
- futures
- intraday high-frequency systems
- autonomous self-modifying strategies
- unrestricted symbol universe explosion

## 8. Safety model
The safety model is deny-first.
A strategy candidate is not enough. It must survive:
1. data completeness checks
2. freshness checks
3. risk checks
4. runtime mode checks
5. execution policy checks

If any of these fail, the result must be a denied or non-actionable decision.

## 9. Audit model
For every meaningful decision, the system should be able to reconstruct:
- which raw data was used
- how it was normalized
- which features were computed
- which strategy produced the candidate
- which risk checks passed or failed
- what final decision was generated
- what order, if any, was submitted
- what the broker returned

## 10. Initial implementation recommendation
Phase 1:
- finalize structure and contracts
- implement source ingestion
- implement canonical normalization
- implement feature generation
- implement paper-mode strategy flow

Phase 2:
- add decision engine
- add risk veto rules
- integrate paper execution and reconciliation
- add audit chain validation

Phase 3:
- harden operational controls
- add recovery runbooks
- prepare `live_guarded` but do not enable by default
