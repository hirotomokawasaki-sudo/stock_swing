"""Tests for P5-A: secret scan script."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))


def test_secret_scan_passes_on_redacted_lines(tmp_path: Path, monkeypatch) -> None:
    import secret_scan

    monkeypatch.setattr(secret_scan, "ROOT", tmp_path)
    safe_file = tmp_path / "config.py"
    safe_file.write_text("BROKER_API_SECRET=***REDACTED***\n", encoding="utf-8")
    assert secret_scan.main() == 0


def test_secret_scan_detects_real_looking_secret(tmp_path: Path, monkeypatch) -> None:
    import secret_scan

    monkeypatch.setattr(secret_scan, "ROOT", tmp_path)
    bad_file = tmp_path / "config_bad.py"
    bad_file.write_text("BROKER_API_SECRET=abcdefghijklmnopqrstuvwxyz123456\n", encoding="utf-8")
    assert secret_scan.main() == 1


def test_secret_scan_allows_empty_value(tmp_path: Path, monkeypatch) -> None:
    import secret_scan

    monkeypatch.setattr(secret_scan, "ROOT", tmp_path)
    safe_file = tmp_path / "env_example.py"
    safe_file.write_text("BROKER_API_SECRET=\n", encoding="utf-8")
    assert secret_scan.main() == 0
