"""Interruption classification models."""

from enum import Enum
from typing import Any, Dict
from pydantic import BaseModel, Field


class InterruptionCategory(str, Enum):
    CORRECTION = "CORRECTION"
    INTERRUPTION = "INTERRUPTION"
    BACKCHANNEL = "BACKCHANNEL"
    NEW_QUERY = "NEW_QUERY"
    CANCEL = "CANCEL"
    UNKNOWN = "UNKNOWN"


class ClassificationResult(BaseModel):
    category: InterruptionCategory
    confidence: float = 1.0
    extracted_deltas: Dict[str, Any] = Field(default_factory=dict)
    classification_duration_ms: float = 0.0
