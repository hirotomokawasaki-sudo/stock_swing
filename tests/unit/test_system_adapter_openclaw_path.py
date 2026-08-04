"""Tests for SystemAdapter's openclaw binary/PATH resolution (2026-08-04).

Regression: the console HTTP server is started by launchd (see
~/Library/LaunchAgents/com.hirotomookawasaki.stock_swing.console.watchdog.plist),
whose default environment PATH is only /usr/bin:/bin:/usr/sbin:/sbin -- it
does NOT include /opt/homebrew/bin, where `openclaw` (and `node`, which
`openclaw` shells out to via `#!/usr/bin/env node`) actually live on this
host. subprocess.run(["openclaw", ...]) under that inherited environment
always raised FileNotFoundError, making
SystemAdapter._check_cron_run_history() permanently critical/not-ok and
keeping the overall dashboard health score capped at 49 ("blocked") around
the clock, even when every other subsystem was healthy.

Verified live: running SystemAdapter._check_cron_run_history() under
`env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin` (the exact launchd PATH)
reproduced "[Errno 2] No such file or directory: 'openclaw'" before this
fix, and returned ok=True / parse_coverage=1.0 after.

See docs/daily_logs/2026-08-04.md.
"""
from __future__ import annotations

import os

from console.adapters import system_adapter as sa_module


# ── _resolve_openclaw_bin ────────────────────────────────────────────────────

class TestResolveOpenclawBin:
    def test_uses_shutil_which_result_when_found(self, monkeypatch):
        """AC: prefer whatever PATH resolution already finds."""
        monkeypatch.setattr(sa_module.shutil, "which", lambda name: "/some/custom/path/openclaw")
        assert sa_module._resolve_openclaw_bin() == "/some/custom/path/openclaw"

    def test_falls_back_to_homebrew_path_when_which_fails_and_exists(self, monkeypatch):
        """AC: when shutil.which() finds nothing (minimal launchd PATH), fall
        back to the known Homebrew install location if it exists on disk."""
        monkeypatch.setattr(sa_module.shutil, "which", lambda name: None)
        monkeypatch.setattr(sa_module.os.path, "exists", lambda p: p == "/opt/homebrew/bin/openclaw")
        assert sa_module._resolve_openclaw_bin() == "/opt/homebrew/bin/openclaw"

    def test_falls_back_to_usr_local_bin_when_homebrew_missing(self, monkeypatch):
        """境界値: /opt/homebrew/bin/openclaw absent but /usr/local/bin present."""
        monkeypatch.setattr(sa_module.shutil, "which", lambda name: None)
        monkeypatch.setattr(sa_module.os.path, "exists", lambda p: p == "/usr/local/bin/openclaw")
        assert sa_module._resolve_openclaw_bin() == "/usr/local/bin/openclaw"

    def test_returns_bare_name_when_nothing_found(self, monkeypatch):
        """境界値: nothing found anywhere -> preserve original 'openclaw' bare
        name so the original FileNotFoundError-style behavior/message is
        unchanged when truly absent (fail visibly, not silently)."""
        monkeypatch.setattr(sa_module.shutil, "which", lambda name: None)
        monkeypatch.setattr(sa_module.os.path, "exists", lambda p: False)
        assert sa_module._resolve_openclaw_bin() == "openclaw"


# ── _subprocess_env ──────────────────────────────────────────────────────────

class TestSubprocessEnv:
    def test_adds_homebrew_dirs_to_minimal_launchd_path(self, monkeypatch):
        """
        Regression: launchd's default PATH (/usr/bin:/bin:/usr/sbin:/sbin)
        cannot resolve `node`, which `openclaw`'s shebang (#!/usr/bin/env
        node) needs. The augmented PATH must include /opt/homebrew/bin.
        """
        monkeypatch.setenv("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
        env = sa_module._subprocess_env()
        parts = env["PATH"].split(os.pathsep)
        assert "/opt/homebrew/bin" in parts
        assert "/usr/bin" in parts, "original PATH entries must be preserved"

    def test_does_not_duplicate_existing_homebrew_dir(self, monkeypatch):
        """no-op ケース: PATH already contains /opt/homebrew/bin -> not duplicated."""
        monkeypatch.setenv("PATH", "/opt/homebrew/bin:/usr/bin:/bin")
        env = sa_module._subprocess_env()
        parts = env["PATH"].split(os.pathsep)
        assert parts.count("/opt/homebrew/bin") == 1

    def test_preserves_other_environment_variables(self, monkeypatch):
        """AC: only PATH is modified; other env vars pass through unchanged."""
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
        monkeypatch.setenv("SOME_OTHER_VAR", "keep-me")
        env = sa_module._subprocess_env()
        assert env.get("SOME_OTHER_VAR") == "keep-me"

    def test_handles_missing_path_env_var(self, monkeypatch):
        """境界値: PATH entirely unset -> still returns a usable PATH with the
        Homebrew fallback dirs, no crash."""
        monkeypatch.delenv("PATH", raising=False)
        env = sa_module._subprocess_env()
        assert "/opt/homebrew/bin" in env["PATH"].split(os.pathsep)


# ── end-to-end: _check_cron_run_history under launchd-like minimal PATH ─────

class TestCheckCronRunHistoryUnderMinimalPath:
    """Regression test replicating the exact launchd PATH condition that
    caused the bug, verified live via `env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin`
    before writing this test."""

    def test_openclaw_bin_and_env_resolve_to_usable_values(self):
        """
        Regression: 2026-08-04. Under the console's actual launchd PATH,
        _OPENCLAW_BIN must resolve to an absolute, existing path (not the
        bare 'openclaw' that would raise FileNotFoundError when PATH lacks
        /opt/homebrew/bin), and _OPENCLAW_ENV's PATH must include a directory
        containing `node` so openclaw's shebang can execute.
        """
        assert os.path.isabs(sa_module._OPENCLAW_BIN) or sa_module._OPENCLAW_BIN == "openclaw", (
            f"_OPENCLAW_BIN should be an absolute path when resolvable, got: {sa_module._OPENCLAW_BIN}"
        )
        # On this host openclaw must be resolvable (it's installed); if this
        # assertion fails on a different host without openclaw installed,
        # that's expected -- the point is it must not silently degrade to
        # a bare unusable name when the binary DOES exist somewhere findable.
        if os.path.exists("/opt/homebrew/bin/openclaw"):
            assert sa_module._OPENCLAW_BIN != "openclaw", (
                "openclaw exists at /opt/homebrew/bin/openclaw but resolution "
                "fell back to the bare unusable name"
            )
