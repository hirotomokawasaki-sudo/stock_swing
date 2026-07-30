from pathlib import Path

from stock_swing.experiments import ExperimentRegistry, build_experiment_context


def test_experiment_registry_writes_manifest_and_index(tmp_path: Path) -> None:
    ctx = build_experiment_context(
        repo_root=tmp_path,
        run_id="run-1",
        strategy_version="s1",
        prompt_version="p1",
        feature_schema_version="f1",
        config_payload={"risk": 1},
        experiment_id="exp-test",
    )
    registry = ExperimentRegistry(tmp_path / "experiments")
    experiment_dir = registry.register(ctx)

    assert (experiment_dir / "manifest.json").exists()
    assert registry.get_manifest("exp-test")["experiment_id"] == "exp-test"
    assert registry.list_experiments(limit=1)[0]["experiment_id"] == "exp-test"


def test_experiment_registry_multiple_entries(tmp_path: Path) -> None:
    registry = ExperimentRegistry(tmp_path / "experiments")
    for i in range(3):
        ctx = build_experiment_context(
            repo_root=tmp_path,
            run_id=f"run-{i}",
            strategy_version="s1",
            prompt_version="p1",
            feature_schema_version="f1",
            config_payload={"i": i},
            experiment_id=f"exp-{i}",
        )
        registry.register(ctx)
    rows = registry.list_experiments(limit=10)
    assert len(rows) == 3
