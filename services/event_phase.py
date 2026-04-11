"""Event phase detection for smart cache TTL management.

Determines event lifecycle phase (EARLY → PRE_MATCH → LIVE → FINISHED → EXPIRED)
and returns appropriate TTL values for search data and LLM analysis caches.
"""

import re
from enum import Enum
from datetime import datetime, timedelta, timezone, tzinfo


class EventPhase(Enum):
    EARLY = "early"           # >12h before event
    PRE_MATCH = "pre_match"   # ≤12h before event
    LIVE = "live"             # during event
    FINISHED = "finished"     # 0..24h after event end
    EXPIRED = "expired"       # >24h after event end


# Approximate event duration by discipline
EVENT_DURATION: dict[str, timedelta] = {
    "football": timedelta(hours=2),
    "hockey": timedelta(hours=3),
    "basketball": timedelta(hours=2, minutes=30),
    "tennis": timedelta(hours=4),
    "volleyball": timedelta(hours=2, minutes=30),
    "table_tennis": timedelta(hours=1),
    "cs2": timedelta(hours=3),
    "dota2": timedelta(hours=2),
    "lol": timedelta(hours=1, minutes=30),
    "valorant": timedelta(hours=2),
    "mma": timedelta(hours=1),
    "boxing": timedelta(hours=1, minutes=30),
}
_DEFAULT_DURATION = timedelta(hours=3)

# Moscow timezone (UTC+3), no pytz dependency
_MSK = timezone(timedelta(hours=3))

# Phase → single TTL (applies to both search and LLM caches)
_PHASE_TTL: dict[EventPhase, timedelta] = {
    EventPhase.EARLY:     timedelta(days=7),     # effectively infinite until PRE_MATCH
    EventPhase.PRE_MATCH: timedelta(hours=2),     # refresh every 2h
    EventPhase.LIVE:      timedelta(0),           # always fresh
    EventPhase.FINISHED:  timedelta(hours=48),    # serve cache ≤48h
    EventPhase.EXPIRED:   timedelta(0),           # full block
}


def _parse_event_date(date_str: str) -> datetime | None:
    """Parse event date string into a timezone-aware datetime (MSK).

    Supports: DD.MM.YY, DD.MM.YYYY, YYYY-MM-DD. Returns None on failure.
    """
    date_str = date_str.strip()
    if not date_str or date_str == "не указана":
        return None

    formats = [
        ("%d.%m.%y", None),
        ("%d.%m.%Y", None),
        ("%Y-%m-%d", None),
        ("%d-%m-%Y", None),
        ("%d/%m/%Y", None),
    ]
    for fmt, _ in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            # Assume event starts at 18:00 MSK if no time provided
            return dt.replace(hour=18, minute=0, second=0, tzinfo=_MSK)
        except ValueError:
            continue
    return None


def get_event_phase(event_date_str: str, discipline: str = "") -> EventPhase:
    """Determine current event phase based on date and discipline.

    Returns EARLY as safe default when date cannot be parsed.
    """
    event_start = _parse_event_date(event_date_str)
    if event_start is None:
        return EventPhase.EARLY

    now = datetime.now(tz=_MSK)
    duration = EVENT_DURATION.get(discipline.lower().strip(), _DEFAULT_DURATION)
    event_end = event_start + duration

    if now < event_start - timedelta(hours=12):
        return EventPhase.EARLY
    if now < event_start:
        return EventPhase.PRE_MATCH
    if now <= event_end:
        return EventPhase.LIVE
    if now <= event_end + timedelta(hours=24):
        return EventPhase.FINISHED
    return EventPhase.EXPIRED


def get_phase_ttl(phase: EventPhase) -> timedelta:
    """Return cache TTL for the given phase."""
    return _PHASE_TTL[phase]


def should_block_request(phase: EventPhase) -> bool:
    """Return True if new search/LLM requests should be blocked (EXPIRED only)."""
    return phase is EventPhase.EXPIRED


def is_event_expired(phase: EventPhase) -> bool:
    """Return True only for EXPIRED phase (full block, no cache served)."""
    return phase is EventPhase.EXPIRED
