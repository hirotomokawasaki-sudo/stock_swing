# stock_swing — current code snapshot (2026-11-11)

Source code for the trading support, deterministic risk/execution controls,
research/paper CLI, local Console and dashboard.

**Start with [the snapshot scope and validation](docs/publication_20261111/README.md).**
This is a source-only publication. Private account data, raw trading evidence,
credentials, runtime state and most research packets are deliberately absent.
It is not a production deployment or a self-contained financial replay package.

- Application: `src/stock_swing/`
- Console: `console/`; dashboard: `dashboard/`
- CLI/maintenance tools: `scripts/`
- Tests and synthetic fixtures: `tests/`
- Policy configuration: `config/` (`mode: paper`, no live activation)
- Dependencies: `pyproject.toml`, `requirements.txt`
- Controls: `GOVERNANCE.md`, `RUNTIME_MODES.md`

See the validation receipt for public-input test results and explicitly
unavailable private-fixture tests. No credentials or operational data are needed
to read the code. Publication does not authorize running broker/repair commands.
