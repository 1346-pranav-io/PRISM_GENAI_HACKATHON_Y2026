"""Unit tests for StateManager."""

import asyncio
import pytest
from src.agent_runtime.core.state_manager import StateManager
from src.agent_runtime.models.state import SessionStatus


@pytest.mark.asyncio
async def test_session_creation():
    mgr = StateManager()
    state = await mgr.create_session("session_1")
    assert state.session_id == "session_1"
    assert state.state_version == 1
    assert state.status == SessionStatus.ACTIVE
    assert state.slots == {}


@pytest.mark.asyncio
async def test_monotonic_state_versioning():
    mgr = StateManager()
    state1 = await mgr.create_session("s1")
    assert state1.state_version == 1

    # Apply slot delta
    state2 = await mgr.apply_delta("s1", slot_deltas={"destination": "Mumbai"})
    assert state2.state_version == 2
    assert "destination" in state2.slots
    assert state2.slots["destination"].value == "Mumbai"
    assert state2.slots["destination"].source_state_version == 2

    # Apply intent change
    state3 = await mgr.apply_delta("s1", intent="book_flight")
    assert state3.state_version == 3
    assert state3.current_intent == "book_flight"
    assert state3.slots["destination"].source_state_version == 2


@pytest.mark.asyncio
async def test_is_valid_version():
    mgr = StateManager()
    await mgr.create_session("s1")
    assert await mgr.is_valid_version("s1", 1) is True
    assert await mgr.is_valid_version("s1", 2) is False

    await mgr.apply_delta("s1", slot_deltas={"origin": "London"})
    assert await mgr.is_valid_version("s1", 1) is False
    assert await mgr.is_valid_version("s1", 2) is True


@pytest.mark.asyncio
async def test_concurrent_mutations():
    mgr = StateManager()
    await mgr.create_session("s_concurrent")

    async def mutate(k: str, v: str):
        await mgr.apply_delta("s_concurrent", slot_deltas={k: v})

    await asyncio.gather(
        mutate("slot_a", "val_a"),
        mutate("slot_b", "val_b"),
        mutate("slot_c", "val_c"),
    )

    final_state = await mgr.get_state("s_concurrent")
    assert final_state.state_version == 4
    assert len(final_state.slots) == 3
    assert final_state.slots["slot_a"].value == "val_a"
    assert final_state.slots["slot_b"].value == "val_b"
    assert final_state.slots["slot_c"].value == "val_c"
