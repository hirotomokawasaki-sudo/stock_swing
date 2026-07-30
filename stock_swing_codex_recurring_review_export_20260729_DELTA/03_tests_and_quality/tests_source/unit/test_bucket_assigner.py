import pytest

from stock_swing.experiments.bucket_assigner import Bucket, BucketAssigner


def test_bucket_assignment_is_stable() -> None:
    assigner = BucketAssigner(
        buckets=[
            Bucket("control", 80, "s1", 80),
            Bucket("test", 20, "s2", 20),
        ],
        salt="x",
    )
    assert assigner.assign_symbol("KLAC") == assigner.assign_symbol("KLAC")


def test_bucket_assignment_different_symbols_can_differ() -> None:
    assigner = BucketAssigner(
        buckets=[
            Bucket("control", 80, "s1", 80),
            Bucket("test", 20, "s2", 20),
        ],
        salt="stock-swing-20260624",
    )
    results = {assigner.assign_symbol(sym).name for sym in ["KLAC", "MRVL", "PLTR", "NOW", "NVDA", "INTU", "DELL", "CIEN"]}
    assert "control" in results


def test_bucket_invalid_allocation_raises() -> None:
    with pytest.raises(ValueError, match="sum to 100"):
        BucketAssigner(
            buckets=[
                Bucket("control", 70, "s1", 70),
                Bucket("test", 20, "s2", 20),
            ],
            salt="x",
        )
