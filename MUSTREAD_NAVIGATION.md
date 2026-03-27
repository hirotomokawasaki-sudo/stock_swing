# MUSTREAD_NAVIGATION.md

This document is the primary navigation map for the `stock_swing` system.
All contributors must read this file before adding code, prompts, tasks, or runtime behavior.

## 0. One-line summary
- The real trading critical path must remain deterministic.
- OpenClaw is an orchestration and interpretation layer, not the source of trading truth.
- Broker/execution state is the source of truth for orders, fills, and positions.
- FRED, SEC, Finnhub, and broker price feeds are input sources, not direct decision makers.
- Directory structure and module boundaries are hard constraints, not suggestions.

## 1. System purpose
This system is designed for:
- U.S. stocks and ETFs
- Cash-only or non-negative exposure structures
- No options as a core strategy
- No futures, no margin-dependent negative balance structures
- Event-driven swing trading
- Short-term momentum / breakout strategies
- OpenClaw-assisted orchestration, summaries, and operator workflows
- Deterministic risk and execution controls

This system is not designed for:
- High-frequency trading
- Tick-level latency competition
- Fully autonomous LLM-driven order submission
- Strategy logic embedded directly in prompts
- Ad-hoc file creation without schema contracts

## 2. Project root layout
Recommended project layout:

```text
~/stock_swing/
├── MUSTREAD_NAVIGATION.md
├── GOVERNANCE.md
├── RUNTIME_MODES.md
├── README.md
├── pyproject.toml
├── .env
├── .env.example
├── docs/
│   ├── architecture/
│   ├── schemas/
│   ├── policies/
│   ├── runbooks/
│   └── decisions/
├── config/
│   ├── environments/
│   ├── runtime/
│   ├── sources/
│   └── strategy/
├── data/
│   ├── raw/
│   │   ├── broker/
│   │   ├── finnhub/
│   │   ├── fred/
│   │   └── sec/
│   ├── normalized/
│   ├── features/
│   ├── signals/
│   ├── decisions/
│   ├── audits/
│   └── archive/
├── src/
│   ├── core/
│   ├── sources/
│   ├── ingestion/
│   ├── normalization/
│   ├── feature_engine/
│   ├── strategy_engine/
│   ├── decision_engine/
│   ├── execution/
│   ├── risk/
│   ├── storage/
│   ├── reporting/
│   ├── openclaw/
│   └── cli/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   └── fixtures/
├── ops/
│   ├── schedules/
│   ├── watchdog/
│   ├── logs/
│   └── healthchecks/
└── openclaw/
    ├── prompts/
    ├── templates/
    ├── agent_inputs/
    ├── agent_outputs/
    └── skills/
```

## 3. Boundary with `~/.openclaw`
`~/.openclaw/` is the OpenClaw runtime home.
It may contain:
- OpenClaw configuration
- agent sessions
- local runtime state
- OpenClaw-managed workspaces

It must not be treated as the authoritative home of the `stock_swing` project.
The `stock_swing` application must live in its own root directory, such as `~/stock_swing`.
Project-owned OpenClaw assets may exist under `~/stock_swing/openclaw/`.

## 4. Directory meaning
- `docs/`: human-readable contracts, policies, architecture notes, and runbooks.
- `config/`: machine-readable configuration for runtime behavior, source settings, strategy switches, and environments.
- `data/raw/`: immutable source snapshots from external providers. Raw data must never be silently overwritten.
- `data/normalized/`: canonical internal schema outputs derived from raw data.
- `data/features/`: computed factors, scores, rankings, and derived metrics.
- `data/signals/`: strategy-generated candidate signals.
- `data/decisions/`: final pass/fail actionability outputs after risk and runtime checks.
- `data/audits/`: audit logs, execution traces, validation failures, and safety events.
- `src/`: application code only.
- `ops/`: operational scripts, health checks, watchdog logic, and schedule management.
- `openclaw/`: OpenClaw-facing prompts, templates, schemas, and skill assets.

## 5. Mandatory module boundaries
- `src/sources/`: external API clients only.
- `src/ingestion/`: controls what gets collected and when, writes source snapshots.
- `src/normalization/`: transforms raw provider payloads into canonical internal records.
- `src/feature_engine/`: builds derived metrics and scores.
- `src/strategy_engine/`: generates strategy-level candidate signals.
- `src/risk/`: deny-first protections and hard limits.
- `src/decision_engine/`: transforms candidate signals into actionable decisions.
- `src/execution/`: broker-facing order submission and reconciliation.
- `src/storage/`: owns persistence contracts.
- `src/reporting/`: summaries, reports, post-trade reviews.
- `src/openclaw/`: application-side adapters for OpenClaw integration.

## 6. Critical path
`source data -> normalization -> feature_engine -> strategy_engine -> risk -> decision_engine -> execution -> audit`

Anything outside that path is non-critical support logic.
OpenClaw-generated text is not part of the execution truth path.

## 7. Sources of truth
- Trading truth: broker order state, fills, positions, execution reconciliation records.
- Market and macro truth: broker price feed, FRED, SEC, Finnhub.
- System truth: runtime mode, audit logs, decision outputs, execution reconciliation outputs.
- Non-truth: free-form LLM text, ad-hoc spreadsheets, chat messages.

## 8. Prohibited patterns
- writing new JSON files to arbitrary paths
- mixing raw and normalized data in the same directory
- strategy modules calling broker APIs directly
- prompts choosing storage paths
- risk logic hidden inside prompt text only
- execution logic embedded in notebooks or one-off scripts
- silent fallback behavior that changes trading intent
- relative path sprawl across unrelated modules

## 9. Mandatory reading order
1. `MUSTREAD_NAVIGATION.md`
2. `GOVERNANCE.md`
3. `RUNTIME_MODES.md`
4. `docs/architecture/SYSTEM_OVERVIEW.md`
5. `docs/schemas/CANONICAL_SCHEMA.md`
6. `docs/schemas/SOURCE_MAPPING.md`
7. `docs/schemas/DECISION_SCHEMA.md`
8. `docs/policies/RISK_POLICY.md`
9. `docs/policies/EXECUTION_POLICY.md`
10. `docs/policies/STRATEGY_SCOPE.md`
11. `docs/runbooks/BOOTSTRAP.md`
12. `docs/runbooks/DAILY_OPERATIONS.md`
13. `docs/runbooks/RECOVERY.md`
14. `openclaw/prompts/README.md`
15. `openclaw/templates/INPUT_SCHEMA.md`
16. `openclaw/templates/OUTPUT_SCHEMA.md`

## 10. Recovery quickstart
1. Confirm runtime mode is not `live` unless explicitly intended.
2. Confirm no stale or duplicated actionable decisions exist.
3. Confirm broker connectivity and order reconciliation.
4. Confirm data freshness for broker, FRED, SEC, and Finnhub inputs.
5. Confirm risk veto state is clear.
6. Confirm audit logs contain no unresolved integrity failures.
7. Do not regenerate orders directly from chat outputs.
