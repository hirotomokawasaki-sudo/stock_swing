from pathlib import Path

from stock_swing.core.runtime import read_runtime_mode


def test_read_runtime_mode() -> None:
    project_root = Path(__file__).resolve().parents[2]
    assert read_runtime_mode(project_root) == "research"
