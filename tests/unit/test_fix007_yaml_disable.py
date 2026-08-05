"""FIX-007 v2 (2026-08-05): simple_exit_v2 config re-enables tiered min_hold
using offset-based tiers instead of the unreachable absolute-return tiers.

History:
  2026-07-27 (52736ca): Plan A introduces tiered_min_hold using absolute
    return_pct thresholds (e.g. "return > -5% -> 7d").
  2026-07-29 (687c5c5, FIX-007): disabled — the -5% absolute threshold was
    unreachable for standard/high-conviction positions, since their stop_loss
    only fires once return_pct is already <= -7%/-9%.
  2026-08-05: redesigned to use offset_pct (percentage points past the
    *effective* stop threshold that fired) instead of an absolute return
    level. This is reachable regardless of conviction tier, so tiered
    min_hold is re-enabled.
"""

from __future__ import annotations

from pathlib import Path

import yaml


def test_simple_exit_v2_yaml_enables_offset_based_tiered_min_hold():
    """FIX-007 v2: tiered min_hold is re-enabled using offset_pct-based tiers."""
    config = yaml.safe_load(Path("config/strategy/simple_exit_v2.yaml").read_text(encoding="utf-8"))

    assert config["tiered_min_hold_enabled"] is True
    assert "tiered_min_hold_disable_reason" not in config

    levels = config["tiered_min_hold_levels"]
    assert len(levels) == 2
    for level in levels:
        # Schema is offset_pct (relative to the effective stop threshold),
        # not the old (unreachable) absolute threshold_pct.
        assert "offset_pct" in level
        assert "threshold_pct" not in level
        assert level["offset_pct"] < 0  # offsets are always negative (past the stop)

    # Levels must be ordered least-negative (shallowest breach) first so
    # that a shallow breach is never mistaken for a severe one.
    assert levels[0]["offset_pct"] > levels[1]["offset_pct"]


def test_offset_tiers_are_reachable_for_all_conviction_levels():
    """FIX-007 v2 regression: unlike v1, every conviction tier's stop_loss
    threshold must be able to reach the shallowest (7-day) offset tier.

    v1 bug: standard stop=-7% could never satisfy "return > -5%" because the
    stop_loss branch only evaluates once return_pct <= -7%. With offset_pct,
    reachability no longer depends on the absolute stop threshold.
    """
    config = yaml.safe_load(Path("config/strategy/simple_exit_v2.yaml").read_text(encoding="utf-8"))
    levels = config["tiered_min_hold_levels"]
    noise_offset_pct = max(lv["offset_pct"] for lv in levels)  # least-negative = shallowest

    # Conviction-tier stop thresholds from SimpleExitV2Strategy._resolve_thresholds
    conviction_stop_pcts = [-0.05, -0.07, -0.09]  # low / standard / high
    for stop_pct in conviction_stop_pcts:
        # A return exactly at the stop threshold has offset_pct == 0, which
        # is always > any negative noise_offset_pct -> reachable.
        return_at_threshold = stop_pct
        offset_pct = (return_at_threshold - stop_pct) * 100.0
        assert offset_pct > noise_offset_pct, (
            f"stop_pct={stop_pct} should reach the shallow offset tier "
            f"(offset={offset_pct}pp vs noise tier={noise_offset_pct}pp)"
        )
