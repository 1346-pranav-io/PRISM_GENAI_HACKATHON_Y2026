"""OpenAI-compatible LLM provider adapter using /v1/chat/completions."""
import asyncio
import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional
from ...interfaces.llm_provider import ILLMProvider
from ...models.llm_plan import LLMPlan
from ...models.state import SessionState
from ...models.tools import ToolCallRequest, ToolManifest
from .base import build_tool_arguments, find_tool, heuristic_known_slots, prior_turns
logger = logging.getLogger(__name__)

def _manifest_to_openai_tool(tool: ToolManifest) -> Dict[str, Any]:
    return {"type": "function", "function": {"name": tool.name, "description": tool.description, "parameters": tool.parameters_schema}}

def _new_call_id() -> str:
    return f"call_openai_{uuid.uuid4().hex[:12]}"

def _parse_tool_call(raw_call: Dict[str, Any], origin_state_version: int) -> ToolCallRequest:
    fn = raw_call.get("function", {})
    arg_str = fn.get("arguments", "{}")
    try:
        arguments = json.loads(arg_str)
    except Exception:
        arguments = {"_raw": arg_str}
    return ToolCallRequest(
        call_id=raw_call.get("id") or _new_call_id(),
        tool_name=fn.get("name", "unknown"),
        arguments=arguments,
        origin_state_version=origin_state_version,
    )

class OpenAILLMProvider(ILLMProvider):
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "gpt-4o",
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model_name = model_name
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.timeout = timeout
        self._client: Optional[Any] = None

    def _get_client(self) -> Any:
        if self._client is None:
            import openai
            self._client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)
        return self._client

    def _build_system_prompt(self) -> str:
        return ("You are a helpful real-time assistant. When the user asks you to do something that "
                "requires calling a tool, you may propose tool calls. Always be concise.")

    def _build_context_message(self, session_state: SessionState) -> str:
        # Conversation turns are sent as chat messages, so only session state goes here.
        lines = [f"state_version: {session_state.state_version}", f"status: {session_state.status.value}", f"slots: {dict(session_state.slots)}"]
        return "Current session state:\n" + "\n".join(lines)

    def _build_messages(self, session_state: SessionState, conversation_history: List[Dict[str, str]], user_input: str) -> List[Dict[str, str]]:
        messages = [{"role": "system", "content": self._build_system_prompt()}, {"role": "system", "content": self._build_context_message(session_state)}]
        for turn in prior_turns(conversation_history, user_input)[-20:]:
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": user_input})
        return messages

    def _parse_response(self, data: Dict[str, Any], origin_state_version: int) -> LLMPlan:
        choices = data.get("choices", [])
        if not choices:
            return LLMPlan(intent="user_request", extracted_slots={}, proposed_tool_calls=[], assistant_response="(No response)")
        message = choices[0].get("message", {})
        tool_calls = [_parse_tool_call(raw, origin_state_version) for raw in message.get("tool_calls") or []]
        return LLMPlan(intent="tool_use" if tool_calls else "user_request", extracted_slots={}, proposed_tool_calls=tool_calls, assistant_response=message.get("content") or None)

    def _convert_tools_to_declarations(self, available_tools: List[ToolManifest]) -> List[Dict[str, Any]]:
        return [_manifest_to_openai_tool(m) for m in available_tools]

    def _heuristic_fallback(
        self,
        session_state: SessionState,
        user_input: str,
        available_tools: Optional[List[ToolManifest]] = None,
    ) -> LLMPlan:
        norm = user_input.strip().lower()
        tools = available_tools or []
        known = heuristic_known_slots(session_state, user_input)
        tool_calls: List[ToolCallRequest] = []
        resp = f"I have processed: {user_input}"
        v = session_state.state_version
        if "flight" in norm or "search" in norm:
            args = build_tool_arguments(find_tool(tools, "search_flights"), user_input, known)
            tool_calls.append(ToolCallRequest(call_id=_new_call_id(), tool_name="search_flights", arguments=args, origin_state_version=v))
            resp = "Checking flight schedules now..."
        elif "weather" in norm:
            args = build_tool_arguments(find_tool(tools, "get_weather"), user_input, known)
            tool_calls.append(ToolCallRequest(call_id=_new_call_id(), tool_name="get_weather", arguments=args, origin_state_version=v))
            resp = "Looking up the weather for you..."
        return LLMPlan(intent="user_request", extracted_slots={}, proposed_tool_calls=tool_calls, assistant_response=resp)

    async def plan_and_reason(
        self,
        session_state: SessionState,
        conversation_history: List[Dict[str, str]],
        available_tools: List[ToolManifest],
        user_input: str,
    ) -> LLMPlan:
        if not self.api_key:
            logger.info("OPENAI_API_KEY not configured -- using heuristic fallback.")
            return self._heuristic_fallback(session_state, user_input, available_tools)
        try:
            return await self._call_openai(session_state, conversation_history, available_tools, user_input)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("OpenAI API call failed (%s) -- using heuristic fallback.", exc)
            return self._heuristic_fallback(session_state, user_input, available_tools)

    async def _call_openai(self, session_state: SessionState, conversation_history: List[Dict[str, str]], available_tools: List[ToolManifest], user_input: str) -> LLMPlan:
        import openai
        client = self._get_client()
        messages = self._build_messages(session_state, conversation_history, user_input)
        api_kwargs: Dict[str, Any] = {"model": self.model_name, "messages": messages}
        if available_tools:
            api_kwargs["tools"] = self._convert_tools_to_declarations(available_tools)
            api_kwargs["tool_choice"] = "auto"
        response = await asyncio.to_thread(client.chat.completions.create, **api_kwargs)
        data = response.model_dump() if hasattr(response, "model_dump") else response
        return self._parse_response(data, session_state.state_version)
