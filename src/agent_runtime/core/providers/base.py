"""Base LLM provider abstraction providing shared functionality for all provider adapters."""

import re
from abc import ABC
from typing import Any, Dict, Iterable, List, Optional

from ...interfaces.llm_provider import LLMPlan
from ...models.state import SessionState
from ...models.tools import ToolManifest

# Capitalised place names, e.g. "flights from New York to Tokyo", "weather in Paris".
_PLACE = r"([A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)*)"

# Route slots the heuristic planners extract from free text.
SLOT_PATTERNS = {
    "destination": re.compile(r"\bto\s+" + _PLACE),
    "origin": re.compile(r"\bfrom\s+" + _PLACE),
}

# How to fill a declared tool parameter from free text when no slot supplies it.
_PARAMETER_PATTERNS = {
    **SLOT_PATTERNS,
    "city": re.compile(r"\b(?:in|for|at)\s+" + _PLACE),
}

# A parameter may be filled from a differently named slot (weather "city" <- trip "destination").
_PARAMETER_SLOT_FALLBACKS = {"city": ("destination",)}


def extract_route_slots(user_input: str) -> Dict[str, str]:
    """Route slots stated in the text, e.g. {"destination": "Tokyo", "origin": "Seattle"}."""
    slots: Dict[str, str] = {}
    for key, pattern in SLOT_PATTERNS.items():
        m = pattern.search(user_input)
        if m:
            slots[key] = m.group(1).strip()
    return slots


def find_tool(available_tools: Iterable[ToolManifest], name: str) -> Optional[ToolManifest]:
    return next((t for t in available_tools if t.name == name), None)


def build_tool_arguments(
    manifest: Optional[ToolManifest],
    user_input: str,
    known_slots: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build arguments for a tool from its declared parameters_schema.

    Each declared property is filled from a same-named slot, then from the text
    itself, then from a mapped slot; undeclared keys are never sent. A tool that
    declares no properties receives the raw request as {"query": user_input}.
    """
    properties = (manifest.parameters_schema or {}).get("properties") if manifest else None
    if not properties:
        return {"query": user_input}
    args: Dict[str, Any] = {}
    for prop in properties:
        if known_slots.get(prop) is not None:
            args[prop] = known_slots[prop]
            continue
        pattern = _PARAMETER_PATTERNS.get(prop)
        m = pattern.search(user_input) if pattern else None
        if m:
            args[prop] = m.group(1).strip()
            continue
        fallback = next(
            (known_slots[s] for s in _PARAMETER_SLOT_FALLBACKS.get(prop, ()) if known_slots.get(s) is not None),
            None,
        )
        if fallback is not None:
            args[prop] = fallback
    return args


def heuristic_known_slots(session_state: SessionState, user_input: str) -> Dict[str, Any]:
    """Current slot values overlaid with any route slots stated in this request."""
    known: Dict[str, Any] = {k: v.value for k, v in session_state.slots.items()}
    known.update(extract_route_slots(user_input))
    return known


def prior_turns(conversation_history: List[Dict[str, str]], user_input: str) -> List[Dict[str, str]]:
    """History excluding the current user turn, which the runtime has already appended."""
    if conversation_history:
        last = conversation_history[-1]
        if last.get("role") == "user" and last.get("content") == user_input:
            return conversation_history[:-1]
    return conversation_history


class BaseLLMProvider(ABC):
    """
    Shared base class for LLM provider adapters.

    Encapsulates common functionality used across multiple provider implementations:
    - Tool manifest conversion to provider-specific function declaration formats
    - Session state / conversation history assembly into prompt context
    - Fallback heuristics when API calls are unavailable

    Subclasses must implement the `ILLMProvider.plan_and_reason` contract and may
    override `_build_system_prompt` or `_convert_tools_to_declarations` when a
    provider requires a custom format.
    """

    def _build_system_prompt(self) -> str:
        """Override to customise the system prompt injected before every user turn."""
        return (
            "You are a helpful real-time assistant. When the user asks you to do "
            "something that requires calling a tool, you may propose tool calls. "
            "Always be concise and respond to the user's intent."
        )

    def _convert_tools_to_declarations(
        self,
        available_tools: List[ToolManifest],
    ) -> List[Dict[str, Any]]:
        """
        Convert internal ToolManifest list into a provider-agnostic function-declaration
        format suitable for passing to `_format_tools_for_api`.

        The default implementation returns a list of dicts with ``name``,
        ``description``, and ``parameters`` keys. Subclasses that require a different
        schema (e.g. OpenAI's ``functions`` / ``tools`` format) should override this
        method.
        """
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters_schema,
            }
            for tool in available_tools
        ]

    def _format_tools_for_api(
        self,
        available_tools: List[ToolManifest],
    ) -> Any:
        """
        Format the converted tool declarations for the specific API call.

        The default implementation returns the raw list from
        `_convert_tools_to_declarations`. Subclasses (OpenAI, Gemini, etc.) should
        override this to wrap the declarations in the format required by their API.
        """
        return self._convert_tools_to_declarations(available_tools)

    def _build_context_message(
        self,
        session_state: SessionState,
        conversation_history: List[Dict[str, str]],
    ) -> str:
        """Build a system-level context snippet describing the current session state."""
        slot_lines = [
            f"  {key}: {sv.value} (confidence={sv.confidence}, version={sv.source_state_version})"
            for key, sv in session_state.slots.items()
        ]
        slots_text = "\n".join(slot_lines) if slot_lines else "  (none)"
        history_text = "\n".join(
            f"{turn['role']}: {turn['content']}"
            for turn in conversation_history[-10:]
        ) or "(empty)"

        return (
            f"Current session state:\n"
            f"  state_version: {session_state.state_version}\n"
            f"  status: {session_state.status.value}\n"
            f"  slots:\n{slots_text}\n\n"
            f"Recent conversation (up to 10 turns):\n{history_text}\n"
        )