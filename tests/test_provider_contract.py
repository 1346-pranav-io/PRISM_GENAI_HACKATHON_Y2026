"""Provider contract tests: every provider must accept the exact call the runtime makes."""

import asyncio
import inspect
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.agent_runtime.core.classifier import FastInterruptionClassifier
from src.agent_runtime.core.event_bus import EventBus
from src.agent_runtime.core.gemini_live import GeminiLiveProvider
from src.agent_runtime.core.mock_llm import MockLLMProvider
from src.agent_runtime.core.providers.openai_llm import OpenAILLMProvider
from src.agent_runtime.core.runtime_engine import AgentRuntimeEngine
from src.agent_runtime.core.state_manager import StateManager
from src.agent_runtime.core.task_manager import TaskManager
from src.agent_runtime.core.tool_executor import ToolExecutor
from src.agent_runtime.core.tool_registry import ToolRegistry
from src.agent_runtime.core.trace_logger import TraceLogger
from src.agent_runtime.models.events import EventType, RuntimeEvent
from src.agent_runtime.models.llm_plan import LLMPlan
from src.agent_runtime.models.state import SessionState
from src.agent_runtime.models.tools import ToolCategory, ToolManifest

# The exact keyword arguments AgentRuntimeEngine._execute_deliberate_path passes.
ENGINE_KWARGS = ("session_state", "conversation_history", "available_tools", "user_input")


@pytest.fixture(autouse=True)
def no_api_keys(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def _providers():
    return [MockLLMProvider(), OpenAILLMProvider(api_key=None), GeminiLiveProvider(api_key=None)]


def _state(version=1):
    now = datetime.now(timezone.utc)
    return SessionState(session_id="contract", state_version=version, created_at=now, updated_at=now)


def _tools():
    return [ToolManifest(name="search_flights", description="d", category=ToolCategory.READ_ONLY, parameters_schema={})]


@pytest.mark.parametrize("provider", _providers(), ids=lambda p: type(p).__name__)
def test_signature_accepts_engine_keywords(provider):
    sig = inspect.signature(provider.plan_and_reason)
    sig.bind(**{k: None for k in ENGINE_KWARGS})


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", _providers(), ids=lambda p: type(p).__name__)
async def test_call_with_engine_keywords_returns_plan(provider):
    plan = await provider.plan_and_reason(
        session_state=_state(),
        conversation_history=[{"role": "user", "content": "search flights"}],
        available_tools=_tools(),
        user_input="search flights to Tokyo",
    )
    assert isinstance(plan, LLMPlan)
    assert plan.proposed_tool_calls, "heuristic path should propose search_flights"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", _providers(), ids=lambda p: type(p).__name__)
async def test_provider_works_through_engine(provider):
    bus = EventBus()
    reg = ToolRegistry()
    engine = AgentRuntimeEngine(
        event_bus=bus, state_manager=StateManager(), task_manager=TaskManager(),
        classifier=FastInterruptionClassifier(), tool_registry=reg,
        tool_executor=ToolExecutor(reg), llm_provider=provider, trace_logger=TraceLogger(),
    )
    events = []

    async def collect(evt):
        events.append(evt)

    bus.subscribe_all(collect)
    await engine.init_session("contract_engine")
    await bus.publish(RuntimeEvent(
        session_id="contract_engine", event_type=EventType.USER_TEXT,
        state_version=1, payload={"text": "hello"},
    ))
    await asyncio.sleep(0.1)
    types = [e.event_type for e in events]
    assert EventType.SYSTEM_ERROR not in types, [e.payload for e in events if e.event_type == EventType.SYSTEM_ERROR]
    assert EventType.AGENT_FINAL_RESPONSE in types


# ---------------------------------------------------------------------------
# Unique call IDs
# ---------------------------------------------------------------------------


def test_openai_multiple_tool_calls_have_unique_ids():
    data = {"choices": [{"message": {"content": None, "tool_calls": [
        {"type": "function", "function": {"name": "search_flights", "arguments": "{}"}},
        {"type": "function", "function": {"name": "get_weather", "arguments": "{}"}},
    ]}}]}
    plan = OpenAILLMProvider(api_key=None)._parse_response(data, origin_state_version=1)
    ids = [c.call_id for c in plan.proposed_tool_calls]
    assert len(ids) == 2 and len(set(ids)) == 2


def test_openai_preserves_api_supplied_call_ids():
    data = {"choices": [{"message": {"content": None, "tool_calls": [
        {"id": "call_abc", "type": "function", "function": {"name": "a", "arguments": "{}"}},
        {"id": "call_def", "type": "function", "function": {"name": "b", "arguments": "{}"}},
    ]}}]}
    plan = OpenAILLMProvider(api_key=None)._parse_response(data, origin_state_version=1)
    assert [c.call_id for c in plan.proposed_tool_calls] == ["call_abc", "call_def"]


def test_gemini_multiple_tool_calls_have_unique_ids():
    parts = [
        SimpleNamespace(text=None, function_call=SimpleNamespace(name="search_flights", args={}, id=None)),
        SimpleNamespace(text=None, function_call=SimpleNamespace(name="get_weather", args={}, id=None)),
    ]
    resp = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=parts))])
    plan = GeminiLiveProvider(api_key=None)._parse_response(resp, 1)
    ids = [c.call_id for c in plan.proposed_tool_calls]
    assert len(ids) == 2 and len(set(ids)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", _providers(), ids=lambda p: type(p).__name__)
async def test_call_ids_unique_across_turns_at_same_version(provider):
    ids = set()
    for _ in range(3):
        plan = await provider.plan_and_reason(
            session_state=_state(version=5), conversation_history=[],
            available_tools=_tools(), user_input="search flights",
        )
        ids.update(c.call_id for c in plan.proposed_tool_calls)
    assert len(ids) == 3
