"""Warm-up ramp and daily sending cap.

A brand-new sending domain that suddenly emits hundreds of messages looks
exactly like a compromised account. The ramp raises volume gradually so the
receiving side builds a reputation for you instead of against you.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.core import db
from app.i18n import t

# Day index -> messages allowed that day. Held at the last value afterwards.
# "Safe" is the recommended one. Until v0.7.1 the only ramp was "faster", which
# reaches 100 a day on day 10: too quick for a brand-new mailbox.
PRESETS = {
    "very_safe": [20, 20, 20, 22, 24, 26, 28, 30, 32, 34, 36, 38, 40, 43, 46, 50, 53, 56, 60,
                  64, 68, 72, 76, 80, 85, 90, 95, 100],
    "safe": [20, 20, 25, 25, 30, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 90, 100, 110, 120,
             130, 140, 150],
    "faster": [20, 20, 30, 30, 40, 50, 60, 70, 85, 100, 115, 130, 150, 175, 200],
}
PRESET_NAMES = {
    "very_safe": "Very safe",
    "safe": "Safe (recommended)",
    "faster": "Faster",
    "custom": "My own plan",
}
PRESET_NOTES = {
    "very_safe": "About 4 weeks to reach 100 a day, then stays there. Best for a brand new "
                 "email address or one that has had trouble before.",
    "safe": "About 3 weeks to reach 150 a day, then stays there. Right for most new addresses.",
    "faster": "About 2 weeks to reach 200 a day. Only for an address that already sends "
              "normal business email every day.",
    "custom": "Type how many emails to send on each day. After the last day, the last number "
              "is used every day.",
}
DEFAULT_PRESET = "safe"
DEFAULT_RAMP = PRESETS[DEFAULT_PRESET]
MAX_CUSTOM_DAYS = 90

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
            return t("Warm-up off, daily cap {cap}", cap=self.cap)
        return t("Warm-up day {day_index}: {sent_today}/{cap} sent today",
                 day_index=self.day_index, sent_today=self.sent_today, cap=self.cap)


def preset() -> str:
    chosen = db.get_setting("warmup_preset", DEFAULT_PRESET)
    return chosen if chosen in PRESET_NAMES else DEFAULT_PRESET


def custom_ramp() -> list[int]:
    """The user's own plan, or the recommended one if they have not written one."""
    ramp = db.get_setting("warmup_ramp", None)
    try:
        cleaned = [max(1, int(v)) for v in ramp][:MAX_CUSTOM_DAYS]
    except (TypeError, ValueError):
        return list(DEFAULT_RAMP)
    return cleaned or list(DEFAULT_RAMP)


def ramp_for(name: str) -> list[int]:
    return custom_ramp() if name == "custom" else list(PRESETS.get(name, DEFAULT_RAMP))


def _ramp() -> list[int]:
    return ramp_for(preset())


def build_ramp(start: int, step: int, maximum: int) -> list[int]:
    """A plan from three numbers: start at ``start``, add ``step`` a day, stop at ``maximum``."""
    start, step = max(1, int(start)), max(1, int(step))
    maximum = max(start, int(maximum))
    return (list(range(start, maximum, step)) + [maximum])[:MAX_CUSTOM_DAYS]


def ramp_warnings(ramp: list[int]) -> list[str]:
    """Plain-English warnings for a plan that grows faster than is safe."""
    if not ramp:
        return [t("Add at least one day.")]
    warnings = []
    if ramp[0] > 50:
        warnings.append(t("Starting with more than 50 a day is risky for a new address. "
                          "Start with 20 to 30."))
    fastest = PRESETS["faster"]
    for day, count in enumerate(ramp, start=1):
        limit = fastest[min(day, len(fastest)) - 1]
        if count > limit and day > 1:
            warnings.append(t("Day {day} sends {count}, more than even the Faster plan ({limit}). "
                              "Grow more slowly to stay out of spam folders.",
                              day=day, count=count, limit=limit))
            break
    return warnings


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


def projected_schedule(days: int = 14, ramp: list[int] | None = None) -> list[tuple[int, int]]:
    """(day, cap) pairs for the ramp preview in the UI, for the saved plan or ``ramp``."""
    ramp = ramp or _ramp()
    current = status()
    out = []
    for offset in range(days):
        index = current.day_index + offset
        cap = ramp[min(index, len(ramp)) - 1]
        out.append((index, min(cap, current.provider_limit)))
    return out
