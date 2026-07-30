from pathlib import Path

from stock_swing.experiments.feature_snapshot_store import FeatureSnapshotStore


def test_feature_snapshot_round_trip(tmp_path: Path) -> None:
    store = FeatureSnapshotStore(tmp_path)
    ref = store.save(
        experiment_id="exp1",
        run_id="run1",
        decision_id="d1",
        symbol="KLAC",
        features={"close": 100.5, "rsi": 61},
        schema_version="features-v1",
    )
    loaded = store.load(ref)
    assert loaded["symbol"] == "KLAC"
    assert loaded["features"]["close"] == 100.5


def test_feature_snapshot_uncompressed(tmp_path: Path) -> None:
    store = FeatureSnapshotStore(tmp_path, compress=False)
    ref = store.save(
        experiment_id="exp1",
        run_id="run1",
        decision_id="d2",
        symbol="MRVL",
        features={"close": 75.0},
        schema_version="features-v1",
    )
    loaded = store.load(ref)
    assert loaded["features"]["close"] == 75.0


def test_feature_snapshot_path_contains_symbol(tmp_path: Path) -> None:
    store = FeatureSnapshotStore(tmp_path)
    ref = store.save(
        experiment_id="exp1",
        run_id="run1",
        decision_id="d3",
        symbol="PLTR",
        features={"close": 20.0},
        schema_version="features-v1",
    )
    assert "PLTR" in ref.path
