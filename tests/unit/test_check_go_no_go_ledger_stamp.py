"""Nov17 regression: cached VALID cannot refresh its own evidence date.
The legacy hook preserves config even when passed True; report saving is
not raw ledger validation. Comments and unrelated controls stay byte-exact.
"""
from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path

import zoneinfo

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_go_no_go.py"
JST = zoneinfo.ZoneInfo("Asia/Tokyo")

_SAMPLE_YAML = """# config/runtime/current_mode.yaml
# comment line kept verbatim
mode: paper

ledger_quality_gate:
  enforce_invalid_ledger_blocks_live_ready: true
  acceptance_criteria:
    max_closed_quarantine_overlap: 0
  # a human comment right above the field being stamped
  current_status: VALID
  last_checked: "2026-08-01"

circuit_breaker:
  require_clean_run_after_manual_clear: true
"""


def _load_module(monkeypatch, project_root: Path):
    spec = importlib.util.spec_from_file_location("check_go_no_go_ledger_stamp", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "PROJECT_ROOT", project_root)
    config_path = project_root / "config" / "runtime" / "current_mode.yaml"
    monkeypatch.setattr(module, "CURRENT_MODE_PATH", config_path)
    return module


def _write_current_mode(project_root: Path, text: str = _SAMPLE_YAML) -> Path:
    config_dir = project_root / "config" / "runtime"
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "current_mode.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_cached_ledger_boolean_does_not_stamp_today(monkeypatch, tmp_path):
    module = _load_module(monkeypatch, tmp_path)
    path = _write_current_mode(tmp_path)

    now_jst = datetime.now(JST)
    module._update_ledger_gate_last_checked(True, now_jst)

    text = path.read_text(encoding="utf-8")
    assert 'last_checked: "2026-08-01"' in text
    assert "current_status: VALID" in text


def test_preserves_surrounding_comments_and_other_sections(monkeypatch, tmp_path):
    module = _load_module(monkeypatch, tmp_path)
    path = _write_current_mode(tmp_path)

    now_jst = datetime.now(JST)
    module._update_ledger_gate_last_checked(True, now_jst)

    text = path.read_text(encoding="utf-8")
    assert "# a human comment right above the field being stamped" in text
    assert "# config/runtime/current_mode.yaml" in text
    assert "circuit_breaker:" in text
    assert "require_clean_run_after_manual_clear: true" in text


def test_does_not_write_when_ledger_check_failed(monkeypatch, tmp_path):
    """If ledger_quality did not pass, last_checked must not be bumped —
    stamping it would mask a genuine failure as freshly re-verified."""
    module = _load_module(monkeypatch, tmp_path)
    path = _write_current_mode(tmp_path)
    before = path.read_text(encoding="utf-8")

    now_jst = datetime.now(JST)
    module._update_ledger_gate_last_checked(False, now_jst)

    after = path.read_text(encoding="utf-8")
    assert after == before
    assert 'last_checked: "2026-08-01"' in after


def test_missing_current_mode_file_does_not_raise(monkeypatch, tmp_path):
    module = _load_module(monkeypatch, tmp_path)
    now_jst = datetime.now(JST)
    # No current_mode.yaml written at all.
    module._update_ledger_gate_last_checked(True, now_jst)
    assert not (tmp_path / "config" / "runtime" / "current_mode.yaml").exists()


def test_malformed_current_mode_missing_fields_does_not_raise_or_write(monkeypatch, tmp_path):
    """If the file doesn't contain the expected fields (e.g. corrupted or
    manually restructured), the regex substitution silently no-ops rather
    than writing a partial/inconsistent file."""
    module = _load_module(monkeypatch, tmp_path)
    path = _write_current_mode(tmp_path, text="mode: paper\nother_key: value\n")
    before = path.read_text(encoding="utf-8")

    now_jst = datetime.now(JST)
    module._update_ledger_gate_last_checked(True, now_jst)

    after = path.read_text(encoding="utf-8")
    assert after == before
