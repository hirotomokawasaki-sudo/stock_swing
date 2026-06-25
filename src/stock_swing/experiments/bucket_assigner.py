from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Bucket:
    name: str
    allocation_pct: float
    strategy_version: str
    max_capital_pct: float


class BucketAssigner:
    def __init__(self, buckets: list[Bucket], salt: str, default_bucket: str = "control") -> None:
        total = sum(bucket.allocation_pct for bucket in buckets)
        if round(total, 6) != 100:
            raise ValueError(f"bucket allocations must sum to 100, got {total}")
        self.buckets = buckets
        self.salt = salt
        self.default_bucket = default_bucket

    def assign_symbol(self, symbol: str) -> Bucket:
        key = f"{self.salt}:{symbol.upper()}".encode("utf-8")
        value = int(hashlib.sha256(key).hexdigest()[:8], 16) / 0xFFFFFFFF * 100
        cursor = 0.0
        for bucket in self.buckets:
            cursor += bucket.allocation_pct
            if value <= cursor:
                return bucket
        for bucket in self.buckets:
            if bucket.name == self.default_bucket:
                return bucket
        return self.buckets[0]
