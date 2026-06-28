from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from personal_assistant_agent.google_calendar import format_events, upcoming_events


class _FakeService:
    """Duck-typed stand-in for the Google Calendar service; records the query."""

    def __init__(self, items: list[dict[str, Any]]) -> None:
        self._items = items
        self.captured: dict[str, Any] = {}

    def events(self) -> _FakeService:
        return self

    def list(self, **kwargs: Any) -> _FakeService:
        self.captured = kwargs
        return self

    def execute(self) -> dict[str, Any]:
        return {"items": self._items}


def test_upcoming_events_passes_query_and_returns_items() -> None:
    svc = _FakeService([{"summary": "Standup"}])
    out = upcoming_events(
        svc,
        datetime(2026, 6, 28, 0, 0, tzinfo=UTC),
        datetime(2026, 6, 29, 0, 0, tzinfo=UTC),
    )
    assert out == [{"summary": "Standup"}]
    # singleEvents+orderBy expand recurrences and sort; bounds are RFC3339 UTC.
    assert svc.captured["singleEvents"] is True
    assert svc.captured["orderBy"] == "startTime"
    assert svc.captured["timeMin"] == "2026-06-28T00:00:00Z"
    assert svc.captured["timeMax"] == "2026-06-29T00:00:00Z"
    assert svc.captured["calendarId"] == "primary"


def test_upcoming_events_honors_calendar_id() -> None:
    svc = _FakeService([])
    upcoming_events(
        svc,
        datetime(2026, 6, 28, tzinfo=UTC),
        datetime(2026, 6, 29, tzinfo=UTC),
        calendar_id="work@group.calendar.google.com",
    )
    assert svc.captured["calendarId"] == "work@group.calendar.google.com"


def test_format_events_timed_shows_start_time() -> None:
    event = {"summary": "Standup", "start": {"dateTime": "2026-06-28T09:30:00-04:00"}}
    assert format_events([event]) == "- 09:30  Standup"


def test_format_events_all_day() -> None:
    out = format_events([{"summary": "Holiday", "start": {"date": "2026-06-28"}}])
    assert "all day" in out and "Holiday" in out


def test_format_events_includes_location() -> None:
    event = {
        "summary": "Lunch",
        "start": {"dateTime": "2026-06-28T12:00:00-04:00"},
        "location": "Cafe",
    }
    assert "@ Cafe" in format_events([event])


def test_format_events_drops_url_location() -> None:
    event = {
        "summary": "Power Yoga",
        "start": {"dateTime": "2026-06-28T17:45:00-04:00"},
        "location": "https://us04web.zoom.us/j/548158349",
    }
    out = format_events([event])
    assert "zoom.us" not in out and "@" not in out
    assert "Power Yoga" in out


def test_format_events_empty_is_explicit() -> None:
    assert format_events([]) == "No events."


def test_format_events_missing_title_is_labeled() -> None:
    out = format_events([{"start": {"dateTime": "2026-06-28T12:00:00-04:00"}}])
    assert "(no title)" in out
