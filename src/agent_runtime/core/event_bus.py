"""In-memory async EventBus implementation."""

import asyncio
import logging
from typing import Awaitable, Callable, Dict, List
from ..interfaces.event_bus import IEventBus
from ..models.events import EventType, RuntimeEvent

logger = logging.getLogger(__name__)


class EventBus(IEventBus):
    """High-throughput in-memory async event bus."""

    def __init__(self) -> None:
        self._subscribers: Dict[EventType, List[Callable[[RuntimeEvent], Awaitable[None]]]] = {}
        self._global_subscribers: List[Callable[[RuntimeEvent], Awaitable[None]]] = []
        self._lock = asyncio.Lock()

    def subscribe(
        self,
        event_type: EventType,
        handler: Callable[[RuntimeEvent], Awaitable[None]],
    ) -> None:
        """Register an async callback for a specific event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    def subscribe_all(
        self,
        handler: Callable[[RuntimeEvent], Awaitable[None]],
    ) -> None:
        """Register an async callback for ALL event types."""
        self._global_subscribers.append(handler)

    def unsubscribe(
        self,
        event_type: EventType,
        handler: Callable[[RuntimeEvent], Awaitable[None]],
    ) -> None:
        """Remove a handler previously registered for a specific event type."""
        handlers = self._subscribers.get(event_type)
        if handlers and handler in handlers:
            handlers.remove(handler)

    def unsubscribe_all(
        self,
        handler: Callable[[RuntimeEvent], Awaitable[None]],
    ) -> None:
        """Remove a handler from the global list and from every per-type list."""
        while handler in self._global_subscribers:
            self._global_subscribers.remove(handler)
        for handlers in self._subscribers.values():
            while handler in handlers:
                handlers.remove(handler)

    async def publish(self, event: RuntimeEvent) -> None:
        """Publish event to all relevant subscribers concurrently."""
        handlers = list(self._global_subscribers)
        if event.event_type in self._subscribers:
            handlers.extend(self._subscribers[event.event_type])

        if not handlers:
            return

        async def _invoke(h: Callable[[RuntimeEvent], Awaitable[None]]) -> None:
            try:
                await h(event)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Error in event handler for {event.event_type}: {e}", exc_info=True)

        await asyncio.gather(*[_invoke(h) for h in handlers], return_exceptions=True)
