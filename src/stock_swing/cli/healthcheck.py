from __future__ import annotations

from pathlib import Path

from stock_swing.core.runtime import read_runtime_mode


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    mode = read_runtime_mode(project_root)
    print({"status": "ok", "runtime_mode": mode})


if __name__ == "__main__":
    main()
