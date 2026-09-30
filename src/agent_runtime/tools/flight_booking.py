"""Deterministic flight search and booking tools.

These tools expose READ_ONLY (search) and STATE_MODIFYING (book) operations
through ToolRegistry / ToolExecutor. They do NOT directly mutate SessionState;
the runtime's StateManager owns all state changes.
"""
import asyncio
from typing import Any, Dict, List, Optional
from ..models.tools import ToolCategory, ToolManifest

# ------------------------------------------------------------------
# In-memory flight data (deterministic; safe for tests and demos)
# ------------------------------------------------------------------
_FLIGHTS: List[Dict[str, Any]] = [
    {"id": "AI101", "from": "New York", "to": "London", "price": 450, "airline": "AirInter", "departure": "2026-10-15T08:00"},
    {"id": "BA205", "from": "New York", "to": "London", "price": 520, "airline": "BritAir", "departure": "2026-10-15T14:30"},
    {"id": "UA801", "from": "New York", "to": "London", "price": 490, "airline": "United", "departure": "2026-10-15T19:00"},
    {"id": "AI201", "from": "London", "to": "Mumbai", "price": 620, "airline": "AirInter", "departure": "2026-10-16T06:00"},
    {"id": "EK501", "from": "Dubai", "to": "Singapore", "price": 380, "airline": "Emirates", "departure": "2026-10-17T22:00"},
    {"id": "JL007", "from": "Tokyo", "to": "Sydney", "price": 710, "airline": "JapanAir", "departure": "2026-10-18T10:00"},
    {"id": "AI131", "from": "Delhi", "to": "Mumbai", "price": 95, "airline": "AirInter", "departure": "2026-10-15T07:30"},
    {"id": "UA830", "from": "London", "to": "New York", "price": 510, "airline": "United", "departure": "2026-10-16T09:15"},
    {"id": "AI144", "from": "Mumbai", "to": "New York", "price": 880, "airline": "AirInter", "departure": "2026-10-17T01:40"},
    {"id": "AI865", "from": "Mumbai", "to": "Delhi", "price": 90, "airline": "AirInter", "departure": "2026-10-15T18:05"},
    {"id": "BA143", "from": "London", "to": "Delhi", "price": 640, "airline": "BritAir", "departure": "2026-10-16T21:10"},
    {"id": "JL044", "from": "Delhi", "to": "Tokyo", "price": 560, "airline": "JapanAir", "departure": "2026-10-18T20:50"},
    {"id": "AF218", "from": "Mumbai", "to": "Paris", "price": 610, "airline": "AirFrance", "departure": "2026-10-19T02:25"},
]
_BOOKINGS: Dict[str, Dict[str, Any]] = {}
_BOOKING_COUNTER = [0]

# ------------------------------------------------------------------
# Tool manifests
# ------------------------------------------------------------------
SEARCH_FLIGHTS_TOOL = ToolManifest(
    name="search_flights",
    description="Search available flights by origin/destination/date",
    category=ToolCategory.READ_ONLY,
    parameters_schema={"type": "object", "properties": {
        "origin": {"type": "string", "description": "Origin city (e.g. New York)"},
        "destination": {"type": "string", "description": "Destination city (e.g. London)"},
        "date": {"type": "string", "description": "Departure date YYYY-MM-DD (optional)"},
    },"required": []},
    supports_cancellation=True,
    timeout_seconds=15.0,
)

BOOK_FLIGHT_TOOL = ToolManifest(
    name="book_flight",
    description="Book a flight by flight ID and passenger name",
    category=ToolCategory.STATE_MODIFYING,
    parameters_schema={"type": "object", "properties": {
        "flight_id": {"type": "string", "description": "Flight ID (e.g. AI101)"},
        "passenger_name": {"type": "string", "description": "Passenger full name"},
        "passenger_email": {"type": "string", "description": "Passenger email"},
    },"required": ["flight_id", "passenger_name"]},
    supports_cancellation=True,
    timeout_seconds=10.0,
    idempotency_required=True,
)

# ------------------------------------------------------------------
# Executors (async, cancellation-safe)
# ------------------------------------------------------------------
async def get_search_flights_executor():
    """Returns a fresh async function so each call gets its own coroutine scope."""
    async def _search(origin: str = "", destination: str = "", date: str = "") -> List[Dict[str, Any]]:
        await asyncio.sleep(0.05)  # Simulate API latency
        q_origin = origin.strip().lower()
        q_dest = destination.strip().lower()
        results = []
        for f in _FLIGHTS:
            origin_ok = not q_origin or q_origin in f["from"].lower()
            dest_ok = not q_dest or q_dest in f["to"].lower()
            if origin_ok and dest_ok:
                results.append(dict(f))
        return results
    return _search

async def get_book_flight_executor():
    async def _book(flight_id: str = "", passenger_name: str = "", passenger_email: str = "") -> Dict[str, Any]:
        await asyncio.sleep(0.05)
        flight = next((f for f in _FLIGHTS if f["id"] == flight_id), None)
        if not flight:
            raise ValueError(f"Flight {flight_id} not found")
        _BOOKING_COUNTER[0] += 1
        booking_ref = f"BK{_BOOKING_COUNTER[0]:05d}"
        booking = {
            "booking_ref": booking_ref,
            "flight_id": flight_id,
            "passenger_name": passenger_name,
            "passenger_email": passenger_email,
            "route": f"{flight['from']} -> {flight['to']}",
            "price": flight["price"],
            "departure": flight["departure"],
            "status": "CONFIRMED",
        }
        _BOOKINGS[booking_ref] = booking
        return booking
    return _book
