# C11/U research source snapshot — 2026-11-26

**Research only. Not a production application, deployable branch, adopted strategy, or investment result.** This dedicated publication branch keeps only the reviewed source allowlist. It is not intended to be merged wholesale into main: inherited application/data/configuration files are absent from this branch tip. Existing main and its already-public history are unchanged.

## Scope

- `docs/c11_calibration_connection_20261124/native_entries.py`, `native_paths.py`, and `run_research_paths.py`: each arm's native Entry/PF/guard and nominal sizing → one accepted C11/U accounting owner → native Exit. Captured integer guard actions are normalized at the typed boundary; unknown values fail closed.
- `closing_port.py`: availability-aware conditional closing valuation without inserting backdated trading events, followed by the existing exposure-only selector.
- `path_driver.py`, `bridge.py`, the accepted pure comparison book, source pins and synthetic acceptance source are retained unchanged as dependencies/source references.

All 101 books have independent cash, positions and history. Native U quantity scaling and C11 ATR/cap logic are not reapplied as valuation adjustments. Unknown inputs are not zero-filled. Daily bar labels, session close and input availability are distinct clocks. The explicit calendar contract handles early closes without assuming 16:00 ET.

## Validation and limits

Private retained-workspace validation completed 46 native-path acceptance cases and, separately, 33 closing-port cases, with no skips. These are different scopes, not a combined application-suite result. The application-wide suite was not rerun.

The private saved-input diagnostic matched independent accounting for 101 modeled books and produced **one conditional daily valuation; zero formally qualified daily sessions**. Source journals stayed byte-identical, with no new fills or mark transaction fees. The formal U, economic qualification, evaluation outcome and start date remain unadopted/unavailable. Diagnostic coefficients and model returns are not adoption decisions.

Historical daily wrappers omit original feed/adjustment/request/wire proof. A current-code HTTP fixture reproduced the omission and separately showed that the **existing recorder**, explicitly attached to the client, retains the full bar contract and response-body hash through the writer/normalizer and sealed reader. This is an offline remedy check, not a historical proof or deployed collector fix.

### What is deliberately not included

No raw snapshots, captured run inputs, account/trade/lot journals, production configuration, credentials, personal paths, private reports, or unrelated local commits are published. This is **not a self-contained market replay**. In particular:

- Native path tests require the private `C11_ENTRY_WORK` fixture, frozen native source pins and explicit pure guard adapter. Their 46-case retained-workspace result is not claimed as reproduced by this checkout.
- Calibration calls through `bridge._prepare()` require the separately retained parent prepare/contract/sealed-source dependency closure, not included here. Six closing test functions depend on that closure and are deliberately deselected in the public subset.
- `SOURCE_PINS.json` is the unchanged accepted source-reference inventory, not a completeness manifest for this branch. `PUBLICATION_MANIFEST.json` describes this branch's actual payload.

### Reproduce the public pure-valuation subset

Python 3.11+ and pytest are required. From this branch root:

```sh
python -B -m pytest -q -p no:cacheprovider -c /dev/null --confcutdir . docs/c11_calibration_connection_20261124/test_closing_port.py -k 'not real_closing_exposures_only_reach_unchanged_selector and not availability_not_only_session_date_is_before_evaluation and not empty_books_are_inactive_not_a_treatment_result and not malformed_receipt_cannot_claim_qualified_daily_data and not next_session_keeps_independent_append_only_journals_and_rejects_reset and not new_event_cannot_be_backfilled_before_an_exported_close'
python -B scripts/secret_scan.py
```

See `PUBLICATION_VALIDATION.json` for the observed checkout-specific count, omitted dependencies, sandbox and static/privacy checks. No live market/broker calls, orders, deployment, scheduler or guard changes were made by the research validation or publication.

## Next priority

Reuse the existing recorder in the normal daily collector so future snapshots retain actual feed, adjustment, query and wire-hash provenance; verify original business behavior and failure/end receipts before any deployment. Do not add another recorder, strategy candidate or general replay platform for this gap.
