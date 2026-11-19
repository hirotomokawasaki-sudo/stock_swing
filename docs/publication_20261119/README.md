# Reviewed source publication — 2026-11-19

Current application/Console/scripts/tests and non-account policy templates are
published on a separate branch based on the prior public code snapshot. This is
not a main integration, service restart, deployment, trading-policy activation,
financial correction or green release claim.

See SCOPE.json, VALIDATION.json, INVENTORY.json and RESEARCH_STATUS.md. Private
raw inputs, account/operational configuration, ledgers, logs, and individual
transaction rows are deliberately absent. Even pseudonymized individual-trade
audit rows and most private plans were not copied. Public aggregate projections
are not the original sealed evidence packets and cannot reproduce omitted inputs.

An uninstalled config/runtime/current_mode.example.yaml is provided instead of
the operational file. It has UNKNOWN readiness and no validation date. The actual
operator configuration remains local and unchanged. Fill in your own environment
and permissions; this branch is not a cutover or execution recipe.

research_candidates/ contains one pure preview candidate, explicitly not
integrated or deployed. The private historical 35-case acceptance is a prior
result, not a new public-input acceptance claim. Test counts for the application
snapshot are recorded separately. Git preserves executable bits, not restrictive
0600/0700 mode inventories of private packets; no such replay is claimed.

The source main HEAD/index and selected originals are preserved. Seven private
local commits are not ancestors; only previously public ancestors are inherited.
The old public branches and remote main are not changed. Public base history is
not rewritten. No CI success, merge, deployment, broker call, order or cancellation
is implied by a branch push.

## Observed verification

- Exact runtime source package: 202 files byte-identical to the private source.
- Private-fixture full-suite acceptance: **4,409 unique passed, 2 skipped**, no unresolved failures after separating five self-owned sandbox cases. This uses deliberately omitted private fixtures/config and is not a public-clone full-suite claim.
- Public-input focused acceptance: **242 unique passed**, no unresolved failures after the same sandbox grouping correction. Includes tests exercising projected script/test identifiers. Counts overlap the private suite.
- Python/JSON/YAML/shell and JavaScript/async-payload syntax checks pass in their actual language contexts. Staged whitespace is checked separately.
- The unchanged heuristic scanner returns exit 1 for 6 exact AST-verified short dummy fixture literals. Supplemental comparison against 13 known credential values and 4106 financial identities has no remaining matches. Actual values are not published.
- Nine files contain privacy-only substitutions in this public copy; one test has one trailing space removed. Runtime application source is unchanged.
- Ordinary tests use OS network/write denial. Child-owned CLI tests use their existing child sandbox and fixture HTTP. No real external service or trading workflow was invoked.

Historical private candidate acceptance (35 cases) is separate and was not rerun.
