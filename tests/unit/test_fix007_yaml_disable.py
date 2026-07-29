"""FIX-007: simple_exit_v2 config should disable the unreachable 7-day tier."""

from __future__ import annotations

from pathlib import Path

import yaml


def test_simple_exit_v2_yaml_disables_tiered_min_hold():
    """FIX-007: tiered min_hold must stay disabled until stop logic is redesigned."""
    config = yaml.safe_load(Path("config/strategy/simple_exit_v2.yaml").read_text(encoding="utf-8"))

    assert config["tiered_min_hold_enabled"] is False
    assert "FIX-007" in config["tiered_min_hold_disable_reason"]
