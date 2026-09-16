"""Warm-up ramp and daily sending cap.

A brand-new sending domain that suddenly emits hundreds of messages looks
exactly like a compromised account. The ramp raises volume gradually so the
receiving side builds a reputation for you instead of against you.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.core import db

# Day index -> messages allowed that day. Held at the last value afterwards.
DEFAULT_RAMP = [20, 20, 30, 30, 40, 50, 60, 70, 85, 100, 115, 130, 150, 175, 200]

# Provider ceilings (recipients per day). The ramp never exceeds these
PROVIDER_LIMITS = {
    "Google Workspace": 2000,
    "Gmail (free)": 500,
    "Microsoft 365": 10000,
    "Outlook.com (free)": 300,
    "Zoho Mail": 1000,
    "Titan Email": 1000,
    "Other / shared hosting": 500,
}


@dataclass
class WarmupStatus:
    day_index: int
    cap: int
    sent_today: int
    started_on: str
    enabled: bool
    provider_limit: int

    @property
    def remaining(self) -> int:
        return max(0, self.cap - self.sent_today)

    @property
    def at_limit(self) -> bool:
        return self.remaining <= 0

    def describe(self) -> str:
        if not self.enabled:
            return f"Warm-up off, daily cap {self.cap}"
        return f"Warm-up day {self.day_index}: {self.sent_today}/{self.cap} sent today"


def _ramp() -> list[int]:
    ramp = db.get_setting("warmup_ramp", DEFAULT_RAMP)
    if not isinstance(ramp, list) or not ramp:
        return DEFAULT_RAMP
    return [int(v) for v in ramp]


def _state() -> dict:
    row = db.query_one("SELECT * FROM warmup_state WHERE id = 1")
    if row is None:
        today = date.today().isoformat()
        db.execute(
            "INSERT INTO warmup_state(id, started_on, day_index, sent_date, sent_today) "
            "VALUES (1, ?, 1, ?, 0)",
            (today, today),
        )
        return {"started_on": today, "day_index": 1, "sent_date": today, "sent_today": 0}
    return dict(row)


def _roll_day(state: dict) -> dict:
    """Advance the ramp when the calendar date has changed."""
    today = date.today().isoformat()
    if state.get("sent_date") == today:
        return state

    # The ramp advances by one step per day that the app is actually used, so a
    # weekend off does not skip you forward to a volume you have not earned.
    new_index = int(state.get("day_index", 1))
    if state.get("sent_today", 0) > 0:
        new_index += 1

    db.execute(
        "UPDATE warmup_state SET day_index = ?, sent_date = ?, sent_today = 0 WHERE id = 1",
        (new_index, today),
    )
    state.update(day_index=new_index, sent_date=today, sent_today=0)
    return state


def status() -> WarmupStatus:
    state = _roll_day(_state())
    enabled = bool(db.get_setting("warmup_enabled", True))
    provider = db.get_setting("provider_limit_name", "Other / shared hosting")
    provider_limit = int(db.get_setting("provider_limit", PROVIDER_LIMITS.get(provider, 500)))

    ramp = _ramp()
    index = max(1, int(state.get("day_index", 1)))
    if enabled:
        cap = ramp[min(index, len(ramp)) - 1]
    else:
        cap = int(db.get_setting("manual_daily_cap", 100))

    cap = min(cap, provider_limit)
    return WarmupStatus(
        day_index=index,
        cap=cap,
        sent_today=int(state.get("sent_today", 0)),
        started_on=str(state.get("started_on", "")),
        enabled=enabled,
        provider_limit=provider_limit,
    )


def record_sent(count: int = 1) -> None:
    state = _roll_day(_state())
    db.execute(
        "UPDATE warmup_state SET sent_today = ?, sent_date = ? WHERE id = 1",
        (int(state.get("sent_today", 0)) + count, date.today().isoformat()),
    )


def effective_cap(campaign_override: int | None = None) -> int:
    """Today's cap, honouring a per-campaign override but never the provider limit."""
    current = status()
    if campaign_override:
        return min(campaign_override, current.provider_limit)
    return current.cap


def remaining_today(campaign_override: int | None = None) -> int:
    current = status()
    cap = effective_cap(campaign_override)
    return max(0, cap - current.sent_today)


def reset() -> None:
    today = date.today().isoformat()
    db.execute(
        "UPDATE warmup_state SET started_on = ?, day_index = 1, sent_date = ?, sent_today = 0 "
        "WHERE id = 1",
        (today, today),
    )


def set_day(day_index: int) -> None:
    """Let an experienced sender skip ahead if the domain is already warm."""
    db.execute("UPDATE warmup_state SET day_index = ? WHERE id = 1", (max(1, int(day_index)),))


def projected_schedule(days: int = 14) -> list[tuple[int, int]]:
    """(day, cap) pairs for the ramp preview in the UI."""
    ramp = _ramp()
    current = status()
    out = []
    for offset in range(days):
        index = current.day_index + offset
        cap = ramp[min(index, len(ramp)) - 1]
        out.append((index, min(cap, current.provider_limit)))
    return out
