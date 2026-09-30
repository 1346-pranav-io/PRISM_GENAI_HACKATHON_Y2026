"""Interruption classifier interface."""

from abc import ABC, abstractmethod
from ..models.classifier import ClassificationResult
from ..models.state import SessionState


class IInterruptionClassifier(ABC):
    @abstractmethod
    async def classify(
        self,
        utterance: str,
        current_state: SessionState,
    ) -> ClassificationResult:
        """Classify user utterance to determine interruption action."""
        pass
