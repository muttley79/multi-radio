from datetime import datetime

from radio_monitor.config import SkipRange


def _time_to_minutes(hour: int, minute: int) -> int:
    return hour * 60 + minute


def is_skip_hour(skip_ranges: list[SkipRange], now: datetime | None = None) -> bool:
    """Check if current time falls within any skip range. Supports midnight-crossing and day-of-week filtering."""
    if now is None:
        now = datetime.now()

    now_mins = _time_to_minutes(now.hour, now.minute)
    today = now.weekday()  # 0=Mon … 6=Sun

    for r in skip_ranges:
        if r.days is not None and today not in r.days:
            continue  # wrong day

        start = _time_to_minutes(r.start_hour, r.start_minute)
        end = _time_to_minutes(r.end_hour, r.end_minute)

        if start <= end:
            # Normal range, e.g. 02:00-06:00
            if start <= now_mins < end:
                return True
        else:
            # Midnight-crossing range, e.g. 23:00-06:00
            if now_mins >= start or now_mins < end:
                return True

    return False
