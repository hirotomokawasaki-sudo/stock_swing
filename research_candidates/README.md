# Isolated candidate — not deployed

canceled_partial_precision_preview.py is a pure, opt-in returned-copy precision
preview. It accepts caller-provided evidence and does not fetch, persist, submit,
cancel, replace, or deploy anything. Original order status, quantity, recorded
cash PnL, identities and quarantine must remain unchanged.

This candidate is not wired into the versioned migration/artifact path. Source,
revision, consumed-PF bindings, failure/retry behavior and namespace qualification
remain required before any application can be considered. Historical private
acceptance covered 35 cases; the private financial inputs and transaction-level
results are intentionally omitted. Those tests were not rerun or independently
reproduced from this public snapshot. Publication is not deployment approval.
