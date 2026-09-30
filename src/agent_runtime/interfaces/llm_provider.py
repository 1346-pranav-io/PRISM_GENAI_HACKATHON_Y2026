"""LLM Provider abstract interface."""
import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List
from ..models.state import SessionState
from ..models.tools import ToolCallRequest, ToolManifest
# Re-export LLMPlan from the canonical models location for backward compatibility
from ..models.llm_plan import LLMPlan

_MAX_RESULT_CHARS = 500


def _format_result(data: Any) -> str:
    try:
        text = json.dumps(data, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(data)
    return text if len(text) <= _MAX_RESULT_CHARS else text[:_MAX_RESULT_CHARS] + "..."


def compose_tool_response(assistant_response: str | None, tool_results: List[Dict[str, Any]]) -> str:
    """Deterministic synthesis: the plan's own text followed by one line per tool outcome."""
    lines = [assistant_response or "Here is what I found."]
    for r in tool_results:
        name, status = r["tool_name"], r["status"]
        if status == "COMPLETED":
            lines.append(f"{name}: {_format_result(r.get('data'))}")
        elif status == "CANCELLED":
            lines.append(f"{name} was cancelled.")
        else:
            lines.append(f"{name} failed: {r.get('error') or 'unknown error'}")
    return "\n".join(lines)


class ILLMProvider(ABC):
    @abstractmethod
    async def plan_and_reason(
        self,
        session_state: SessionState,
        conversation_history: List[dict],
        available_tools: List[ToolManifest],
        user_input: str,
    ) -> LLMPlan:
        """Produce structured plan proposing slot deltas, tool calls, and text response."""
        pass

    async def synthesize_response(
        self,
        session_state: SessionState,
        conversation_history: List[dict],
        user_input: str,
        plan: LLMPlan,
        tool_results: List[Dict[str, Any]],
    ) -> str:
        """
        Produce the final reply once the plan's tool calls have finished.

        tool_results contains only current-version outcomes (stale results are
        filtered out by the runtime); each entry has task_id, tool_name, status
        (COMPLETED / FAILED / CANCELLED), data and error. Providers may override
        this to synthesize with a model; the default is deterministic.
        """
        return compose_tool_response(plan.assistant_response, tool_results)
