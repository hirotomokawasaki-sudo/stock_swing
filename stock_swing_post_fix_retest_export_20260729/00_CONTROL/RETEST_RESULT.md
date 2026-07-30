# Stock Swing Post-Fix Retest Result

- snapshot_id: `0288631a317e14a941d9`
- as_of_utc: `2026-07-29T10:18:06.302948+00:00`
- commit_start: `f407b27162e7e7d3f8aed8c8a8e3ce82b1e0b3e5`
- commit_end: `f407b27162e7e7d3f8aed8c8a8e3ce82b1e0b3e5`
- branch: `main`
- runtime_mode: `paper`
- config_hash: `2b408d0382d15ec85db418393301ef253f1c5ce7ebe610e8a6fb48209f6a9853`
- overall: **NO-GO**

## Acceptance Matrix

- **GATE-001** PASS — expected: all pytest suites exit 0 / actual: see 02_TESTS / evidence: see related export section
- **GATE-002** FAIL — expected: 0 / actual: 1136 / evidence: see related export section
- **GATE-003** PASS — expected: 0 / actual: 0 / evidence: see related export section
- **GATE-004** PASS — expected: 0 / actual: 0 / evidence: see related export section
- **GATE-005** BLOCKED — expected: 0 / actual: potential key reuse count=25; exact duplicate consumption unavailable without broker fill ledger / evidence: see related export section
- **GATE-006** FAIL — expected: abs(diff)<=1 / actual: -4340.8 / evidence: see related export section
- **GATE-007** FAIL — expected: 0 / actual: 1 / evidence: see related export section
- **GATE-008** FAIL — expected: >=99% / actual: {"run_id_pct": 0.0, "experiment_id_pct": 0.0, "config_hash_pct": 0.0} / evidence: see related export section
- **GATE-009** FAIL — expected: >=99.5% and no synthetic/stale required source / actual: [{"source": "finnhub_news", "rows": 44, "ok": 41, "coverage_pct": 93.182, "as_of": "2026-07-29T07:04:18.198275+00:00", "timed_out": false}, {"source": "broker", "raw_file_count": 25, "latest_mtime_utc": "2026-04-21T06:15:08.596495+00:00", "freshness_hours": 2380.05, "coverage_pct": null}, {"source": "fred", "raw_file_count": 4, "latest_mtime_utc": "2026-04-21T06:15:08.596586+00:00", "freshness_hours": 2380.05, "coverage_pct": 0}, {"source": "sec", "raw_file_count": 10, "latest_mtime_utc": "2026- / evidence: see related export section
- **GATE-010** PASS — expected: missing metric not zero + tests pass / actual: see 06_GUARDRAILS and scenario tests / evidence: see related export section
- **GATE-011** PASS — expected: HTTP 200 / actual: health=200 / evidence: see related export section
- **GATE-012** PASS — expected: 403 for apply/rollback / actual: {"full_parameter_apply_post": 403, "full_parameter_rollback_post": 403} / evidence: see related export section
- **GATE-013** FAIL — expected: stale/invalid must not display VALID / actual: {"status": "VALID", "as_of": "2026-07-28T13:35:26.156176+00:00", "details": {"overlap": 0, "reversed_chronology": 0, "holding_days_missing": 0, "attribution_coverage_pct": 98.5}} / evidence: see related export section
- **GATE-014** PASS — expected: independent recomputation generated in export / actual: 05_PERFORMANCE/performance_by_window.json / evidence: see related export section
- **GATE-015** FAIL — expected: query token rejected / actual: 200 / evidence: see related export section

## Stage Decisions

- PAPER継続可否: YES
- 新規BUY再開可否: NO
- Exit-only解除可否: NO
- strategy A/B開始可否: NO
- micro-live可否: NO

## Unresolved Critical Issues
- GATE-002: synthetic production records=0 (FAIL) actual=1136
- GATE-005: duplicate fill consumption=0 (BLOCKED) actual=potential key reuse count=25; exact duplicate consumption unavailable without broker fill ledger
- GATE-006: sum(closed.pnl) and state PnL diff <= $1 (FAIL) actual=-4340.8
- GATE-007: unexplained broker/tracker mismatch=0 (FAIL) actual=1
- GATE-008: run_id/experiment_id/config_hash coverage >=99% (FAIL) actual={"run_id_pct": 0.0, "experiment_id_pct": 0.0, "config_hash_pct": 0.0}
- GATE-009: required source coverage >=99.5% (FAIL) actual=[{"source": "finnhub_news", "rows": 44, "ok": 41, "coverage_pct": 93.182, "as_of": "2026-07-29T07:04:18.198275+00:00", "timed_out": false}, {"source": "broker", "raw_file_count": 25, "latest_mtime_utc": "2026-04-21T06:15:08.596495+00:00", "freshness_hours": 2380.05, "coverage_pct": null}, {"source": "fred", "raw_file_count": 4, "latest_mtime_utc": "2026-04-21T06:15:08.596586+00:00", "freshness_hours": 2380.05, "coverage_pct": 0}, {"source": "sec", "raw_file_count": 10, "latest_mtime_utc": "2026-
- GATE-013: invalid/stale data not VALID/green (FAIL) actual={"status": "VALID", "as_of": "2026-07-28T13:35:26.156176+00:00", "details": {"overlap": 0, "reversed_chronology": 0, "holding_days_missing": 0, "attribution_coverage_pct": 98.5}}
- GATE-015: remote read-only query token disabled (FAIL) actual=200
