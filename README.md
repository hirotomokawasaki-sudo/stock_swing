# stock_swing — reviewed source snapshot (2026-11-19)

Application, research/paper CLI, deterministic controls, local Console and tests.

Start with [publication scope and observed validation](docs/publication_20261119/README.md).
This code-only branch excludes credentials, actual account/operational configuration,
mutable ledgers, raw broker evidence and private individual transaction rows.
It is not a deployment or self-contained financial replay.

- src/stock_swing/: application source
- console/, dashboard/: operator interfaces
- scripts/: administrative and analysis tools; publication does not authorize use
- tests/: code and synthetic fixtures, with private-input dependencies disclosed
- config/: non-account policy templates; uninstalled runtime example only
- research_candidates/: isolated, unapplied preview
- pyproject.toml, requirements.txt: declared dependencies (Python >=3.11)
- docs/publication_20261119/: exact scope, inventory, tests and limitations
