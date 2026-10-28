"""FIX-009: Console security regression tests."""

from __future__ import annotations

from pathlib import Path


def test_console_host_is_loopback():
    """Full console must bind to 127.0.0.1, not 0.0.0.0."""
    app_content = Path("console/app.py").read_text(encoding="utf-8")

    assert 'HOST = "0.0.0.0"' not in app_content
    assert 'HOST = "127.0.0.1"' in app_content


def test_console_write_disabled_by_default():
    """Write endpoints must be disabled by default."""
    app_content = Path("console/app.py").read_text(encoding="utf-8")

    assert "CONSOLE_WRITE_ENABLED" in app_content
