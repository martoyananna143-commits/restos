"""Timezone utilities for Moscow time."""

import pytz
from datetime import datetime
from typing import Optional

# Moscow timezone
MOSCOW_TZ = pytz.timezone('Europe/Moscow')


def now_moscow() -> datetime:
    """Get current time in Moscow timezone."""
    return datetime.now(MOSCOW_TZ)


def to_moscow(dt: Optional[datetime]) -> Optional[datetime]:
    """Convert datetime to Moscow timezone."""
    if dt is None:
        return None
    
    # If datetime is naive, assume it's UTC
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    
    # Convert to Moscow timezone
    return dt.astimezone(MOSCOW_TZ)


def moscow_datetime(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    """Create a datetime in Moscow timezone."""
    return MOSCOW_TZ.localize(datetime(year, month, day, hour, minute, second))
