"""Unit tests for Interruption Classifier."""

import pytest
from src.agent_runtime.core.classifier import FastInterruptionClassifier
from src.agent_runtime.models.classifier import InterruptionCategory
from src.agent_runtime.models.state import SessionState


@pytest.mark.asyncio
async def test_classify_backchannel():
    classifier = FastInterruptionClassifier()
    state = SessionState(session_id="s1")

    res1 = await classifier.classify("uh-huh", state)
    assert res1.category == InterruptionCategory.BACKCHANNEL
    assert res1.extracted_deltas == {}
    assert res1.classification_duration_ms < 5.0

    res2 = await classifier.classify("yeah", state)
    assert res2.category == InterruptionCategory.BACKCHANNEL


@pytest.mark.asyncio
async def test_classify_cancel():
    classifier = FastInterruptionClassifier()
    state = SessionState(session_id="s1")

    res = await classifier.classify("stop!", state)
    assert res.category == InterruptionCategory.CANCEL


@pytest.mark.asyncio
async def test_classify_correction_with_deltas():
    classifier = FastInterruptionClassifier()
    state = SessionState(session_id="s1")

    res = await classifier.classify("No wait, change destination to Paris", state)
    assert res.category == InterruptionCategory.CORRECTION
    assert res.extracted_deltas.get("destination") == "Paris"


@pytest.mark.asyncio
async def test_classify_new_query():
    classifier = FastInterruptionClassifier()
    state = SessionState(session_id="s1")

    res = await classifier.classify("Find me flights from Seattle to Tokyo", state)
    assert res.category == InterruptionCategory.NEW_QUERY
