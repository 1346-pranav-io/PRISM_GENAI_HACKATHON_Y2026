"""Deterministic calendar event management tools.

STATE_MODIFYING operations append events to an in-memory store.
The runtime's StateManager is NOT modified by these tools;
downstream reasoning decides whether to surface booking confirmation
in the assistant response.
"""
import asyncio, uuid
from datetime import datetime, timezone
from typing import Any, Dict, List
from ..models.tools import ToolCategory, ToolManifest

_EVENTS: List[Dict[str, Any]] = []

ADD_CALENDAR_EVENT_TOOL = ToolManifest(
    name="add_calendar_event",
    description="Add a calendar event",
    category=ToolCategory.STATE_MODIFYING,
    parameters_schema={"type": "object", "properties": {
        "title":       {"type": "string", "description": "Event title"},
        "start_time":  {"type": "string", "description": "Start time ISO-8601 (e.g. 2026-10-15T09:00:00Z)"},
        "end_time":    {"type": "string", "description": "End time ISO-8601 (e.g. 2026-10-15T10:00:00Z)"},
        "description": {"type": "string", "description": "Optional description"},
    },"required": ["title", "start_time", "end_time"]},
    supports_cancellation=True,
    timeout_seconds=10.0,
    idempotency_required=True,
)

GET_CALENDAR_EVENTS_TOOL = ToolManifest(
    name="get_calendar_events",
    description="List calendar events for a given date",
    category=ToolCategory.READ_ONLY,
    parameters_schema={"type": "object", "properties": {
        "date": {"type": "string", "description": "Date YYYY-MM-DD"},
    },"required": []},
    supports_cancellation=True,
    timeout_seconds=5.0,
)

async def get_add_event_executor():
    async def _add_event(title: str = "", start_time: str = "", end_time: str = "", description: str = "") -> Dict[str, Any]:
        await asyncio.sleep(0.04)
        event = {
            "event_id": str(uuid.uuid4())[:8],
            "title": title,
            "start_time": start_time,
            "end_time": end_time,
            "description": description,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _EVENTS.append(event)
        return event
    return _add_event

async def get_calendar_events_executor():
    async def _get_events(date: str = "") -> List[Dict[str, Any]]:
        await asyncio.sleep(0.03)
        if not date:
            return list(_EVENTS)
        return [e for e in _EVENTS if e["start_time"].startswith(date)]
    return _get_events
