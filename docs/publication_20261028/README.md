# 2026-10-28 public publication

This branch publishes reviewed code, plans, and isolated validation artifacts. It is **not a production deployment or an approval to enable candidates**.

## History and scope

- Public base: `ee2acac4f7579188938d1265671d3146c91c0295`.
- Local source checkpoint: `8909e79c1a83e04d508715b132575625454b7856`.
- The seven local unpublished commits are represented by their reviewed current file contents, not pushed as ancestors. Necessary earlier code fixes are included for compatibility.
- The latest plans include the 10/28 work through section 3.44. Eight same-day review/validation directories are included. Isolation candidates stay under `docs/`; this publication does not apply them to runtime source.
- Earlier local-only research dependencies referenced in the plans are not automatically published by this operation. Some historical relative links therefore remain unavailable in this public branch.

## Private omissions and projections

- No working account configuration, runtime-mode changes, ledgers, raw broker snapshots, mutable trading data, `.run` contents, or private environment files are added.
- `signal_diagnostics_20261028/inputs.zip` and `input_manifest.json` are intentionally omitted. The public signal packet is a report/code subset, **not a self-contained raw-data replay**. Its original artifact hashes refer to the private complete packet and are not a claim that all inputs are published.
- In the newly published `strategy_assessment_20261020/results.json`, individual `worst10`/`best10` trade rows are omitted. The remaining aggregate results are a public projection, not the original input/result bytes.
- All six sealed implementation packets and the closure-review packet retain their original published file bytes, including safe synthetic logs and coverage receipts. Git preserves executable bits but not restrictive local permission bits (such as 0600/0700). Original mode-sensitive verifiers require an explicit local restoration of their pinned modes before use; a fresh clone alone is not claimed to have passed those verifiers.
- Full historical suite logs are existing evidence, not tests rerun for publication. Some full suites require privately retained financial fixtures; only hashes of those fixtures are published.

## Publication checks

See `VALIDATION.json` for the publication-specific test result and privacy review. Tests use the existing environment, an isolated checkout, and an OS sandbox denying external networking and writes to the operational repository. No broker request, order, cancel, scheduler change, console restart, or service deployment is performed.

The existing heuristic secret scanner flags eleven synthetic fixture assignments. Each flagged assignment was checked to contain a short dummy literal rather than a credential; its overly broad line-length heuristic is retained unchanged. The exact locations and line hashes are recorded in the validation receipt. A supplemental credential/private-key/credential-URL scan found no matches in the selected new scope. This is a scoped publication review, not a claim to audit all pre-existing public history.
