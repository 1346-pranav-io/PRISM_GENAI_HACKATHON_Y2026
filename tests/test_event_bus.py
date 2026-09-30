"""Unit tests for EventBus."""

import pytest
from src.agent_runtime.core.event_bus import EventBus
from src.agent_runtime.models.events import EventType, RuntimeEvent


@pytest.mark.asyncio
async def test_event_bus_pub_sub():
    bus = EventBus()
    received_specific = []
    received_all = []

    async def on_user_text(evt: RuntimeEvent):
        received_specific.append(evt)

    async def on_any_event(evt: RuntimeEvent):
        received_all.append(evt)

    bus.subscribe(EventType.USER_TEXT, on_user_text)
    bus.subscribe_all(on_any_event)

    event1 = RuntimeEvent(
        event_type=EventType.USER_TEXT,
        session_id="s1",
        state_version=1,
        payload={"text": "Hello"},
    )
    event2 = RuntimeEvent(
        event_type=EventType.TASK_SCHEDULED,
        session_id="s1",
        state_version=1,
        payload={"task_id": "t1"},
    )

    await bus.publish(event1)
    await bus.publish(event2)

    assert len(received_specific) == 1
    assert received_specific[0].payload["text"] == "Hello"
    assert len(received_all) == 2

