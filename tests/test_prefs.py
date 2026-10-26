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


# --- sidebar order ------------------------------------------------------------
def test_menu_order_keeps_saved_keys_then_adds_new_pages():
    pages = ["dashboard", "guide", "send", "sent"]
    assert prefs.ordered(pages, []) == pages
    assert prefs.ordered(pages, ["send", "gone", "dashboard", "send"]) == [
        "send", "dashboard", "guide", "sent"]


def test_home_can_never_be_hidden():
    db.set_setting("nav_hidden", ["dashboard", "guide"])
    assert prefs.hidden_pages() == {"guide"}


# --- date filters ---------------------------------------------------------------
def test_date_range_includes_both_days():
    from datetime import date

    assert prefs.date_bounds(date(2026, 10, 1), date(2026, 10, 31)) == ("2026-10-01", "2026-11-01")
    assert prefs.date_bounds(None, None) == (None, None)
    clause, values = prefs.date_clause("sent_at", date(2026, 10, 1), None)
    assert clause == " AND sent_at >= ?" and values == ["2026-10-01"]
    # A timestamp late on the last day is inside the range
    assert "2026-10-31T23:59:00" < prefs.date_bounds(None, date(2026, 10, 31))[1]


# --- themes ---------------------------------------------------------------------
def test_every_ready_made_theme_is_valid_and_readable():
    from app.core import themes

    for key, spec in themes.PRESETS.items():
        assert themes.validate(spec) == spec, key
        assert themes.readability_problems(spec) == [], key


def test_a_theme_with_bad_colours_or_no_name_is_refused():
    from app.core import themes

    good = dict(themes.PRESETS["ocean"], name="Mine")
    for broken in (dict(good, name=" "), dict(good, accent="red"),
                   dict(good, gradient=["#ffffff"]), "not a theme"):
        with pytest.raises(ValueError):
            themes.validate(broken)
    # Unknown fonts and places are dropped rather than refused
    cleaned = themes.validate(dict(good, font="Comic Sans", where=["sidebar", "roof"]))
    assert cleaned["font"] == "" and cleaned["where"] == ["sidebar"]


def test_hard_to_read_colours_are_pointed_out():
    from app.core import themes

    murky = dict(themes.PRESETS["ocean"], text="#203038")
    assert themes.readability_problems(murky)


def test_custom_themes_are_saved_found_replaced_and_deleted():
    from app.core import themes

    spec = dict(themes.PRESETS["forest"], name="Office")
    themes.save_custom(spec)
    assert themes.find("custom:office")["name"] == "Office"
    themes.save_custom(dict(spec, name="Office 2"), replacing="Office")
    assert [t["name"] for t in themes.custom_themes()] == ["Office 2"]
    themes.delete_custom("office 2")
    assert themes.custom_themes() == [] and themes.find("custom:Office 2") is None
    assert themes.find("Dark") is None and themes.find("sunset")["name"] == "Sunset"


def test_a_theme_file_round_trips_and_junk_is_refused(tmp_path):
    from app.core import themes

    spec = dict(themes.PRESETS["rose"], name="Shared")
    path = themes.write_file(tmp_path / "shared", spec)
    assert path.suffix == ".hptheme"
    assert themes.read_file(path) == spec

    junk = tmp_path / "junk.hptheme"
    junk.write_text('{"name": "x"}', encoding="utf-8")
    with pytest.raises(ValueError):
        themes.read_file(junk)
    junk.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError):
        themes.read_file(junk)
