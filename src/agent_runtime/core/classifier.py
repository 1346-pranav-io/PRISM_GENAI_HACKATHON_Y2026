"""Rule-based and heuristic Interruption Classifier."""

import re
import time
from typing import Any, Dict
from ..interfaces.classifier import IInterruptionClassifier
from ..models.classifier import ClassificationResult, InterruptionCategory
from ..models.state import SessionState


class FastInterruptionClassifier(IInterruptionClassifier):
    """Ultra-low-latency rule-based classifier for inbound utterances (<5ms execution)."""

    BACKCHANNEL_PATTERNS = [
        r"^(uh-huh|yeah|yes|ok|okay|mm-hmm|right|got it|i see|sure|cool|yep|yup|alright|go on|go ahead|mhm)[\.!\?]?$"
    ]

    CANCEL_PATTERNS = [
        r"^(stop|cancel|never\s*mind|abort|shut\s*up|hold\s*on|pause|halt)[\.!\?]?$"
    ]

    CORRECTION_PATTERNS = [
        r"^(no|wait|actually|instead|i mean|change\s+to|not\s+\w+)",
        r"(change|switch|update)\s+(the\s+)?(destination|origin|date|flight|hotel|ticket)\s+to\s+(.+)",
    ]

    # Corrections that name a new value but not the slot, e.g. "actually make it New York".
    # Explicit verb form: any short value is accepted.
    IMPLICIT_VALUE_EXPLICIT_VERB = re.compile(
        r"\b(?:make|change|switch|set)\s+it\s+(?:to\s+)?(?P<value>[^,.!?]+?)(?:\s+instead)?[.!?]*$",
        re.IGNORECASE,
    )
    # Bare form ("No, London" / "Actually Mumbai"): only a capitalised name of up to 3 words,
    # so that "actually, can you check hotels" is not mistaken for a slot value.
    IMPLICIT_VALUE_BARE = re.compile(
        r"^(?:(?i:no|wait|actually|i mean)[\s,]+)+(?i:to\s+)?"
        r"(?P<value>[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*){0,2})(?:\s+instead)?[.!?]*$"
    )
    MAX_IMPLICIT_VALUE_WORDS = 4

    def __init__(self) -> None:
        self._backchannel_re = [re.compile(p, re.IGNORECASE) for p in self.BACKCHANNEL_PATTERNS]
        self._cancel_re = [re.compile(p, re.IGNORECASE) for p in self.CANCEL_PATTERNS]
        self._correction_re = [re.compile(p, re.IGNORECASE) for p in self.CORRECTION_PATTERNS]

    def _implicit_slot_correction(self, text: str, current_state: SessionState) -> Dict[str, Any]:
        """Apply a slot-less correction to the most recently updated slot, if any."""
        if not current_state.slots:
            return {}
        m = self.IMPLICIT_VALUE_EXPLICIT_VERB.search(text) or self.IMPLICIT_VALUE_BARE.match(text)
        if not m:
            return {}
        value = m.group("value").strip()
        if not value or len(value.split()) > self.MAX_IMPLICIT_VALUE_WORDS:
            return {}
        target = max(
            current_state.slots.values(),
            key=lambda s: (s.source_state_version, s.updated_at),
        )
        if target.value == value:
            return {}
        return {target.key: value}

    async def classify(
        self,
        utterance: str,
        current_state: SessionState,
    ) -> ClassificationResult:
        start_time = time.perf_counter()
        text = utterance.strip()
        category = InterruptionCategory.UNKNOWN
        extracted_deltas: Dict[str, Any] = {}

        # 1. Check Backchannel
        for p in self._backchannel_re:
            if p.match(text):
                category = InterruptionCategory.BACKCHANNEL
                break

        # 2. Check Cancellation
        if category == InterruptionCategory.UNKNOWN:
            for p in self._cancel_re:
                if p.match(text):
                    category = InterruptionCategory.CANCEL
                    break

        # 3. Check Correction & extract slot updates
        if category == InterruptionCategory.UNKNOWN:
            for p in self._correction_re:
                m = p.search(text)
                if m:
                    category = InterruptionCategory.CORRECTION
                    # Check for simple entity updates: e.g. "change destination to London"
                    dest_match = re.search(r"destination\s+to\s+([a-zA-Z\s]+)", text, re.IGNORECASE)
                    if dest_match:
                        extracted_deltas["destination"] = dest_match.group(1).strip()
                    origin_match = re.search(r"origin\s+to\s+([a-zA-Z\s]+)", text, re.IGNORECASE)
                    if origin_match:
                        extracted_deltas["origin"] = origin_match.group(1).strip()
                    date_match = re.search(r"date\s+to\s+([\w\s]+)", text, re.IGNORECASE)
                    if date_match:
                        extracted_deltas["date"] = date_match.group(1).strip()
                    if not extracted_deltas:
                        extracted_deltas = self._implicit_slot_correction(text, current_state)
                    break

        # 4. Default to NEW_QUERY if not backchannel/cancel/correction
        if category == InterruptionCategory.UNKNOWN:
            category = InterruptionCategory.NEW_QUERY

        duration_ms = (time.perf_counter() - start_time) * 1000
        return ClassificationResult(
            category=category,
            confidence=0.95 if category != InterruptionCategory.UNKNOWN else 0.5,
            extracted_deltas=extracted_deltas,
            classification_duration_ms=duration_ms,
        )
