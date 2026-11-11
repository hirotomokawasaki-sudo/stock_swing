# Current source-code snapshot — 2026-11-11

This branch contains the current on-disk application source, Console, scripts,
tests, policy configuration, dashboard and integration templates. It is a
**code-only snapshot**, not a deployment, strategy activation, profit evaluation,
or a complete private research/evidence archive. Source main, its index, services,
schedulers, account state and credentials remain unchanged.

See [SCOPE.json](SCOPE.json), [INVENTORY.json](INVENTORY.json), and
[VALIDATION.json](VALIDATION.json) for exact scope, file hashes and checks.
The seven unpublished private commits on local main are not ancestors. The
snapshot descends only from the previously public branch. Existing main and the
previous publication branch are not changed. Historical data/export/env-backup
files inherited from that public parent are removed from this snapshot's tip;
this does not rewrite their existing public history.

## Inputs deliberately not supplied

No credentials, actual account configuration, operational ledgers, raw orders,
fills, decision/price history, runtime logs, or private financial evidence packets
are included. Empty `.env.example` fields and deliberately synthetic test
fixtures are included. Incident and migration tests which need omitted private
inputs cannot be replayed from this ZIP; they are distinguished from tests run
using only public inputs. Most private planning and research documents, including
the current authoritative roadmap, remain local. Links to those local-only
documents are intentionally not a claim that they are bundled.

## Verification and use

Python >=3.11; dependencies are in `pyproject.toml`, `requirements.txt`, and
`dashboard/requirements.txt`. Use a new virtual environment. Do not copy this
snapshot over an operational installation: it contains administrative and
historical maintenance commands, not an authorized cutover procedure. Runtime
configuration is copied exactly, with `mode: paper`; no login or broker call was
performed by this publication. GitHub ZIPs preserve file bytes and executable
bits, not restrictive local 0600/0700 modes.

No main integration, CI success or production application is implied by a push.

## Observed verification results

- Existing project Python 3.13.10 venv; no packages installed.
- Private-fixture suite on the public code projection: **4,310 passed, 4 failed,
  2 skipped**. The four failures are retained expectations/behavior disagreements
  in reduction orders (2), stop-loss versus emergency-cap reason (1), and
  submission guard behavior (1). This is **not an all-green release**.
- Public-input run: **3,911 passed, 19 failed, 2 skipped** after omitting 14
  directly private-input-dependent modules. Fifteen of those failures are an
  additional indirect dependency on the omitted private residual-case input;
  four match the private-fixture suite's functional disagreements. Public and
  private runs overlap and must not be summed.
- Python 682, JSON 20, YAML 19, shell 17, and JavaScript/payload 13 syntax checks
  pass. OpenClaw async payloads were parsed in their async-function context.
- Existing heuristic scanner exits 1 on five AST-verified dummy `fixture`
  literals. Supplementary checks against 12 real credential values and 4,096
  financial identities have no remaining matches after the public-only
  projections. Actual values are not included in this report.
- Source administrative code/test identity literals were replaced only in the
  public copy; one manual WebSocket authentication example is a placeholder.
  Nine privacy-projected paths and one whitespace-only test projection are
  enumerated in SCOPE.json. Do not mistake those placeholders for usable
  authentication or historical account evidence.

INVENTORY.json lists every regular file except itself, with SHA256/size and
executable-bit information. Source-mode entries describe private original
permissions; a Git ZIP does not restore 0600/0700 modes. ZIP verification checks
the exact published tree bytes and inventory, not financial replay readiness.
