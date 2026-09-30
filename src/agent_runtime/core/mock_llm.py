"""Mock LLM Provider for deterministic evaluation and testing."""

import asyncio
import uuid
from typing import Any, Dict, List, Optional, Tuple
from .classifier import FastInterruptionClassifier
from .providers.base import SLOT_PATTERNS, build_tool_arguments, extract_route_slots, find_tool, prior_turns
from ..interfaces.llm_provider import ILLMProvider
from ..models.llm_plan import LLMPlan
from ..models.state import SessionState
from ..models.tools import ToolCallRequest, ToolManifest


def _extract_route_slots(user_input: str, session_state: SessionState) -> Dict[str, Any]:
    """Propose slot deltas only for values that differ from the current state."""
    slots: Dict[str, Any] = {}
    for key, value in extract_route_slots(user_input).items():
        current = session_state.slots.get(key)
        if current is None or current.value != value:
            slots[key] = value
    return slots


def _correct_prior_request(
    user_input: str,
    conversation_history: List[Dict[str, str]],
) -> Optional[Tuple[str, str, str]]:
    """(prior request text, slot key, new value) if user_input corrects an earlier route request."""
    m = FastInterruptionClassifier.IMPLICIT_VALUE_EXPLICIT_VERB.search(user_input) or (
        FastInterruptionClassifier.IMPLICIT_VALUE_BARE.match(user_input)
    )
    if not m:
        return None
    value = m.group("value").strip()
    for turn in reversed(prior_turns(conversation_history, user_input)):
        if turn.get("role") != "user":
            continue
        for key, pattern in SLOT_PATTERNS.items():
            if pattern.search(turn.get("content", "")):
                return turn["content"], key, value
    return None


class MockLLMProvider(ILLMProvider):
    """Deterministic LLM Mock with configurable responses and artificial latency."""

    def __init__(self, latency_seconds: float = 0.0) -> None:
        self.latency_seconds = latency_seconds
        self._custom_responses: Dict[str, LLMPlan] = {}

    def set_response_for_query(self, query: str, plan: LLMPlan) -> None:
        self._custom_responses[query.strip().lower()] = plan

    async def plan_and_reason(
        self,
        session_state: SessionState,
        conversation_history: List[Dict[str, str]],
        available_tools: List[ToolManifest],
        user_input: str,
    ) -> LLMPlan:
        if self.latency_seconds > 0:
            await asyncio.sleep(self.latency_seconds)

        normalized = user_input.strip().lower()
        if normalized in self._custom_responses:
            return self._custom_responses[normalized]

        # Default heuristic parsing
        extracted_slots = _extract_route_slots(user_input, session_state)
        tool_calls: List[ToolCallRequest] = []
        response_text = f"Processed request: {user_input}"

        # Like a real LLM reading the conversation, resolve a slot-less correction
        # ("actually make it New York") against the user's previous request.
        request_text = normalized
        corrected = _correct_prior_request(user_input, conversation_history)
        if corrected and not extracted_slots:
            prior_text, key, value = corrected
            current = session_state.slots.get(key)
            if current is None or current.value != value:
                extracted_slots = {key: value}
            request_text = prior_text.lower()

        if "flight" in request_text or "search" in request_text:
            known = {k: v.value for k, v in session_state.slots.items()}
            known.update(extracted_slots)
            manifest = find_tool(available_tools, "search_flights")
            tool_calls.append(
                ToolCallRequest(
                    call_id=f"call_mock_{uuid.uuid4().hex[:8]}",
                    tool_name="search_flights",
                    arguments=build_tool_arguments(manifest, user_input, known),
                    origin_state_version=session_state.state_version,
                )
            )
            response_text = "Searching for flights matching your request..."

        return LLMPlan(
            intent="user_request",
            extracted_slots=extracted_slots,
            proposed_tool_calls=tool_calls,
            assistant_response=response_text,
        )
