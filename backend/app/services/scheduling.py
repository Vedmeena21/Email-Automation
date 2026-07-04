"""Send-time scheduling. All timing is driven by the user's app_settings (timezone,
two daily windows, working days, optional per-country holidays), read per call so a
settings change takes effect without a restart. Each send lands at a random second
inside a window; a contact added before a window's end takes that window today, else
the next working day's first window; weekends/holidays/missed sends roll forward."""
from __future__ import annotations

import functools
import random
from datetime import date, datetime, time, timedelta

import holidays as holidays_lib
import pytz

from app.services import app_settings


def _cfg():
    return app_settings.get()


def _tz() -> pytz.BaseTzInfo:
    return pytz.timezone(_cfg().timezone)


@functools.lru_cache(maxsize=8)
def _holiday_calendar(country: str):
    return holidays_lib.country_holidays(country)


def _is_holiday(d: date) -> bool:
    """Whether `d` is a public holiday, when holiday_mode='country' is enabled."""
    cfg = _cfg()
    if cfg.holiday_mode != "country":
        return False
    try:
        return d in _holiday_calendar(cfg.holiday_country)
    except Exception:  # noqa: BLE001 — unknown country code -> treat as no holidays
        return False


def _parse_hhmm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def _windows() -> tuple[tuple[time, time], tuple[time, time]]:
    c = _cfg()
    return (
        (_parse_hhmm(c.window_a_start), _parse_hhmm(c.window_a_end)),
        (_parse_hhmm(c.window_b_start), _parse_hhmm(c.window_b_end)),
    )


def now_tz() -> datetime:
    """Current time in the configured timezone."""
    return datetime.now(_tz())


now_ist = now_tz  # backwards-compatible alias for existing callers


def to_local(dt: datetime) -> datetime:
    """Convert an aware datetime into the configured timezone."""
    return dt.astimezone(_tz())


def is_working_day(d: date) -> bool:
    """A configured working weekday (ISO 1=Mon…7=Sun) that isn't a public holiday."""
    if d.isoweekday() not in _cfg().working_days:
        return False
    return not _is_holiday(d)


def next_working_day(d: date) -> date:
    d += timedelta(days=1)
    while not is_working_day(d):
        d += timedelta(days=1)
    return d


def working_days_between(start: date, end: date) -> int:
    """Working days strictly after `start`, up to and including `end`.

    Defines the follow-up rule: sent Monday with a 5-day threshold means the
    follow-up becomes due the NEXT Monday (Tue+Wed+Thu+Fri+Mon = 5), i.e. the
    send day itself never counts. Pinned by tests — change deliberately.
    """
    if end <= start:
        return 0
    count, d = 0, start
    while d < end:
        d += timedelta(days=1)
        if is_working_day(d):
            count += 1
    return count


def _random_dt_in_window(d: date, window: tuple[time, time], *,
                         not_before: datetime | None = None) -> datetime:
    """Tz-aware datetime at a random second within the window on day `d`.

    `not_before` clamps the earliest possible pick — needed when scheduling into a
    window that's already in progress "today", so the random slot can't land in the
    past (before `now`) inside that same window.
    """
    tz = _tz()
    start_dt = tz.localize(datetime.combine(d, window[0]))
    end_dt = tz.localize(datetime.combine(d, window[1]))
    if not_before is not None and not_before > start_dt:
        start_dt = not_before
    span = int((end_dt - start_dt).total_seconds())
    return start_dt + timedelta(seconds=random.randint(0, max(span - 1, 0)))


def compute_send_time(now: datetime | None = None) -> datetime:
    """Pick the next valid send datetime for a contact added at `now` (tz-aware)."""
    tz = _tz()
    if now is None:
        now = datetime.now(tz)
    elif now.tzinfo is None:
        now = tz.localize(now)
    else:
        now = now.astimezone(tz)

    window_a, window_b = _windows()
    today = now.date()
    if is_working_day(today):
        if now.time() < window_a[1]:
            return _random_dt_in_window(today, window_a, not_before=now)
        if now.time() < window_b[1]:
            return _random_dt_in_window(today, window_b, not_before=now)
    return _random_dt_in_window(next_working_day(today), window_a)


def reschedule_if_past(scheduled_at: datetime, now: datetime | None = None) -> datetime:
    """Roll a past-due time to the next valid window; keep it if still in the future."""
    tz = _tz()
    if now is None:
        now = datetime.now(tz)
    if scheduled_at.tzinfo is None:
        scheduled_at = tz.localize(scheduled_at)
    if scheduled_at > now:
        return scheduled_at
    return compute_send_time(now)


def followup_time_from(return_date: date) -> datetime:
    """OOO follow-up time: the return date (or next working day), first window."""
    window_a, _ = _windows()
    d = return_date if is_working_day(return_date) else next_working_day(return_date)
    return _random_dt_in_window(d, window_a)
