from pathlib import Path

from stock_swing.experiments import build_experiment_context


def test_experiment_context_is_stable_for_same_config(tmp_path: Path) -> None:
    config = {"a": 1, "b": {"c": 2}}
    ctx1 = build_experiment_context(
        repo_root=tmp_path,
        run_id="run-1",
        strategy_version="s1",
        prompt_version="p1",
        feature_schema_version="f1",
        config_payload=config,
    )
    ctx2 = build_experiment_context(
        repo_root=tmp_path,
        run_id="run-2",
        strategy_version="s1",
        prompt_version="p1",
        feature_schema_version="f1",
        config_payload={"b": {"c": 2}, "a": 1},
    )
    assert ctx1.config_hash == ctx2.config_hash


def test_experiment_context_attach_to_adds_fields(tmp_path: Path) -> None:
    ctx = build_experiment_context(
        repo_root=tmp_path,
        run_id="run-1",
        strategy_version="s1",
        prompt_version="p1",
        feature_schema_version="f1",
        config_payload={"x": 1},
        experiment_id="exp-test",
    )
    payload = ctx.attach_to({"symbol": "KLAC"})
    assert payload["experiment_id"] == "exp-test"
    assert payload["run_id"] == "run-1"
    assert "config_hash" in payload


def test_experiment_id_auto_generated_when_none(tmp_path: Path) -> None:
    ctx = build_experiment_context(
        repo_root=tmp_path,
        run_id="run-auto",
        strategy_version="s1",
        prompt_version="p1",
        feature_schema_version="f1",
        config_payload={"x": 1},
    )
    assert ctx.experiment_id.startswith("exp-")
