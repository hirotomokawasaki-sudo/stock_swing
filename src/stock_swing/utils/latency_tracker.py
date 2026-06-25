"""API latency tracking (P2-A)."""

from __future__ import annotations

import csv
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator


@dataclass
class LatencyRecord:
    endpoint: str
    started_at: str
    duration_ms: float
    status: str
    error_type: str = ""
    retry_count: int = 0
    symbol: str = ""


class LatencyTracker:
    """Append-only CSV latency tracker."""

    def __init__(self, out_path: Path) -> None:
        self.out_path = out_path
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self._records: list[LatencyRecord] = []

    @contextmanager
    def track(
        self, endpoint: str, *, symbol: str = "", retry_count: int = 0
    ) -> Generator[None, None, None]:
        started_at = datetime.now(timezone.utc).isoformat()
        t0 = time.monotonic()
        status = "ok"
        error_type = ""
        try:
            yield
        except Exception as exc:
            status = "error"
            error_type = type(exc).__name__
            raise
        finally:
            duration_ms = round((time.monotonic() - t0) * 1000, 1)
            self._records.append(
                LatencyRecord(
                    endpoint=endpoint,
                    started_at=started_at,
                    duration_ms=duration_ms,
                    status=status,
                    error_type=error_type,
                    retry_count=retry_count,
                    symbol=symbol,
                )
            )

    def flush(self) -> None:
        if not self._records:
            return
        write_header = not self.out_path.exists()
        with open(self.out_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "endpoint",
                    "started_at",
                    "duration_ms",
                    "status",
                    "error_type",
                    "retry_count",
                    "symbol",
                ],
            )
            if write_header:
                writer.writeheader()
            for record in self._records:
                writer.writerow(
                    {
                        "endpoint": record.endpoint,
                        "started_at": record.started_at,
                        "duration_ms": record.duration_ms,
                        "status": record.status,
                        "error_type": record.error_type,
                        "retry_count": record.retry_count,
                        "symbol": record.symbol,
                    }
                )
        self._records.clear()

    @property
    def record_count(self) -> int:
        return len(self._records)
