"""Tests for CronAdapter's openclaw binary/PATH resolution (2026-08-04).

Regression: same launchd-minimal-PATH issue as
console/adapters/system_adapter.py (see that module's tests/docstring for
full context on why launchd's default PATH cannot resolve `openclaw` or
`node` on this host).

For CronAdapter specifically, the consequence was worse than a health-score
display bug: get_jobs() caught the resulting FileNotFoundError from
subprocess.run(["openclaw", ...]) and silently fell through to
_get_from_backup(), which reads cron_backup/jobs.json -- a snapshot last
written 2026-05-01, about 3 months stale. Every cron-derived dashboard
metric (lag_seconds, next_run, last_run, last_status) was therefore
computed from ~3-month-old schedule data for as long as the console ran
under launchd, producing misleading alerts like "7 scheduled job(s) appear
behind schedule" with lag values in the millions of seconds -- not because
any real job was actually behind, but because "now" was being compared
against a next_run timestamp frozen on 2026-05-01.

Verified live: running CronAdapter.get_jobs() under
`env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin` (the exact launchd PATH)
returned the stale 7-job May 1st backup before this fix, and the live
13-job schedule with lag_seconds=0 after.

See docs/daily_logs/2026-08-04.md.
"""
from __future__ import annotations

import os

from console.adapters import cron_adapter as ca_module


class TestResolveOpenclawBin:
    def test_uses_shutil_which_result_when_found(self, monkeypatch):
        monkeypatch.setattr(ca_module.shutil, "which", lambda name: "/some/custom/path/openclaw")
        assert ca_module._resolve_openclaw_bin() == "/some/custom/path/openclaw"

    def test_falls_back_to_homebrew_path_when_which_fails_and_exists(self, monkeypatch):
        monkeypatch.setattr(ca_module.shutil, "which", lambda name: None)
        monkeypatch.setattr(ca_module.os.path, "exists", lambda p: p == "/opt/homebrew/bin/openclaw")
        assert ca_module._resolve_openclaw_bin() == "/opt/homebrew/bin/openclaw"

    def test_returns_bare_name_when_nothing_found(self, monkeypatch):
        monkeypatch.setattr(ca_module.shutil, "which", lambda name: None)
        monkeypatch.setattr(ca_module.os.path, "exists", lambda p: False)
        assert ca_module._resolve_openclaw_bin() == "openclaw"


class TestSubprocessEnv:
    def test_adds_homebrew_dirs_to_minimal_launchd_path(self, monkeypatch):
        monkeypatch.setenv("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
        env = ca_module._subprocess_env()
        parts = env["PATH"].split(os.pathsep)
        assert "/opt/homebrew/bin" in parts
        assert "/usr/bin" in parts

    def test_does_not_duplicate_existing_homebrew_dir(self, monkeypatch):
        monkeypatch.setenv("PATH", "/opt/homebrew/bin:/usr/bin:/bin")
        env = ca_module._subprocess_env()
        assert env["PATH"].split(os.pathsep).count("/opt/homebrew/bin") == 1


class TestGetJobsUnderMinimalPath:
    """Regression test replicating the exact launchd PATH condition that
    caused CronAdapter to silently serve a 3-month-stale backup file."""

    def test_openclaw_bin_resolves_to_usable_absolute_path(self):
        """
        Regression: 2026-08-04. Under the console's actual launchd PATH,
        _OPENCLAW_BIN must resolve to an existing absolute path so
        get_jobs() reaches live `openclaw cron list --json` output instead
        of silently falling back to the stale cron_backup/jobs.json.
        """
        if os.path.exists("/opt/homebrew/bin/openclaw"):
            assert ca_module._OPENCLAW_BIN != "openclaw", (
                "openclaw exists at /opt/homebrew/bin/openclaw but resolution "
                "fell back to the bare unusable name"
            )
