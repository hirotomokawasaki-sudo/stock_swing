# GOVERNANCE.md

This document defines structural governance for the `stock_swing` system.
Its goal is to prevent architecture drift, file sprawl, unsafe execution shortcuts, and undocumented schema changes.

## 0. Governance principles
1. Safety before convenience
2. Determinism before cleverness
3. Explicit contracts before implementation
4. Broker truth before internal assumptions
5. Deny-first risk controls before strategy expansion
6. Stable directories before feature growth
7. Reproducibility before speed of hacking

## 1. Ownership model
Each major area must have a clear owner.
- Architecture owner: top-level structure, boundaries, critical path.
- Data contract owner: canonical schemas, source mappings, versioning.
- Strategy owner: strategy definitions, signal semantics, eligibility criteria.
- Risk owner: hard limits, deny conditions, escalation rules.
- Execution owner: broker submission, reconciliation, order lifecycle integrity.
- Operations owner: schedules, health checks, recovery procedures.

## 2. Directory governance
Approved top-level directories:
- `docs/`
- `config/`
- `data/`
- `src/`
- `tests/`
- `ops/`
- `openclaw/`

Adding a new top-level directory requires explicit approval and documented reason.

Under `data/`, each directory serves one stage only:
- `raw/`
- `normalized/`
- `features/`
- `signals/`
- `decisions/`
- `audits/`
- `archive/`

Cross-stage mixing is prohibited.

## 3. File creation rules
A new file family may be created only if all are defined:
- purpose
- owner
- read path
- write path
- naming rule
- retention rule
- schema or format contract

No module may create arbitrary filenames based solely on prompt output.

## 4. Naming conventions
- use lowercase
- prefer snake_case
- avoid spaces
- avoid ambiguous names like `final.json`, `latest2.json`, `temp_new.json`

Data filenames should include stable attributes when appropriate:
- source
- date
- symbol
- schema version

Example:
- `finnhub_aapl_2026-03-06_v1.json`

## 5. Schema governance
All structured outputs must belong to one of:
- raw source schema
- canonical internal schema
- derived feature schema
- signal schema
- decision schema
- audit/event schema

Every non-trivial schema must be documented under `docs/schemas/`.
Silent schema changes are prohibited.

## 6. Code boundary rules
Preferred directional flow:
`sources -> ingestion -> normalization -> feature_engine -> strategy_engine -> risk/decision_engine -> execution/reporting`

Forbidden shortcuts:
- `strategy_engine` calling broker directly
- `sources` importing strategy scoring rules
- `reporting` mutating execution state
- `openclaw` templates controlling final order parameters without decision validation

## 7. OpenClaw governance
OpenClaw is a system integration layer, not the authoritative core.
Project-root `openclaw/` contains prompt templates, schemas, I/O examples, and skill assets.
OpenClaw must not:
- own broker truth
- own position truth
- choose arbitrary storage locations
- bypass runtime mode restrictions
- bypass risk vetoes

## 8. Runtime safety governance
`RUNTIME_MODES.md` is binding.
If in doubt, fail closed.
No contributor may introduce logic that:
- auto-promotes `paper` to `live`
- treats missing runtime mode as permissive
- bypasses operator approval requirements where mandated
- converts incomplete data into actionable intent silently

## 9. Testing governance
Critical-path code must not remain untested.
- Unit tests: parsing, normalization, scoring, rule evaluation
- Integration tests: source-to-normalized flow, feature chains, strategy-to-decision flow, reconciliation
- Contract tests: schema validation, provider assumptions, OpenClaw input/output shapes

## 10. Auditability requirements
The system must be able to answer:
- what data was used
- what features were computed
- what signal was created
- what risk rule allowed or denied it
- what decision was generated
- what order was submitted
- what the broker returned

## 11. Exception process
Exceptions require:
- explicit written note
- limited scope
- expiry condition
- named owner
- rollback path

## 12. Minimum review checklist
Before accepting a structural or critical-path change, verify:
- directory placement is correct
- ownership is clear
- schema is documented
- write paths are controlled
- risk implications are understood
- runtime mode behavior is safe
- audit trail is preserved
- tests exist at the correct level
