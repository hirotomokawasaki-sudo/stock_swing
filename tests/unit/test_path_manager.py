from pathlib import Path

from stock_swing.core.path_manager import PathManager


def test_data_stage_path() -> None:
    project_root = Path(__file__).resolve().parents[2]
    path = PathManager(project_root).data_stage("raw")
    assert path.name == "raw"
