"""Mtime-based file read cache for R6-v2 / H9 console performance SLO.

Prevents redundant full file reads when the source file has not changed.
Thread-safe for the console server's ThreadingHTTPServer model.

Usage:
    from stock_swing.utils.mtime_cache import MtimeFileCache

    _pnl_cache: MtimeFileCache[dict] = MtimeFileCache()

    def load_pnl_state(path: Path) -> dict:
        return _pnl_cache.get(path, lambda p: json.loads(p.read_text()))

Performance SLO (H9):
    - initial render p95 ≤ 2s  (first load, no cache)
    - cached rerun p95 ≤ 500ms (subsequent loads when file unchanged)

History:
    R6-v2 / H9 (2026-07-23): extracted from console_summary discussion;
    dashboard_service._tracker._load_state() is called per-request and
    reads pnl_state.json (~400KB) each time even when nothing changed.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Generic, TypeVar

T = TypeVar("T")


@dataclass
class _CacheEntry(Generic[T]):
    value: T
    mtime: float       # os.stat().st_mtime at load time
    file_size: int     # st_size for quick change detection


class MtimeFileCache(Generic[T]):
    """Thread-safe file-read cache invalidated by mtime + size.

    The cache holds one entry per path.  On each get():
      1. stat() the file (cheap syscall).
      2. If mtime and size unchanged → return cached value.
      3. Otherwise reload via loader_fn and update cache.

    Args:
        loader_fn: Optional default loader.  Can be overridden per call.
    """

    def __init__(self, loader_fn: Callable[[Path], T] | None = None) -> None:
        self._loader_fn = loader_fn
        self._lock = threading.Lock()
        self._entries: dict[Path, _CacheEntry[T]] = {}

    def get(
        self,
        path: Path,
        loader_fn: Callable[[Path], T] | None = None,
    ) -> T:
        """Return cached value if file unchanged, else reload.

        Args:
            path: File path to read.
            loader_fn: Callable that reads *path* and returns a parsed value.
                       Falls back to the instance-level loader_fn if omitted.

        Returns:
            Parsed file content (cached or freshly loaded).

        Raises:
            ValueError: When no loader_fn is available.
            FileNotFoundError: When *path* does not exist (propagated from loader).
        """
        fn = loader_fn or self._loader_fn
        if fn is None:
            raise ValueError("loader_fn must be provided either at construction or per call")

        path = Path(path)
        try:
            stat = path.stat()
            current_mtime = stat.st_mtime
            current_size = stat.st_size
        except FileNotFoundError:
            # File gone → invalidate cache, propagate error from loader
            with self._lock:
                self._entries.pop(path, None)
            raise

        with self._lock:
            entry = self._entries.get(path)
            if entry is not None and entry.mtime == current_mtime and entry.file_size == current_size:
                return entry.value

        # Load outside lock to avoid blocking other threads
        value = fn(path)

        with self._lock:
            # Re-check: another thread may have updated cache while we loaded
            existing = self._entries.get(path)
            if existing is None or existing.mtime != current_mtime or existing.file_size != current_size:
                self._entries[path] = _CacheEntry(value=value, mtime=current_mtime, file_size=current_size)

        return value

    def invalidate(self, path: Path | None = None) -> None:
        """Invalidate a specific path, or all entries when path is None."""
        with self._lock:
            if path is None:
                self._entries.clear()
            else:
                self._entries.pop(Path(path), None)

    def is_cached(self, path: Path) -> bool:
        """Return True when path has a valid cache entry."""
        with self._lock:
            return Path(path) in self._entries

    @property
    def cached_paths(self) -> list[Path]:
        with self._lock:
            return list(self._entries.keys())


# ---------------------------------------------------------------------------
# Module-level shared instances (singleton per file type)
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# Shared cache for pnl_state.json – used by PnLTracker and dashboard_service
pnl_state_cache: MtimeFileCache[dict] = MtimeFileCache(loader_fn=_load_json)

# Shared cache for other JSON config files
json_file_cache: MtimeFileCache[Any] = MtimeFileCache(loader_fn=_load_json)
