"""Session-aware guards for daily-close price overrides."""

from datetime import UTC, datetime

import pytest

from stock_swing.sources.massive_client import MassiveBar
from stock_swing.utils.stale_price import apply_price_overrides, compute_stale_price_overrides


class FakeMassive:
    def __init__(self, *, close: float, bar_date: str) -> None:
        self.close = close
        self.bar_date = bar_date

    def fetch_daily_bars(self, symbol: str, from_date: str, to_date: str, limit: int = 7) -> list[MassiveBar]:
        timestamp = datetime.fromisoformat(f"{self.bar_date}T04:00:00+00:00")
        return [
            MassiveBar(
                timestamp=timestamp,
                open=self.close,
                high=self.close,
                low=self.close,
                close=self.close,
                volume=100,
            )
        ]


PATH_INCIDENT_AT = datetime(2026, 9, 4, 19, 55, tzinfo=UTC)  # Friday 15:55 ET


@pytest.mark.parametrize(
    "as_of",
    [
        datetime(2026, 9, 4, 12, 0, tzinfo=UTC),  # Friday 08:00 ET, pre-market
        PATH_INCIDENT_AT,  # Friday 15:55 ET, regular session
        datetime(2026, 9, 4, 21, 0, tzinfo=UTC),  # Friday 17:00 ET, after-hours
    ],
)
def test_compute_overrides_rejects_prior_day_close_in_every_live_session(as_of: datetime) -> None:
    overrides, _, errors = compute_stale_price_overrides(
        [{"symbol": "PATH", "current_price": "15.23"}],
        FakeMassive(close=18.22, bar_date="2026-09-03"),
        min_deviation_pct=5.0,
        as_of=as_of,
    )

    assert errors == []
    assert overrides == {}


def test_compute_overrides_path_incident_rejects_prior_day_close_during_live_session() -> None:
    """Regression: 2026-09-04 PATH emergency-stop masking incident.

    Commit: session-aware stale-price guard (this change).
    Root cause: a live broker price of $15.23 was replaced with Massive's
    prior-session $18.22 daily close during regular market hours.
    """
    overrides, logs, errors = compute_stale_price_overrides(
        [{"symbol": "PATH", "current_price": "15.23"}],
        FakeMassive(close=18.22, bar_date="2026-09-03"),
        min_deviation_pct=5.0,
        as_of=PATH_INCIDENT_AT,
    )

    assert overrides == {}, "prior-session daily close must not override a live-session broker price"
    assert errors == [], "session guard is an expected skip, not a source error"
    assert any("PATH" in line and "session guard" in line for line in logs), (
        "operator log must explain why the override was rejected"
    )


def test_compute_overrides_allows_same_session_date_during_regular_hours() -> None:
    overrides, _, errors = compute_stale_price_overrides(
        [{"symbol": "PATH", "current_price": "15.23"}],
        FakeMassive(close=18.22, bar_date="2026-09-04"),
        min_deviation_pct=5.0,
        as_of=PATH_INCIDENT_AT,
    )

    assert errors == []
    assert overrides["PATH"]["fresh_price"] == pytest.approx(18.22)


def test_compute_overrides_allows_prior_session_close_when_market_is_closed() -> None:
    saturday = datetime(2026, 9, 5, 15, 0, tzinfo=UTC)
    overrides, _, errors = compute_stale_price_overrides(
        [{"symbol": "PATH", "current_price": "15.23"}],
        FakeMassive(close=18.22, bar_date="2026-09-04"),
        min_deviation_pct=5.0,
        as_of=saturday,
    )

    assert errors == []
    assert overrides["PATH"]["fresh_price"] == pytest.approx(18.22)


def test_apply_overrides_rejects_persisted_prior_day_close_during_live_session() -> None:
    positions = {"PATH": {"symbol": "PATH", "current_price": 15.23}}
    overrides = {"PATH": {"fresh_price": 18.22, "date": "2026-09-03"}}

    applied = apply_price_overrides(positions, overrides, as_of=PATH_INCIDENT_AT)

    assert applied == 0, "persisted stale overrides must be guarded at application time too"
    assert positions["PATH"]["current_price"] == pytest.approx(15.23)


def test_apply_overrides_rejects_missing_bar_date_during_live_session() -> None:
    positions = {"PATH": {"symbol": "PATH", "current_price": 15.23}}
    overrides = {"PATH": {"fresh_price": 18.22}}

    applied = apply_price_overrides(positions, overrides, as_of=PATH_INCIDENT_AT)

    assert applied == 0, "unknown-age daily close must fail closed during a live session"
    assert positions["PATH"]["current_price"] == pytest.approx(15.23)


def test_apply_overrides_allows_same_date_during_live_session() -> None:
    positions = {"PATH": {"symbol": "PATH", "current_price": 15.23}}
    overrides = {"PATH": {"fresh_price": 18.22, "date": "2026-09-04"}}

    applied = apply_price_overrides(positions, overrides, as_of=PATH_INCIDENT_AT)

    assert applied == 1
    assert positions["PATH"]["current_price"] == pytest.approx(18.22)
