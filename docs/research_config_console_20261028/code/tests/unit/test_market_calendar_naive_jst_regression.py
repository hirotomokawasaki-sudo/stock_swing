"""Regression: 2026-10-24 false weekend blocked US Friday paper orders.

Pre-fix commit: 2eb041e. paper_demo supplied naive datetime.now() on a JST
host; calendar gates checked its unconverted Saturday date as if it were ET.
Acceptance: legacy naive JST and aware representations of the same instant
must agree, without opening real weekends, holidays or off-hours to BUYs.
"""

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from stock_swing.cli.paper_demo import (
    _filter_buys_outside_regular_hours,
    _filter_sells_outside_regular_hours,
)
from stock_swing.utils.market_calendar import MarketCalendar


@pytest.mark.parametrize("representation", ["naive-jst", "Asia/Tokyo", "UTC", "America/New_York"])
@pytest.mark.parametrize(
    "stamp,regular,session",
    [
        ("2026-10-24T01:00", True, "Regular hours"),  # Incident midday.
        ("2026-10-24T04:55", True, "Regular hours"),  # Incident near-close.
        ("2026-11-07T01:00", True, "Regular hours"),  # Standard time.
        ("2026-11-07T05:55", True, "Regular hours"),
        ("2026-10-23T22:29", False, "Pre-market"),
        ("2026-10-23T22:30", True, "Regular hours"),
        ("2026-10-24T05:00", False, "After-hours"),
        ("2026-11-06T23:29", False, "Pre-market"),
        ("2026-11-06T23:30", True, "Regular hours"),
        ("2026-11-07T06:00", False, "After-hours"),
        ("2026-10-24T23:30", False, "Weekend"),
        ("2026-10-26T01:00", False, "Weekend"),
        ("2026-06-20T01:00", False, "Juneteenth"),  # US holiday, JST next day.
    ],
)
def test_calendar_same_instant_preserves_exchange_date(stamp, regular, session, representation):
    """Incident 2026-10-24 / pre-fix 2eb041e: normalize before calendar checks."""
    naive = datetime.fromisoformat(stamp)
    dt = naive if representation == "naive-jst" else naive.replace(
        tzinfo=ZoneInfo("Asia/Tokyo")
    ).astimezone(ZoneInfo(representation))

    is_regular, regular_message = MarketCalendar.is_regular_market_hours(dt)
    is_open, open_message = MarketCalendar.is_market_open(dt)

    assert is_regular is regular, f"{stamp} ({representation}): {regular_message}"
    assert is_open is (session in {"Pre-market", "Regular hours", "After-hours"}), open_message
    assert session in open_message, f"{stamp} ({representation}): {open_message}"
    if session in {"Weekend", "Juneteenth"}:
        assert session in regular_message, "Regular gate must preserve the actual closed reason"


@pytest.mark.parametrize("stamp,regular", [
    ("2026-10-24T01:00", True),
    ("2026-10-24T04:55", True),
    ("2026-10-24T05:00", False),
    ("2026-10-24T23:30", False),
])
@pytest.mark.parametrize("aware", [False, True], ids=["legacy-naive-jst", "aware-utc"])
def test_order_filters_use_exchange_session_without_loosening_offhours(monkeypatch, stamp, regular, aware):
    """Incident 2026-10-24 / pre-fix 2eb041e: propagate session to BUY and SELL."""
    monkeypatch.delenv("PAPER_DEMO_ALLOW_OFFHOURS_BUYS", raising=False)
    monkeypatch.delenv("PAPER_DEMO_ALLOW_OFFHOURS_SELLS", raising=False)
    dt = datetime.fromisoformat(stamp)
    if aware:
        dt = dt.replace(tzinfo=ZoneInfo("Asia/Tokyo")).astimezone(ZoneInfo("UTC"))
    buy = SimpleNamespace(action="buy", symbol="IBM", evidence={})
    sell = SimpleNamespace(action="sell", symbol="FICO", evidence={"return_pct": -0.05})
    emergency = SimpleNamespace(action="sell", symbol="NOW", evidence={"return_pct": -0.13})
    decisions = [buy, sell, emergency]

    after_buy, blocked = _filter_buys_outside_regular_hours(decisions, dt)
    after_sell, deferred = _filter_sells_outside_regular_hours(after_buy, dt)

    assert after_sell == (decisions if regular else [emergency]), "Session must reach both real order filters"
    assert len(blocked) == (0 if regular else 1), "Off-hours BUY block must remain active"
    assert len(deferred) == (0 if regular else 1), "Only non-catastrophic off-hours SELLs are deferred"
