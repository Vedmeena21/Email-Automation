"""Scheduling rules: windows, working days, follow-up cadence. Dates are fixed:
2026-01-05 is a Monday, 2026-01-10/11 the following weekend."""
from datetime import date, datetime, time

import pytz

from app.services import scheduling

TZ = pytz.timezone("Asia/Kolkata")
MON = date(2026, 1, 5)
SAT = date(2026, 1, 10)


def at(d, hh, mm=0):
    return TZ.localize(datetime.combine(d, time(hh, mm)))


def test_weekday_is_working_day_weekend_is_not():
    assert scheduling.is_working_day(MON)
    assert not scheduling.is_working_day(SAT)


def test_holiday_country_mode_skips_republic_day():
    import app.services.app_settings as app_settings
    from dataclasses import replace
    app_settings._cache = replace(app_settings._cache, holiday_mode="country")
    assert not scheduling.is_working_day(date(2026, 1, 26))  # Republic Day (a Monday)


def test_added_before_morning_window_lands_in_it_today():
    t = scheduling.compute_send_time(at(MON, 8))
    assert t.date() == MON and time(9) <= t.time() < time(10)


def test_added_between_windows_lands_in_afternoon_window():
    t = scheduling.compute_send_time(at(MON, 11))
    assert t.date() == MON and time(14) <= t.time() < time(15)


def test_added_inside_a_live_window_never_lands_in_the_past():
    # Regression: compute_send_time used to pick a uniformly random second across
    # the WHOLE window even when `now` was already inside it, so a contact added
    # mid-window could get a scheduled_at earlier than `now` — i.e. in the past.
    now = at(MON, 9, 45)  # window A is 09:00-10:00; already 45 minutes in
    for _ in range(50):
        t = scheduling.compute_send_time(now)
        assert t >= now
        assert t.date() == MON and time(9, 45) <= t.time() < time(10)


def test_added_after_last_window_rolls_to_next_working_day_morning():
    t = scheduling.compute_send_time(at(MON, 16))
    assert t.date() == date(2026, 1, 6) and time(9) <= t.time() < time(10)


def test_added_on_weekend_rolls_to_monday():
    t = scheduling.compute_send_time(at(SAT, 9, 30))
    assert t.date() == date(2026, 1, 12)


def test_reschedule_keeps_future_time():
    future = at(MON, 9, 30)
    assert scheduling.reschedule_if_past(future, now=at(MON, 8)) == future


def test_reschedule_rolls_past_time_forward():
    t = scheduling.reschedule_if_past(at(MON, 9, 30), now=at(MON, 12))
    assert t > at(MON, 12)


def test_followup_time_on_weekend_return_date_rolls_to_monday_morning():
    t = scheduling.followup_time_from(SAT)
    assert t.date() == date(2026, 1, 12) and time(9) <= t.time() < time(10)


def test_working_days_between_pinned_semantics():
    # sent Monday, threshold 5 -> due the NEXT Monday; send day never counts
    assert scheduling.working_days_between(MON, date(2026, 1, 12)) == 5
    assert scheduling.working_days_between(MON, date(2026, 1, 9)) == 4   # Friday
    assert scheduling.working_days_between(MON, MON) == 0
    assert scheduling.working_days_between(MON, date(2026, 1, 4)) == 0   # end < start
