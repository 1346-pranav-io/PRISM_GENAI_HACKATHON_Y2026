"""Gemini Live / Multimodal LLM Provider using modern google.genai Client API."""
import asyncio
import logging
import os
import uuid
from typing import Any, Dict, List, Optional
from ..interfaces.llm_provider import ILLMProvider
from ..models.llm_plan import LLMPlan
from ..models.state import SessionState
from ..models.tools import ToolCallRequest, ToolManifest
from .providers.base import build_tool_arguments, find_tool, heuristic_known_slots, prior_turns
logger = logging.getLogger(__name__)

def _manifest_to_func(tool: ToolManifest) -> Dict[str, Any]:
    return {"name": tool.name, "description": tool.description, "parameters": tool.parameters_schema}

def _new_call_id() -> str:
    return f"call_gemini_{uuid.uuid4().hex[:12]}"

async def _gen_async(client, model, contents, config):
    return await asyncio.to_thread(client.models.generate_content, model=model, contents=contents, config=config)

class GeminiLiveProvider(ILLMProvider):
    def __init__(self, api_key: Optional[str] = None, model_name: str = "gemini-2.0-flash"):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.model_name = model_name
        self._client: Optional[Any] = None
    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai as _g
            self._client = _g.Client(api_key=self.api_key)
        return self._client
    def _build_contents(self, ss: SessionState, hist: List[Dict], user: str) -> List[Dict]:
        lines = [f"Current session state: state_version={ss.state_version} status={ss.status.value} slots={dict(ss.slots)}"]
        lines += [f"{t['role']}: {t['content']}" for t in prior_turns(hist, user)[-20:]]
        lines.append(f"user: {user}")
        ctx = "\n".join(lines)
        return [{"role": "user", "parts": [{"text": ctx}]}]
    async def plan_and_reason(
        self,
        session_state: SessionState,
        conversation_history: List[Dict],
        available_tools: List[ToolManifest],
        user_input: str,
    ) -> LLMPlan:
        if not self.api_key:
            return self._heuristic_fallback(session_state, user_input, available_tools)
        try:
            return await self._call_gemini(session_state, conversation_history, available_tools, user_input)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Gemini API failed (%s), falling back to heuristic.", exc)
            return self._heuristic_fallback(session_state, user_input, available_tools)
    async def _call_gemini(self, ss: SessionState, hist: List[Dict], tools: List[ToolManifest], user: str) -> LLMPlan:
        from google.genai import types as t
        cli = self._get_client()
        cfg = None
        if tools:
            decls = [_manifest_to_func(tm) for tm in tools]
            cfg = t.GenerateContentConfig(tools=[t.Tool(function_declarations=decls)])
        resp = await _gen_async(cli, self.model_name, self._build_contents(ss, hist, user), cfg)
        return self._parse_response(resp, ss.state_version)
    def _parse_response(self, resp: Any, ver: int) -> LLMPlan:
        cands = getattr(resp, "candidates", []) or []
        if not cands:
            return LLMPlan(intent="user_request", extracted_slots={}, proposed_tool_calls=[], assistant_response="(No response)")
        parts = (cands[0].content.parts if cands[0].content else [])
        texts = [p.text for p in parts if hasattr(p, "text") and p.text]
        fcs = [p.function_call for p in parts if hasattr(p, "function_call") and p.function_call]
        calls = []
        for fc in fcs:
            args = getattr(fc, "args", {}) or {}
            if not isinstance(args, dict): args = {"_raw": str(args)}
            calls.append(ToolCallRequest(call_id=getattr(fc, "id", None) or _new_call_id(), tool_name=getattr(fc, "name", "unknown"), arguments=args, origin_state_version=ver))
        return LLMPlan(intent="tool_use" if calls else "user_request", extracted_slots={}, proposed_tool_calls=calls, assistant_response=" ".join(texts) or None)
    def _heuristic_fallback(self, ss: SessionState, user: str, available_tools: Optional[List[ToolManifest]] = None) -> LLMPlan:
        norm = user.strip().lower()
        tools = available_tools or []
        known = heuristic_known_slots(ss, user)
        calls: List[ToolCallRequest] = []
        resp = f"I have processed: {user}"
        v = ss.state_version
        if "flight" in norm or "search" in norm:
            calls.append(ToolCallRequest(call_id=_new_call_id(), tool_name="search_flights", arguments=build_tool_arguments(find_tool(tools, "search_flights"), user, known), origin_state_version=v))
            resp = "Checking flight schedules now..."
        elif "weather" in norm:
            calls.append(ToolCallRequest(call_id=_new_call_id(), tool_name="get_weather", arguments=build_tool_arguments(find_tool(tools, "get_weather"), user, known), origin_state_version=v))
            resp = "Looking up the weather for you..."
        return LLMPlan(intent="user_request", extracted_slots={}, proposed_tool_calls=calls, assistant_response=resp)
