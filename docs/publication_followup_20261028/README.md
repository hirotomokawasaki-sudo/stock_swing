# 2026-10-28 follow-up publication

Reviewed isolated candidates through plan section 3.47, based on public commit `e2d98eed3c2cdf19dd6621d1cec29297f6eb2e61`. The seven private source-main commits are NOT outgoing ancestors. Root runtime source and operational configuration are not updated by this follow-up; no deployment or service restart.

- Cancellation/config and timing/config packets retain original sealed bytes.
- `research_config_console_20261028` is a PUBLIC PROJECTION: individual decisions, event-level outcomes, frozen price inputs, private account fixtures and screenshots are omitted. Aggregate result bytes are retained after nested review. Private research outcome replay and full historical suite replay are unavailable from this publication.
- Captured latest Console compatibility code is included ONLY inside the isolated candidate under `docs/`, not applied to root runtime code. Unrelated newer operational Console work is excluded.
- Prior local full-suite evidence: 3,156 unique passes / 2 skips. Publication-specific tests and skips are recorded separately in `VALIDATION.json`, never added to that total.
- Git does not preserve 0600/0700. In a disposable checkout run `python -B docs/research_config_console_20261028/restore_modes.py` to verify every byte before restoring reviewed packet modes. Then use its `verify.py --output <outside-path> --browser` for public technical replay. It does not recompute privately dependent research outcomes.
- Old `Push:false` fields describe original local validation, not this publication action. Some older local-only document links remain unavailable. No main merge or CI completion is claimed.
