#!/usr/bin/env python3
"""Market status check CLI.

Checks current market status including:
- Market open/closed
- US holidays
- Daylight saving time
- Market hours in JST

Usage:
    python -m stock_swing.cli.market_check [--date YYYY-MM-DD]
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from stock_swing.utils import (
    MarketCalendar,
    is_market_open,
    is_us_holiday,
    get_market_hours,
    is_daylight_saving_time,
)


def main():
    """Main market check entry point."""
    parser = argparse.ArgumentParser(description="Check market status")
    parser.add_argument(
        "--date",
        type=str,
        help="Date to check (YYYY-MM-DD format, defaults to today)",
    )
    
    args = parser.parse_args()
    
    # Parse date
    if args.date:
        try:
            check_date = datetime.strptime(args.date, "%Y-%m-%d")
            check_date = check_date.replace(tzinfo=ZoneInfo("Asia/Tokyo"))
        except ValueError:
            print(f"❌ Invalid date format: {args.date}")
            print("   Use YYYY-MM-DD format")
            return 1
    else:
        check_date = datetime.now(ZoneInfo("Asia/Tokyo"))
    
    print("🏛️  US Market Status Check")
    print("=" * 60)
    print(f"📅 Checking: {check_date.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print()
    
    # Check if holiday
    is_holiday, holiday_name = MarketCalendar.is_us_holiday(check_date)
    if is_holiday:
        print(f"🗓️  Holiday: {holiday_name}")
        print("   Market is CLOSED")
    else:
        print("✅ Not a holiday")
    print()
    
    # Check if weekend
    weekday = check_date.strftime("%A")
    if check_date.weekday() >= 5:
        print(f"📆 {weekday} (Weekend)")
        print("   Market is CLOSED")
    else:
        print(f"📆 {weekday} (Weekday)")
    print()
    
    # Check DST
    is_dst = is_daylight_saving_time(check_date)
    offset = 13 if is_dst else 14
    print(f"🌞 Daylight Saving Time: {'Yes (Summer)' if is_dst else 'No (Winter)'}")
    print(f"   ET to JST offset: {offset} hours")
    print()
    
    # Market hours
    market_hours = get_market_hours(check_date)
    print("⏰ Market Hours (JST):")
    
    for session, (start, end) in market_hours.items():
        session_name = session.replace("_", " ").title()
        print(f"   {session_name:12}: {start.strftime('%H:%M')} - {end.strftime('%H:%M')}")
    print()
    
    # Current status
    is_open, status = MarketCalendar.is_market_open(check_date)
    print("📊 Current Status:")
    if is_open:
        print(f"   ✅ {status}")
    else:
        print(f"   ❌ {status}")
    print()
    
    # Next market open/close
    print("🔔 Next Events:")
    if is_holiday or check_date.weekday() >= 5:
        print("   ℹ️  Market will open on next trading day")
    elif is_open:
        # Find next close
        current_time = check_date.time()
        for session, (start, end) in market_hours.items():
            if start <= current_time < end:
                session_name = session.replace("_", " ").title()
                print(f"   📉 {session_name} closes at {end.strftime('%H:%M')} JST")
                break
    else:
        # Find next open
        current_time = check_date.time()
        next_session = None
        
        for session, (start, end) in market_hours.items():
            if current_time < start:
                next_session = (session, start)
                break
        
        if next_session:
            session_name, start_time = next_session
            session_display = session_name.replace("_", " ").title()
            print(f"   📈 {session_display} opens at {start_time.strftime('%H:%M')} JST")
        else:
            print("   ℹ️  Market opens tomorrow")
    
    print()
    print("=" * 60)
    
    # Return appropriate exit code
    if is_open:
        return 0  # Market open
    else:
        return 1  # Market closed


if __name__ == "__main__":
    sys.exit(main())
