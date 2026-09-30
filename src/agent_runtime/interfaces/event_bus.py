"""Event bus abstract interface."""

from abc import ABC, abstractmethod
from typing import Awaitable, Callable
from ..models.events import EventType, RuntimeEvent


class IEventBus(ABC):
    @abstractmethod
    async def publish(self, event: RuntimeEvent) -> None:
        """Publish an event to all subscribers."""
        pass

    @abstractmethod
    def subscribe(
        self,
        event_type: EventType,
        handler: Callable[[RuntimeEvent], Awaitable[None]],
    ) -> None:
        """Subscribe an async handler to a specific event type."""
        pass
