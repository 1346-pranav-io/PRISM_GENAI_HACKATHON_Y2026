"""Structured plan produced by LLM providers.

This model is the canonical definition of ``LLMPlan``. It was previously
defined inline in ``interfaces/llm_provider.py``; the import there is
kept as a re-export for backward compatibility.
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from .tools import ToolCallRequest

class LLMPlan(BaseModel):
    """Structured proposal produced by an LLM provider.

    The runtime validates every field before acting on this plan.
    The provider never executes tools; the runtime handles validation
   , origin_state_version assignment, and tool execution.
    """
    intent: Optional[str] = None
    extracted_slots: Dict[str, Any] = Field(default_factory=dict)
    proposed_tool_calls: List[ToolCallRequest] = Field(default_factory=list)
    assistant_response: Optional[str] = None
