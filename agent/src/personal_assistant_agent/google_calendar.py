"""Read-only Google Calendar access for the agent.

The agent's trust zone holds only a READ-ONLY calendar token (scope
``calendar.readonly``): even if compromised it can read events but never write —
calendar writes go through the proposal queue. This module is pure: it takes an
already-built Google Calendar API ``service`` (injected) and plain event dicts,
so it carries no ``google`` dependency and is unit-testable with a fake service.
The pa-tools server builds the real service and calls in here.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

# Read-only: list/read events, never modify. The whole point of the trust split.
CALENDAR_READONLY_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


def upcoming_events(
    service: Any,  # google calendar service; duck-typed so this module needs no google import
    time_min: datetime,
    time_max: datetime,
    calendar_id: str = "primary",
) -> list[dict[str, Any]]:
    """Events in [time_min, time_max), expanded and time-ordered.

    ``singleEvents`` expands recurring events into instances; ``orderBy`` is only
    valid alongside it. Both datetimes must be UTC.
    """
    response = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=_to_rfc3339(time_min),
            timeMax=_to_rfc3339(time_max),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    items = response.get("items", [])
    return list(items)


def format_events(events: list[dict[str, Any]]) -> str:
    """Render events as a compact agenda for the briefing.

    Timed events show their start time (in the event's own timezone, which for a
    personal calendar is the user's); all-day events show ``all day``.
    """
    if not events:
        return "No events."
    lines: list[str] = []
    for event in events:
        when = _format_start(event.get("start", {}))
        summary = event.get("summary") or "(no title)"
        line = f"- {when}  {summary}"
        location = event.get("location")
        # Keep real places; drop URL "locations" (Zoom/Meet links) — noise in an agenda.
        if location and not location.lower().startswith(("http://", "https://")):
            line += f"  @ {location}"
        lines.append(line)
    return "\n".join(lines)


def _to_rfc3339(dt: datetime) -> str:
    # Our datetimes are UTC; Google's API wants RFC3339.
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_start(start: dict[str, Any]) -> str:
    if "date" in start:  # all-day events carry 'date', timed ones 'dateTime'
        return "all day"
    raw = start.get("dateTime")
    if not raw:
        return "?"
    try:
        return datetime.fromisoformat(raw).strftime("%H:%M")
    except ValueError:
        return raw
