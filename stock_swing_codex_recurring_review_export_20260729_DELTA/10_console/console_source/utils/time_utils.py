"""Time utilities for console."""

from datetime import datetime
from zoneinfo import ZoneInfo


def now_iso() -> str:
    """Get current time in ISO format (JST)."""
    return datetime.now(ZoneInfo("Asia/Tokyo")).isoformat()


def format_timestamp(dt: datetime) -> str:
    """Format datetime for display."""
    if dt is None:
        return "N/A"
    return dt.strftime("%Y-%m-%d %H:%M:%S")
