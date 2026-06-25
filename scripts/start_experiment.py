#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stock_swing.core.run_context import RunContext
from stock_swing.experiments import ExperimentRegistry, build_experiment_context


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--config", default="config/experiments/default_experiment.yaml")
    parser.add_argument("--registry-root", default="data/experiments")
    parser.add_argument("--experiment-id", default=None)
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    config_path = (repo_root / args.config).resolve()
    config_payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    run_context = RunContext.create(command="start_experiment")
    context = build_experiment_context(
        repo_root=repo_root,
        run_id=run_context.run_id,
        strategy_version=str(config_payload["strategy_version"]),
        prompt_version=str(config_payload["prompt_version"]),
        feature_schema_version=str(config_payload["feature_schema_version"]),
        config_payload=config_payload,
        mode=str(config_payload.get("mode", "paper")),
        experiment_id=args.experiment_id,
        notes=str(config_payload.get("notes", "")),
        tags=list(config_payload.get("tags", [])),
    )

    registry = ExperimentRegistry(repo_root / args.registry_root)
    experiment_dir = registry.register(context, extra={"config_path": str(config_path)})
    print(json.dumps({"experiment_dir": str(experiment_dir), **context.to_dict()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
