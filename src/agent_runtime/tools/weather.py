"""Deterministic weather lookup tool.

Uses an in-memory dataset for demonstration. In production, replace
``_fetch_weather`` with a live weather API call.
"""
import asyncio
from typing import Any, Dict, List, Optional
from ..models.tools import ToolCategory, ToolManifest

# Deterministic mock weather data
_WEATHER_DB: Dict[str, Dict[str, Any]] = {
    "london":    {"city": "London",    "temp_c": 14, "condition": "Overcast",    "humidity": 78, "wind_kmh": 18},
    "new york":  {"city": "New York",  "temp_c": 22, "condition": "Partly Cloudy", "humidity": 65, "wind_kmh": 12},
    "mumbai":    {"city": "Mumbai",    "temp_c": 31, "condition": "Humid",        "humidity": 82, "wind_kmh": 8},
    "tokyo":     {"city": "Tokyo",     "temp_c": 19, "condition": "Clear",         "humidity": 55, "wind_kmh": 10},
    "paris":     {"city": "Paris",     "temp_c": 16, "condition": "Light Rain",    "humidity": 85, "wind_kmh": 14},
    "dubai":     {"city": "Dubai",     "temp_c": 38, "condition": "Sunny",         "humidity": 40, "wind_kmh": 15},
    "singapore": {"city": "Singapore", "temp_c": 32, "condition": "Thunderstorm",  "humidity": 90, "wind_kmh": 20},
}

GET_WEATHER_TOOL = ToolManifest(
    name="get_weather",
    description="Get current weather for a city",
    category=ToolCategory.READ_ONLY,
    parameters_schema={"type": "object", "properties": {
        "city": {"type": "string", "description": "City name (e.g. London)"},
    },"required": ["city"]},
    supports_cancellation=True,
    timeout_seconds=10.0,
)

async def get_weather_executor():
    async def _weather(city: str = "") -> Dict[str, Any]:
        await asyncio.sleep(0.04)
        key = city.strip().lower()
        if key in _WEATHER_DB:
            return dict(_WEATHER_DB[key])
        return {"city": city, "temp_c": 20, "condition": "Unknown", "humidity": 50, "wind_kmh": 0, "note": "Data not available for this city"}
    return _weather
