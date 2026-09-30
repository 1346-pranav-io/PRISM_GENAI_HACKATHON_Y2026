import sys, asyncio
sys.path.insert(0, 'src')
from agent_runtime.core.event_bus import EventBus
from agent_runtime.core.state_manager import StateManager
from agent_runtime.core.task_manager import TaskManager
from agent_runtime.core.classifier import FastInterruptionClassifier
from agent_runtime.core.tool_registry import ToolRegistry
from agent_runtime.core.tool_executor import ToolExecutor
from agent_runtime.core.mock_llm import MockLLMProvider
from agent_runtime.core.trace_logger import TraceLogger
from agent_runtime.core.runtime_engine import AgentRuntimeEngine, StateRef
from agent_runtime.models.classifier import InterruptionCategory
from agent_runtime.models.llm_plan import LLMPlan
from agent_runtime.models.tools import ToolCallRequest
from agent_runtime.models.tasks import TaskRecord, TaskStatus, TaskType
from agent_runtime.models.events import EventType, RuntimeEvent
from agent_runtime.tools import SEARCH_FLIGHTS_TOOL, ADD_CALENDAR_EVENT_TOOL

def run_integration_tests():
    async def run():
        eb=EventBus(); sm=StateManager(); tm=TaskManager(); cl=FastInterruptionClassifier()
        tr=ToolRegistry(); tex=ToolExecutor(tr); llm=MockLLMProvider(0.01); tlog=TraceLogger()
        eng=AgentRuntimeEngine(eb,sm,tm,cl,tr,tex,llm,tlog)
        async def send_text(sid,text):
            await eng.handle_user_input(RuntimeEvent(session_id=sid,event_type=EventType.USER_TEXT,state_version=0,payload={'text':text}))
        async def send_interrupt(sid):
            await eng.handle_user_interruption(RuntimeEvent(session_id=sid,event_type=EventType.USER_INTERRUPTION,state_version=0,payload={}))
        async def slow_bg(): await asyncio.sleep(10); return 'done'
        sid='i1'; await sm.create_session(sid)
        r=await cl.classify('uh-huh',await sm.get_state(sid)); assert r.category==InterruptionCategory.BACKCHANNEL
        r2=await cl.classify('stop',await sm.get_state(sid)); assert r2.category==InterruptionCategory.CANCEL
        r3=await cl.classify('change destination to Mumbai',await sm.get_state(sid)); assert r3.category==InterruptionCategory.CORRECTION
        print('OK  T1: classifier async correct')
        sid='i2'; await sm.create_session(sid); await eng.init_session(sid)
        await tm.spawn_task(sid,TaskRecord(task_id='bg1',task_type=TaskType.REASONING,origin_state_version=1),slow_bg())
        await send_text(sid,'uh-huh'); await asyncio.sleep(0.05)
        t=await tm.get_task('bg1'); assert t.status==TaskStatus.RUNNING; await tm.cancel_all_active(sid,'cleanup')
        print('OK  T2: backchannel does NOT cancel')
        sid='i3'; await sm.create_session(sid); await eng.init_session(sid)
        await tm.spawn_task(sid,TaskRecord(task_id='bg2',task_type=TaskType.REASONING,origin_state_version=1),slow_bg())
        await send_text(sid,'STOP'); await asyncio.sleep(0.05)
        t2=await tm.get_task('bg2'); assert t2.status in (TaskStatus.CANCELLED,TaskStatus.CANCELLING)
        print('OK  T3: cancel stops task')
        sid='i4'; await sm.create_session(sid); await eng.init_session(sid)
        v1=(await sm.get_state(sid)).state_version; await send_text(sid,'Actually change destination to Delhi'); await asyncio.sleep(0.05)
        v2=(await sm.get_state(sid)).state_version; assert v2>v1; print(f'OK  T4: correction advances {v1}->{v2}')
        sid='i5'; await sm.create_session(sid); await eng.init_session(sid)
        eng._is_speaking[sid]=True; await send_interrupt(sid); await asyncio.sleep(0.02)
        assert eng._is_speaking.get(sid)==False; print('OK  T5: interruption resets _is_speaking')
        sid='i6'; await sm.create_session(sid); await eng.init_session(sid)
        for i in range(25): await send_text(sid,f'msg {i}')
        hist=eng._history.get(sid,[]); assert len(hist)<=20; print(f'OK  T6: history bounded {len(hist)}/20')
        sid='i7'; await sm.create_session(sid); await eng.init_session(sid)
        llm.set_response_for_query('search flights to mumbai',LLMPlan(intent='user_request',extracted_slots={},proposed_tool_calls=[ToolCallRequest(call_id='tool1',tool_name='search_flights',arguments={'query':'mumbai'},origin_state_version=1)],assistant_response='Searching...'))
        tr.register_tool(SEARCH_FLIGHTS_TOOL,lambda **kw: asyncio.sleep(0) or {'flights':[]})
        await send_text(sid,'search flights to mumbai'); await asyncio.sleep(0.1)
        tasks=await tm.get_session_tasks(sid); assert len(tasks)>=1; print(f'OK  T7: deliberate spawns {len(tasks)} task(s)')
        await tm.cancel_all_active(sid,'cleanup')
        sid='i8'; await sm.create_session(sid)
        vs=[(await sm.get_state(sid)).state_version]
        for i in range(5): await sm.apply_delta(sid,{str(i):str(i)}); vs.append((await sm.get_state(sid)).state_version)
        assert vs==list(range(1,7)); print(f'OK  T8: monotonic versions {vs}')
        sid='i9'; await sm.create_session(sid)
        v_old=(await sm.get_state(sid)).state_version; await sm.apply_delta(sid,{'x':'y'}); v_new=(await sm.get_state(sid)).state_version
        assert v_new>v_old
        async def add_event_executor(title: str = "", start_time: str = "", end_time: str = "", description: str = ""):
            return {"event_id": "E001", "title": title, "start_time": start_time, "end_time": end_time, "description": description}
        tr.register_tool(ADD_CALENDAR_EVENT_TOOL, add_event_executor)
        ref = StateRef(sm, sid)
        res = await tex.execute(ToolCallRequest(call_id='sc', tool_name='add_calendar_event', arguments={'title': 'Test', 'start_time': '10:00', 'end_time': '11:00', 'description': ''}, origin_state_version=v_old), ref)
        assert res.status == TaskStatus.STALE, f'Expected STALE, got {res.status} ({res.error})'
        assert res.error is not None; assert res.data is None; print(f'OK  T9: stale rejection STATE_MODIFYING (tool_v={v_old}, cur_v={v_new}), data={res.data}')
        sid='i10'; await sm.create_session(sid); await eng.init_session(sid)
        llm.set_response_for_query('hello',LLMPlan(intent='user_request',extracted_slots={},proposed_tool_calls=[],assistant_response='Hi'))
        eng._is_speaking[sid]=True; await eng._execute_deliberate_path(sid,'hello',(await sm.get_state(sid)).state_version)
        assert eng._is_speaking.get(sid)==False; print('OK  T10: deliberate resets _is_speaking')
        manifests=tr.get_manifests(); assert any(m.name=='search_flights' for m in manifests); assert any(m.name=='add_calendar_event' for m in manifests); print(f'OK  T11: registry {len(manifests)} tools')
        await tlog.log_event(RuntimeEvent(session_id='x',event_type=EventType.USER_TEXT,state_version=1,payload={}))
        trace = await tlog.get_session_trace('x')
        assert trace is not None and len(trace.events) == 1; print('OK  T12: trace_logger works')
        received=[]
        async def h(e): received.append(e)
        eb.subscribe(EventType.USER_TEXT,h); await eb.publish(RuntimeEvent(session_id='y',event_type=EventType.USER_TEXT,state_version=1,payload={})); await asyncio.sleep(0.05)
        assert len(received)==1; print('OK  T13: event_bus pub/sub')
        sid='i14'; await sm.create_session(sid)
        v=(await sm.get_state(sid)).state_version
        assert await sm.is_valid_version(sid,v) and not await sm.is_valid_version(sid,v+1) and not await sm.is_valid_version('nonexistent',1); print('OK  T14: is_valid_version')
        sid='i15'; await sm.create_session(sid)
        v1b=(await sm.get_state(sid)).state_version; ref=StateRef(sm,sid); assert int(ref)==v1b
        await sm.apply_delta(sid,{'n':'v'}); assert int(ref)==(await sm.get_state(sid)).state_version; print('OK  T15: StateRef dynamic')
        sid='i16'; await sm.create_session(sid)
        await tm.spawn_task(sid,TaskRecord(task_id='bg3',task_type=TaskType.REASONING,origin_state_version=1),slow_bg())
        cancelled=await tm.cancel_all_active(sid,'test'); assert 'bg3' in cancelled; print(f'OK  T16: cancel_all_active={cancelled}')
        sid='i17'; await sm.create_session(sid); await eng.init_session(sid)
        await send_text(sid,'change origin to Mumbai'); await asyncio.sleep(0.05)
        state=await sm.get_state(sid); assert state.slots.get('origin') is not None; assert state.slots['origin'].value=='Mumbai'; print(f'OK  T17: correction delta origin={state.slots["origin"].value}')
        print(); print('ALL 17 INTEGRATION TESTS PASSED')
    asyncio.run(run())
if __name__=='__main__': run_integration_tests()
