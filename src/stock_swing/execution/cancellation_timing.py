"""Bounded equity cancellation-time qualification, not a broker-hours authority.

Reuses MarketCalendar holidays and zoneinfo. Early closes are pinned to the
NYSE 2026–2028 release (2025-12-23); outside that reviewed range refuse selection.
No shared MarketCalendar behavior or cancellation policy/age threshold is changed.
"""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from stock_swing.utils.market_calendar import MarketCalendar

ET = ZoneInfo('America/New_York')
EARLY_CLOSES = frozenset({'2026-11-27','2026-12-24','2027-11-26','2028-07-03','2028-11-24'})

def aware_utc(value):
    if not isinstance(value,datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('order_time_unqualified')
    return value.astimezone(timezone.utc)

def session_bounds(day):
    if day.year not in {2026,2027,2028}:raise ValueError('cancel_calendar_year_unqualified')
    probe=datetime.combine(day,time(12),ET)
    if day.weekday()>=5 or MarketCalendar.is_us_holiday(probe)[0]:return None
    close=time(13) if day.isoformat() in EARLY_CLOSES else MarketCalendar.REGULAR_END
    return datetime.combine(day,MarketCalendar.REGULAR_START,ET),datetime.combine(day,close,ET)

def last_open(now):
    now=aware_utc(now);day=now.astimezone(ET).date()
    for _ in range(10):
        bounds=session_bounds(day)
        if bounds and bounds[0]<=now:return bounds[0].astimezone(timezone.utc)
        day-=timedelta(days=1)
    raise ValueError('cancel_session_unavailable')

def submitted_time(value,now):
    if not isinstance(value,str):raise ValueError('order_time_unqualified')
    try:dt=aware_utc(datetime.fromisoformat(value.replace('Z','+00:00')))
    except (ValueError,TypeError,OverflowError):raise ValueError('order_time_unqualified') from None
    if dt>aware_utc(now):raise ValueError('order_time_in_future')
    return dt

def after_hours(dt):
    dt=aware_utc(dt).astimezone(ET);bounds=session_bounds(dt.date())
    # Existing selector's after-close-to-20:00 ET policy, not all broker sessions.
    return bool(bounds and bounds[1]<=dt<datetime.combine(dt.date(),MarketCalendar.AFTER_HOURS_END,ET))

def regular_hours(dt):
    dt=aware_utc(dt).astimezone(ET);bounds=session_bounds(dt.date())
    return bool(bounds and bounds[0]<=dt<bounds[1])
