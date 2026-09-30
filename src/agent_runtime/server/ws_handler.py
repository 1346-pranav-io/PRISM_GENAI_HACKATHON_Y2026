"""WebSocket session handler bridging the browser/client to AgentRuntimeEngine.

Each WebSocket connection is mapped to one runtime session. The handler
publishes USER_TEXT events into the EventBus and subscribes to all events,
forwarding them back to the client as JSON.

On disconnect the handler cleanly cancels the deliberate path task and
removes session state.
"""
import asyncio
import json
import logging
import uuid
from typing import Any, Dict, List, Optional
from fastapi import WebSocket, WebSocketDisconnect
from ..core.event_bus import EventBus
from ..core.runtime_engine import AgentRuntimeEngine
from ..core.state_manager import StateManager
from ..core.task_manager import TaskManager
from ..core.classifier import FastInterruptionClassifier
from ..core.tool_registry import ToolRegistry
from ..core.tool_executor import ToolExecutor
from ..core.mock_llm import MockLLMProvider
from ..core.trace_logger import TraceLogger
from ..models.events import EventType, RuntimeEvent
logger = logging.getLogger(__name__)

class WebSocketSession:
    """Manages a single WebSocket client connection to the agent runtime."""

    def __init__(
        self,
        websocket: WebSocket,
        event_bus: EventBus,
        engine: AgentRuntimeEngine,
        trace_logger: TraceLogger,
        state_manager: StateManager,
        session_id: Optional[str] = None,
    ) -> None:
        self.ws = websocket
        self.event_bus = event_bus
        self.engine = engine
        self.trace_logger = trace_logger
        self.state_manager = state_manager
        self.session_id = session_id or f"ws_{uuid.uuid4().hex[:12]}"
        self._deliberate_task: Optional[asyncio.Task[None]] = None
        self._running = False
        self._subscribed = False

    async def _outbound_sender(self, evt: RuntimeEvent) -> None:
        """Forward runtime events to the WebSocket client as JSON."""
        if not self._running or evt.session_id != self.session_id:
            return
        try:
            payload = {
                "session_id": evt.session_id,
                "event_type": evt.event_type.value,
                "state_version": evt.state_version,
                "timestamp": evt.timestamp.isoformat(),
                **evt.payload,
            }
            await self.ws.send_json(payload)
        except Exception as exc:
            logger.warning("Failed to send event to WebSocket: %s", exc)

    async def start(self) -> None:
        """Initialize the runtime session and start listening for inbound messages."""
        await self.ws.accept()
        try:
            await self.engine.init_session(self.session_id)
            # A single global subscription; _outbound_sender filters by session_id.
            self.event_bus.subscribe_all(self._outbound_sender)
            self._subscribed = True
            self._running = True
            self._deliberate_task = asyncio.create_task(self._run_deliberate_path())
            while self._running:
                raw = await self.ws.receive_text()
                await self._handle_client_message(raw)
        except WebSocketDisconnect:
            logger.info("WebSocket disconnected for session %s", self.session_id)
        finally:
            await self._shutdown()

    async def _handle_client_message(self, raw: str) -> None:
        """Parse and dispatch inbound client messages to the event bus."""
        try:
            msg = json.loads(raw)
        except Exception:
            msg = {"type": "user_text", "text": raw}
        msg_type = msg.get("type", "user_text")
        if msg_type == "interrupt":
            await self.event_bus.publish(RuntimeEvent(
                session_id=self.session_id,
                event_type=EventType.USER_INTERRUPTION,
                state_version=self.state_manager.get_current_version(self.session_id),
                payload={"text": msg.get("text", "")},
            ))
        else:
            await self.event_bus.publish(RuntimeEvent(
                session_id=self.session_id,
                event_type=EventType.USER_TEXT,
                state_version=self.state_manager.get_current_version(self.session_id),
                payload={"text": msg.get("text", msg.get("content", raw))},
            ))

    async def _run_deliberate_path(self) -> None:
        """Proxy task that keeps the deliberate path running until cancelled."""
        # The deliberate path is driven by the event bus subscriber in engine.
        # We just keep this task alive until shutdown.
        try:
            while self._running:
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass

    async def _shutdown(self) -> None:
        """Cleanly terminate session work on disconnect."""
        self._running = False
        if self._subscribed:
            self.event_bus.unsubscribe_all(self._outbound_sender)
            self._subscribed = False
        if self._deliberate_task:
            self._deliberate_task.cancel("WebSocket disconnected")
            try:
                await self._deliberate_task
            except asyncio.CancelledError:
                pass
        logger.info("Session %s shut down", self.session_id)
