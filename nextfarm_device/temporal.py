"""Deterministic Vietnamese time-of-day semantics used by the query planner."""
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=7))
PERIODS = {
    'morning': (5, 11),
    'noon': (11, 13.5),
    'afternoon': (13.5, 18),
    'evening': (18, 24),
}

def local_day(now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(TZ)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)

def resolve_day_period(period, now=None):
    """Return an explicit local-time interval; noon is never interpreted as NOW."""
    day = local_day(now)
    if period not in PERIODS:
        return None
    start_hour, end_hour = PERIODS[period]
    start = day + timedelta(hours=start_hour)
    end = day + timedelta(hours=end_hour)
    current = (now or datetime.now(timezone.utc)).astimezone(TZ)
    # Future portions of today's period cannot contain observations yet.
    if period in {'morning', 'noon', 'afternoon', 'evening'} and current.date() == day.date():
        end = min(end, current)
    return start, max(start, end)
