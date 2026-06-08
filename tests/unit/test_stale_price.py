from stock_swing.utils.stale_price import apply_empty_override_guard, apply_price_overrides


def test_apply_empty_override_guard_preserves_previous_on_first_empty_run():
    final_overrides, guard_applied, clear_pending, clear_pending_since = apply_empty_override_guard(
        new_overrides={},
        previous_payload={"overrides": {"CHPX": {"fresh_price": 93.07}}},
        generated_at="2026-05-22T01:00:00+00:00",
    )

    assert final_overrides == {"CHPX": {"fresh_price": 93.07}}
    assert guard_applied is True
    assert clear_pending is True
    assert clear_pending_since == "2026-05-22T01:00:00+00:00"



def test_apply_empty_override_guard_allows_second_consecutive_empty_run_to_clear():
    final_overrides, guard_applied, clear_pending, clear_pending_since = apply_empty_override_guard(
        new_overrides={},
        previous_payload={
            "overrides": {"CHPX": {"fresh_price": 93.07}},
            "clear_pending": True,
            "clear_pending_since": "2026-05-22T01:00:00+00:00",
        },
        generated_at="2026-05-22T02:00:00+00:00",
    )

    assert final_overrides == {}
    assert guard_applied is False
    assert clear_pending is False
    assert clear_pending_since is None



def test_apply_price_overrides_updates_in_place():
    positions = {
        "CHPX": {"symbol": "CHPX", "current_price": 56.4},
        "QTEC": {"symbol": "QTEC", "current_price": 259.55},
    }
    overrides = {
        "CHPX": {"fresh_price": 93.07},
        "QTEC": {"fresh_price": 299.49},
    }

    applied = apply_price_overrides(positions, overrides)

    assert applied == 2
    assert positions["CHPX"]["current_price"] == 93.07
    assert positions["QTEC"]["current_price"] == 299.49
