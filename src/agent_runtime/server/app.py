"""FastAPI application factory for the agent runtime server."""
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from .routes import router
from .ws_handler import WebSocketSession
from ..core.event_bus import EventBus
from ..core.runtime_engine import AgentRuntimeEngine
from ..core.state_manager import StateManager
from ..core.task_manager import TaskManager
from ..core.classifier import FastInterruptionClassifier
from ..core.tool_registry import ToolRegistry
from ..core.tool_executor import ToolExecutor
from ..core.mock_llm import MockLLMProvider
from ..core.trace_logger import TraceLogger
from ..tools import get_search_flights_executor, SEARCH_FLIGHTS_TOOL
from ..tools import GET_WEATHER_TOOL, get_weather_executor
logger = logging.getLogger(__name__)

_server_runtime: dict | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _server_runtime
    bus = EventBus()
    sm = StateManager()
    tm = TaskManager()
    clf = FastInterruptionClassifier()
    reg = ToolRegistry()
    # Register domain tools
    reg.register_tool(SEARCH_FLIGHTS_TOOL, await get_search_flights_executor())
    reg.register_tool(GET_WEATHER_TOOL, await get_weather_executor())
    tex = ToolExecutor(reg)
    # Demo knob: a larger value (e.g. 1.5) leaves time to type a correction by hand.
    llm = MockLLMProvider(latency_seconds=float(os.environ.get("AGENT_LLM_LATENCY_SECONDS", "0.05")))
    trace = TraceLogger()
    engine = AgentRuntimeEngine(
        event_bus=bus, state_manager=sm, task_manager=tm,
        classifier=clf, tool_registry=reg, tool_executor=tex,
        llm_provider=llm, trace_logger=trace,
    )
    _server_runtime = {"engine": engine, "bus": bus, "sm": sm, "tm": tm, "trace": trace, "reg": reg}
    app.state.runtime = _server_runtime
    logger.info("Runtime engine initialized for server")
    yield
    logger.info("Server shutting down")
    _server_runtime = None
    app.state.runtime = None

def create_app() -> FastAPI:
    app = FastAPI(
        title="Interruptible Realtime Agent Runtime",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(router, prefix="/api/v1")

    @app.websocket("/ws/{session_id}")
    async def websocket_endpoint(ws: WebSocket, session_id: str):
        if _server_runtime is None:
            await ws.close(code=1011, reason="Server not initialized")
            return
        engine = _server_runtime["engine"]
        bus = _server_runtime["bus"]
        trace = _server_runtime["trace"]
        sm = _server_runtime["sm"]
        session = WebSocketSession(ws, bus, engine, trace, sm, session_id=session_id)
        await session.start()

    return app

app = create_app()
