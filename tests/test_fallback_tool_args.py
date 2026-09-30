"""Heuristic fallback paths must build tool arguments from each tool's declared schema."""

import asyncio
from datetime import datetime, timezone

import pytest

from src.agent_runtime.core.classifier import FastInterruptionClassifier
from src.agent_runtime.core.event_bus import EventBus
from src.agent_runtime.core.gemini_live import GeminiLiveProvider
from src.agent_runtime.core.providers.openai_llm import OpenAILLMProvider
from src.agent_runtime.core.runtime_engine import AgentRuntimeEngine
from src.agent_runtime.core.state_manager import StateManager
from src.agent_runtime.core.task_manager import TaskManager
from src.agent_runtime.core.tool_executor import ToolExecutor
from src.agent_runtime.core.tool_registry import ToolRegistry
from src.agent_runtime.core.trace_logger import TraceLogger
from src.agent_runtime.models.events import EventType, RuntimeEvent
from src.agent_runtime.models.state import SessionState, SlotValue
from src.agent_runtime.models.tasks import TaskStatus, TaskType
from src.agent_runtime.models.tools import ToolCategory, ToolManifest
from src.agent_runtime.tools import (
    GET_WEATHER_TOOL, SEARCH_FLIGHTS_TOOL, get_search_flights_executor, get_weather_executor,
)

DOMAIN_TOOLS = [SEARCH_FLIGHTS_TOOL, GET_WEATHER_TOOL]


@pytest.fixture(autouse=True)
def no_api_keys(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def _providers():
    return [OpenAILLMProvider(api_key=None), GeminiLiveProvider(api_key=None)]


def _state(**slots):
    now = datetime.now(timezone.utc)
    return SessionState(
        session_id="fb",
        state_version=1 + len(slots),
        slots={k: SlotValue(key=k, value=v, source_state_version=2, updated_at=now) for k, v in slots.items()},
    )


async def _plan(provider, text, state=None, tools=DOMAIN_TOOLS):
    return await provider.plan_and_reason(
        session_state=state or _state(), conversation_history=[{"role": "user", "content": text}],
        available_tools=tools, user_input=text,
    )


def _declared(manifest):
    return set(manifest.parameters_schema["properties"])


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", _providers(), ids=lambda p: type(p).__name__)
async def test_flight_fallback_uses_flight_schema(provider):
    plan = await _plan(provider, "Find me flights from Seattle to Tokyo")
    [call] = plan.proposed_tool_calls
    assert call.tool_name == "search_flights"
    assert call.arguments == {"origin": "Seattle", "destination": "Tokyo"}
    assert set(call.arguments) <= _declared(SEARCH_FLIGHTS_TOOL)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", _providers(), ids=lambda p: type(p).__name__)
async def test_flight_fallback_uses_known_slots(provider):
    plan = await _plan(provider, "search flights please", state=_state(destination="Mumbai"))
    assert plan.proposed_tool_calls[0].arguments == {"destination": "Mumbai"}


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", _providers(), ids=lambda p: type(p).__name__)
async def test_weather_fallback_uses_weather_schema(provider):
    plan = await _plan(provider, "What's the weather in Paris")
    [call] = plan.proposed_tool_calls
    assert call.tool_name == "get_weather"
    assert call.arguments == {"city": "Paris"}
    assert set(call.arguments) <= _declared(GET_WEATHER_TOOL)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", _providers(), ids=lambda p: type(p).__name__)
async def test_weather_city_falls_back_to_destination_slot(provider):
    plan = await _plan(provider, "how is the weather there", state=_state(destination="Tokyo"))
    assert plan.proposed_tool_calls[0].arguments == {"city": "Tokyo"}


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", _providers(), ids=lambda p: type(p).__name__)
async def test_weather_city_in_text_beats_destination_slot(provider):
    plan = await _plan(provider, "weather in London", state=_state(destination="Tokyo"))
    assert plan.proposed_tool_calls[0].arguments == {"city": "London"}


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", _providers(), ids=lambda p: type(p).__name__)
async def test_schemaless_tool_keeps_raw_query(provider):
    schemaless = ToolManifest(name="search_flights", description="d", category=ToolCategory.READ_ONLY, parameters_schema={"type": "object"})
    plan = await _plan(provider, "search flights to Tokyo", tools=[schemaless])
    assert plan.proposed_tool_calls[0].arguments == {"query": "search flights to Tokyo"}


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", _providers(), ids=lambda p: type(p).__name__)
@pytest.mark.parametrize("text, factory", [
    ("Find me flights from Seattle to Tokyo", get_search_flights_executor),
    ("What's the weather in Paris", get_weather_executor),
])
async def test_fallback_arguments_are_accepted_by_real_executors(provider, text, factory):
    [call] = (await _plan(provider, text)).proposed_tool_calls
    executor = await factory()
    await executor(**call.arguments)  # previously TypeError: unexpected keyword 'query'


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", _providers(), ids=lambda p: type(p).__name__)
@pytest.mark.parametrize("text, tool_name", [
    ("Find me flights from Seattle to Tokyo", "search_flights"),
    ("What's the weather in Paris", "get_weather"),
])
async def test_fallback_tool_tasks_complete_through_engine(provider, text, tool_name):
    bus, reg, tm = EventBus(), ToolRegistry(), TaskManager()
    reg.register_tool(SEARCH_FLIGHTS_TOOL, await get_search_flights_executor())
    reg.register_tool(GET_WEATHER_TOOL, await get_weather_executor())
    engine = AgentRuntimeEngine(
        event_bus=bus, state_manager=StateManager(), task_manager=tm,
        classifier=FastInterruptionClassifier(), tool_registry=reg,
        tool_executor=ToolExecutor(reg), llm_provider=provider, trace_logger=TraceLogger(),
    )
    await engine.init_session("fb_engine")
    await bus.publish(RuntimeEvent(session_id="fb_engine", event_type=EventType.USER_TEXT, state_version=1, payload={"text": text}))
    await asyncio.sleep(0.2)
    [task] = [t for t in await tm.get_session_tasks("fb_engine") if t.task_type == TaskType.TOOL_EXECUTION]
    assert task.tool_name == tool_name
    assert task.status == TaskStatus.COMPLETED, task.error
