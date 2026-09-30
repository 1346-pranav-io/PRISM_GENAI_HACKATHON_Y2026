"""Integration + provider verification tests (STEP 3-4)."""
import sys, asyncio, tempfile, pathlib
sys.path.insert(0, 'src')

from agent_runtime.core.mock_llm import MockLLMProvider
from agent_runtime.core.providers.openai_llm import OpenAILLMProvider, _manifest_to_openai_tool
from agent_runtime.core.gemini_live import GeminiLiveProvider
from agent_runtime.models.state import SessionState
from agent_runtime.models.llm_plan import LLMPlan
from agent_runtime.models.tools import ToolManifest
from agent_runtime.tools import SEARCH_FLIGHTS_TOOL

def test_providers():
    ss = SessionState(session_id='test', state_version=1)

    # P1: MockLLMProvider with custom response
    m = MockLLMProvider()
    m.set_response_for_query('hello', LLMPlan(intent='greet', extracted_slots={}, proposed_tool_calls=[], assistant_response='Hello!'))
    r = asyncio.run(m.plan_and_reason(ss, [], [], 'hello'))
    assert r.assistant_response == 'Hello!', f'Expected Hello!, got {r.assistant_response}'
    print('OK  P1: MockLLMProvider custom response works')

    # P2: MockLLMProvider heuristic fallback (flight keyword)
    m2 = MockLLMProvider()
    r2 = asyncio.run(m2.plan_and_reason(ss, [], [], 'show me flights to delhi'))
    assert len(r2.proposed_tool_calls) == 1, f'Expected 1, got {len(r2.proposed_tool_calls)}'
    assert r2.proposed_tool_calls[0].tool_name == 'search_flights'
    print(f'OK  P2: MockLLMProvider heuristic: {r2.proposed_tool_calls[0].tool_name}')

    # P3: OpenAILLMProvider fallback when no API key
    op = OpenAILLMProvider(api_key=None)
    result = asyncio.run(op.plan_and_reason(ss, [], [], 'weather in mumbai'))
    assert result.assistant_response is not None
    assert len(result.proposed_tool_calls) == 1
    assert result.proposed_tool_calls[0].tool_name == 'get_weather'
    print(f'OK  P3: OpenAILLMProvider fallback: {result.proposed_tool_calls[0].tool_name}')

    # P4: GeminiLiveProvider fallback when no API key
    gp = GeminiLiveProvider(api_key=None)
    result2 = asyncio.run(gp.plan_and_reason(ss, [], [], 'search for flights'))
    assert result2 is not None
    print(f'OK  P4: GeminiLiveProvider fallback: resp={result2.assistant_response!r}')

    # P5: Provider returns LLMPlan (never corrupts state by raising)
    op2 = OpenAILLMProvider(api_key=None)
    r3 = asyncio.run(op2.plan_and_reason(ss, [], [], 'hello'))
    assert isinstance(r3, LLMPlan), f'Expected LLMPlan, got {type(r3)}'
    print(f'OK  P5: Provider returns LLMPlan: {type(r3).__name__}')

    # P6: Tool manifest conversion
    tool_decl = _manifest_to_openai_tool(SEARCH_FLIGHTS_TOOL)
    assert tool_decl['type'] == 'function'
    assert 'function' in tool_decl
    assert tool_decl['function']['name'] == 'search_flights'
    print(f'OK  P6: Tool manifest -> LLM format: {tool_decl["function"]["name"]}')

    # P7: LLMPlan structure
    plan = LLMPlan(intent='tool_use', extracted_slots={'city': 'Mumbai'}, proposed_tool_calls=[], assistant_response='Test')
    assert plan.intent == 'tool_use'
    assert plan.extracted_slots['city'] == 'Mumbai'
    print('OK  P7: LLMPlan structured correctly')

    print()
    print('ALL 7 PROVIDER CHECKS PASSED')

if __name__ == '__main__':
    test_providers()
