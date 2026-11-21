import datetime
import random

import scheduler


GMT8 = scheduler.GMT8


def _at(year, month, day, hour, minute):
    return datetime.datetime(year, month, day, hour, minute, tzinfo=GMT8)


def test_fixed_time_today():
    now = _at(2026, 1, 1, 8, 0)
    target = scheduler.calculate_next_run_time("fixed", "09:00", now=now)
    assert target == _at(2026, 1, 1, 9, 0)


def test_fixed_time_rolls_to_tomorrow():
    now = _at(2026, 1, 1, 10, 0)
    target = scheduler.calculate_next_run_time("fixed", "09:00", now=now)
    assert target == _at(2026, 1, 2, 9, 0)


def test_range_in_window_runs_now():
    now = _at(2026, 1, 1, 10, 0)
    target = scheduler.calculate_next_run_time(
        "range", "09:00-21:00", now=now, rng=random.Random(1)
    )
    assert now <= target <= now + datetime.timedelta(seconds=5)


def test_range_before_window_is_today():
    now = _at(2026, 1, 1, 8, 0)
    target = scheduler.calculate_next_run_time(
        "range", "09:00-21:00", now=now, rng=random.Random(1)
    )
    assert _at(2026, 1, 1, 9, 0) <= target <= _at(2026, 1, 1, 21, 0)


def test_range_after_window_is_tomorrow():
    now = _at(2026, 1, 1, 22, 0)
    target = scheduler.calculate_next_run_time(
        "range", "09:00-21:00", now=now, rng=random.Random(1)
    )
    assert _at(2026, 1, 2, 9, 0) <= target <= _at(2026, 1, 2, 21, 0)


def test_overnight_range_in_window_runs_now():
    now = _at(2026, 1, 1, 1, 0)
    target = scheduler.calculate_next_run_time(
        "range", "22:00-02:00", now=now, rng=random.Random(1)
    )
    assert now <= target <= now + datetime.timedelta(seconds=5)


def test_overnight_range_daytime_is_tonight():
    now = _at(2026, 1, 1, 12, 0)
    target = scheduler.calculate_next_run_time(
        "range", "22:00-02:00", now=now, rng=random.Random(1)
    )
    assert _at(2026, 1, 1, 22, 0) <= target <= _at(2026, 1, 2, 2, 0)


def test_completed_run_inside_window_waits_until_tomorrow():
    now = _at(2026, 1, 1, 10, 0)
    target = scheduler.calculate_next_run_time(
        "range",
        "09:00-21:00",
        now=now,
        rng=random.Random(1),
        allow_immediate=False,
    )
    assert _at(2026, 1, 2, 9, 0) <= target <= _at(2026, 1, 2, 21, 0)


def test_completed_overnight_run_late_evening_waits_until_tomorrow():
    now = _at(2026, 1, 1, 23, 0)
    target = scheduler.calculate_next_run_time(
        "range",
        "22:00-02:00",
        now=now,
        rng=random.Random(1),
        allow_immediate=False,
    )
    assert _at(2026, 1, 2, 22, 0) <= target <= _at(2026, 1, 3, 2, 0)


def test_completed_overnight_run_early_morning_waits_until_tonight():
    now = _at(2026, 1, 2, 1, 0)
    target = scheduler.calculate_next_run_time(
        "range",
        "22:00-02:00",
        now=now,
        rng=random.Random(1),
        allow_immediate=False,
    )
    assert _at(2026, 1, 2, 22, 0) <= target <= _at(2026, 1, 3, 2, 0)


def test_get_run_config_defaults_and_fallback(monkeypatch):
    monkeypatch.delenv("RUN_AT", raising=False)
    assert scheduler.get_run_config() == ("range", scheduler.DEFAULT_RUN_AT)

    monkeypatch.setenv("RUN_AT", "10:30")
    assert scheduler.get_run_config() == ("fixed", "10:30")

    monkeypatch.setenv("RUN_AT", "10:00-18:00")
    assert scheduler.get_run_config() == ("range", "10:00-18:00")

    monkeypatch.setenv("RUN_AT", "99:99")
    assert scheduler.get_run_config() == ("range", scheduler.FALLBACK_RUN_AT)


def test_parse_hhmm_rejects_invalid_values():
    assert scheduler._parse_hhmm("23:59") == (23, 59)
    assert scheduler._parse_hhmm("24:00") is None
    assert scheduler._parse_hhmm("9:00") is None
    assert scheduler._parse_hhmm("ab:cd") is None
