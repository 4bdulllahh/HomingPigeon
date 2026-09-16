"""Date/time formatting from Settings, and the update-check version comparison."""
from __future__ import annotations

import os
import tempfile
from datetime import datetime

import pytest

from app.core import db, prefs

MOMENT = datetime(2026, 12, 31, 17, 5, 9)


@pytest.fixture(autouse=True)
def temp_db():
    db.close()
    db.init(os.path.join(tempfile.mkdtemp(), "prefs.db"))
    yield
    db.close()


@pytest.mark.parametrize("key,expected", [
    ("dmy", "31/12/2026"), ("mdy", "12/31/2026"), ("ymd", "2026-12-31"), ("long", "31 Dec 2026"),
])
def test_date_formats(key, expected):
    db.set_setting("date_format", key)
    assert prefs.format_date(MOMENT) == expected


def test_time_formats():
    db.set_setting("time_format", "12")
    assert prefs.format_time(MOMENT) == "5:05 PM"
    assert prefs.format_time(MOMENT, seconds=True) == "5:05:09 PM"
    assert prefs.format_time(datetime(2026, 1, 1, 0, 30)) == "12:30 AM"
    db.set_setting("time_format", "24")
    assert prefs.format_time(MOMENT) == "17:05"


def test_iso_strings_from_the_database_are_formatted():
    db.set_setting("date_format", "ymd")
    db.set_setting("time_format", "24")
    assert prefs.format_datetime("2026-12-31T17:05:09") == "2026-12-31  17:05"
    assert prefs.format_datetime("") == ""
    assert prefs.format_datetime("not a date") == "not a date"


def test_send_window_clock_round_trips_in_both_formats():
    for time_format in ("12", "24"):
        db.set_setting("time_format", time_format)
        for hour in range(24):
            stored = f"{hour:02d}:00"
            assert prefs.parse_clock(prefs.format_clock(stored)) == stored


def test_defaults_when_nothing_is_saved():
    assert prefs.get("text_size") == prefs.DEFAULT_TEXT_SIZE
    assert prefs.text_scale() == 1.15
    db.set_setting("text_size", "huge")
    assert prefs.text_scale() == 1.5


def test_update_check_version_comparison():
    from app.services.maintenance import is_newer, version_tuple

    assert version_tuple("v0.2.1 beta") == (0, 2, 1)
    assert version_tuple("v0.3.0") > version_tuple("v0.2.1 beta")
    assert version_tuple("v0.2.0") < version_tuple("v0.2.1 beta")
    assert version_tuple("v0.2.1") == version_tuple("v0.2.1 beta")
    assert is_newer("v0.4.0", "v0.3.0 beta")
    assert not is_newer("v0.3.0", "v0.3.0 beta")
