from stock_swing.guardrails.flatten_plan import build_flatten_plan


def test_flatten_plan_prioritizes_largest_losers() -> None:
    plan = build_flatten_plan(
        [
            {"symbol": "AAA", "qty": 10, "unrealized_pct": -1},
            {"symbol": "BBB", "qty": 10, "unrealized_pct": -5},
        ],
        reason="test",
    )
    assert [item.symbol for item in plan] == ["BBB", "AAA"]


def test_flatten_plan_only_losers_excludes_winners() -> None:
    plan = build_flatten_plan(
        [
            {"symbol": "WIN", "qty": 10, "unrealized_pct": 5},
            {"symbol": "LOSE", "qty": 10, "unrealized_pct": -3},
        ],
        reason="flatten_risky",
        only_losers=True,
    )
    assert len(plan) == 1
    assert plan[0].symbol == "LOSE"


def test_flatten_plan_skips_zero_qty() -> None:
    plan = build_flatten_plan(
        [
            {"symbol": "ZERO", "qty": 0, "unrealized_pct": -10},
            {"symbol": "VALID", "qty": 5, "unrealized_pct": -2},
        ],
        reason="test",
    )
    assert len(plan) == 1
    assert plan[0].symbol == "VALID"


def test_flatten_plan_max_orders_respected() -> None:
    positions = [{"symbol": f"SYM{i}", "qty": 1, "unrealized_pct": -i} for i in range(1, 10)]
    plan = build_flatten_plan(positions, reason="test", max_orders=3)
    assert len(plan) == 3


def test_flatten_plan_empty_positions() -> None:
    plan = build_flatten_plan([], reason="test")
    assert plan == []
