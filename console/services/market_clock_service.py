"""Display polling only; never changes trading scheduler, calendar or controls."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from stock_swing.utils.market_calendar import MarketCalendar

# NYSE official hours-calendars, reviewed 2026-10-29; bounded to 2025–2027.
# Existing shared holiday/DST logic is reused, not modified for this display.
EARLY_CLOSE = {'2025-07-03', '2025-11-28', '2025-12-24',
               '2026-11-27', '2026-12-24', '2027-11-26'}
ET = ZoneInfo('America/New_York')


def _session(now):
    et = now.astimezone(ET)
    holiday, _ = MarketCalendar.is_us_holiday(et)
    if et.weekday() >= 5 or holiday:
        return 'closed'
    early = et.date().isoformat() in EARLY_CLOSE
    regular, _ = MarketCalendar.is_regular_market_hours(now)
    if regular and (not early or et.time() < time(13)):
        return 'regular'
    extended, _ = MarketCalendar.is_market_open(now)
    return 'extended' if extended and (not early or et.time() < time(17)) else 'closed'


def get_market_clock(now=None):
    now = now or datetime.now(timezone.utc)
    result = {'as_of': None, 'timezone': 'America/New_York', 'session': 'unknown',
              'refresh_interval_ms': 300000, 'next_transition_at': None,
              'source': 'MarketCalendar + NYSE scheduled early closes 2025-2027',
              'scope': '画面更新の予定市場区分。売買許可/実行時刻/臨時休場の認定ではない。'}
    if not isinstance(now, datetime) or now.tzinfo is None or not 2025 <= now.year <= 2027:
        return result
    try:
        now = now.astimezone(timezone.utc)
        session = _session(now)
        boundaries = []
        for i in range(9):
            day = now.astimezone(ET).date() + timedelta(days=i)
            for hour, minute in [(0,0), (4,0), (9,30), (13,0), (16,0), (17,0), (20,0)]:
                instant = datetime.combine(day, time(hour,minute), ET).astimezone(timezone.utc)
                if instant > now and _session(instant) != session:
                    boundaries.append(instant)
        return {**result, 'as_of': now.isoformat(), 'session': session,
                'refresh_interval_ms': {'regular':300000,'extended':1800000,'closed':3600000}[session],
                'next_transition_at': min(boundaries).isoformat() if boundaries else None}
    except (ValueError, OverflowError):
        return result
