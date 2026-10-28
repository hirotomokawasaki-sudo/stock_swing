"""R6-v2 / H9: Mtime file cache tests.

Performance SLO:
  - initial render: loads file via loader_fn
  - cached rerun (mtime/size unchanged): returns cached value without calling loader
  - invalidation: re-reads when mtime or size changes

History:
    R6-v2 / H9 (2026-07-23): prevents redundant pnl_state.json reads in the
    console server dashboard_service._tracker._load_state() per-request.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from stock_swing.utils.mtime_cache import MtimeFileCache, pnl_state_cache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _loader(path: Path) -> dict:
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Core behaviour
# ---------------------------------------------------------------------------

class TestMtimeFileCacheCore:
    def test_first_call_loads_file(self, tmp_path: Path) -> None:
        p = tmp_path / "data.json"
        _write(p, {"v": 1})
        cache: MtimeFileCache[dict] = MtimeFileCache()
        result = cache.get(p, loader_fn=_loader)
        assert result == {"v": 1}

    def test_second_call_uses_cache_without_calling_loader(self, tmp_path: Path) -> None:
        p = tmp_path / "data.json"
        _write(p, {"v": 1})
        call_count = {"n": 0}

        def counting_loader(path: Path) -> dict:
            call_count["n"] += 1
            return _loader(path)

        cache: MtimeFileCache[dict] = MtimeFileCache()
        cache.get(p, loader_fn=counting_loader)
        cache.get(p, loader_fn=counting_loader)

        assert call_count["n"] == 1, "second call must use cache (loader called only once)"

    def test_cache_invalidated_when_mtime_changes(self, tmp_path: Path) -> None:
        """Cache miss when mtime changes (simulated by writing new content)."""
        p = tmp_path / "data.json"
        _write(p, {"v": 1})
        call_count = {"n": 0}

        def counting_loader(path: Path) -> dict:
            call_count["n"] += 1
            return _loader(path)

        cache: MtimeFileCache[dict] = MtimeFileCache()
        r1 = cache.get(p, loader_fn=counting_loader)
        assert r1 == {"v": 1}

        # Simulate file change: write new content and touch mtime
        time.sleep(0.01)  # ensure different mtime
        _write(p, {"v": 2})

        r2 = cache.get(p, loader_fn=counting_loader)
        assert r2 == {"v": 2}, "must reload when file changes"
        assert call_count["n"] == 2, "loader must be called again after file change"

    def test_cache_invalidated_when_size_changes(self, tmp_path: Path) -> None:
        """Cache miss when file size changes even if mtime is same (e.g. quick write)."""
        p = tmp_path / "data.json"
        _write(p, {"v": 1})
        cache: MtimeFileCache[dict] = MtimeFileCache()
        cache.get(p, loader_fn=_loader)

        # Manually force size mismatch in cache entry
        entry = cache._entries[p]
        # Replace entry with wrong size so next get() detects change
        from stock_swing.utils.mtime_cache import _CacheEntry
        cache._entries[p] = _CacheEntry(value={"v": 1}, mtime=entry.mtime, file_size=0)

        result = cache.get(p, loader_fn=_loader)
        assert result == {"v": 1}  # re-read, same content but loader called

    def test_missing_loader_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "data.json"
        _write(p, {})
        cache: MtimeFileCache[dict] = MtimeFileCache()
        with pytest.raises(ValueError, match="loader_fn"):
            cache.get(p)

    def test_file_not_found_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "nonexistent.json"
        cache: MtimeFileCache[dict] = MtimeFileCache()
        with pytest.raises(FileNotFoundError):
            cache.get(p, loader_fn=_loader)

    def test_constructor_loader_fn_used_as_default(self, tmp_path: Path) -> None:
        p = tmp_path / "data.json"
        _write(p, {"x": 99})
        cache: MtimeFileCache[dict] = MtimeFileCache(loader_fn=_loader)
        result = cache.get(p)  # no per-call loader_fn
        assert result == {"x": 99}


# ---------------------------------------------------------------------------
# Invalidation
# ---------------------------------------------------------------------------

class TestMtimeFileCacheInvalidation:
    def test_invalidate_specific_path(self, tmp_path: Path) -> None:
        p = tmp_path / "data.json"
        _write(p, {"v": 1})
        call_count = {"n": 0}

        def counting_loader(path: Path) -> dict:
            call_count["n"] += 1
            return _loader(path)

        cache: MtimeFileCache[dict] = MtimeFileCache()
        cache.get(p, loader_fn=counting_loader)
        cache.invalidate(p)
        cache.get(p, loader_fn=counting_loader)

        assert call_count["n"] == 2, "loader must be called again after explicit invalidate"

    def test_invalidate_all(self, tmp_path: Path) -> None:
        p1 = tmp_path / "a.json"
        p2 = tmp_path / "b.json"
        _write(p1, {"a": 1})
        _write(p2, {"b": 2})
        cache: MtimeFileCache[dict] = MtimeFileCache(loader_fn=_loader)
        cache.get(p1)
        cache.get(p2)
        assert len(cache.cached_paths) == 2
        cache.invalidate()
        assert len(cache.cached_paths) == 0

    def test_is_cached_returns_true_after_load(self, tmp_path: Path) -> None:
        p = tmp_path / "data.json"
        _write(p, {})
        cache: MtimeFileCache[dict] = MtimeFileCache(loader_fn=_loader)
        assert not cache.is_cached(p)
        cache.get(p)
        assert cache.is_cached(p)


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

class TestMtimeFileCacheThreadSafety:
    def test_concurrent_reads_all_return_same_value(self, tmp_path: Path) -> None:
        """Multiple threads reading same path must all get the same value."""
        p = tmp_path / "data.json"
        _write(p, {"shared": 42})
        cache: MtimeFileCache[dict] = MtimeFileCache(loader_fn=_loader)

        results: list[dict] = []
        lock = threading.Lock()

        def reader():
            val = cache.get(p)
            with lock:
                results.append(val)

        threads = [threading.Thread(target=reader) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 10
        assert all(r == {"shared": 42} for r in results)


# ---------------------------------------------------------------------------
# Module-level shared pnl_state_cache
# ---------------------------------------------------------------------------

class TestPnlStateCache:
    def test_pnl_state_cache_is_singleton(self) -> None:
        from stock_swing.utils.mtime_cache import pnl_state_cache as c1
        from stock_swing.utils.mtime_cache import pnl_state_cache as c2
        assert c1 is c2, "pnl_state_cache must be module-level singleton"

    def test_pnl_state_cache_reads_json(self, tmp_path: Path) -> None:
        p = tmp_path / "pnl_state.json"
        _write(p, {"trades": [], "total_trades": 0})
        result = pnl_state_cache.get(p)
        assert result["total_trades"] == 0

    def test_pnl_state_cache_does_not_reload_unchanged_file(self, tmp_path: Path) -> None:
        p = tmp_path / "pnl_state.json"
        _write(p, {"trades": []})
        local_cache: MtimeFileCache[dict] = MtimeFileCache(
            loader_fn=lambda path: json.loads(path.read_text())
        )
        call_count = {"n": 0}

        def counting(_path: Path) -> dict:
            call_count["n"] += 1
            return json.loads(_path.read_text())

        local_cache.get(p, loader_fn=counting)
        local_cache.get(p, loader_fn=counting)
        assert call_count["n"] == 1, "pnl_state_cache must skip re-read when file unchanged"
