"""Diagnosis models and schemas."""

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class DiagnosisSource(str, Enum):
    """Source of the incident diagnosis."""

    ai = "ai"
    fallback = "fallback"


# Valid actions that the AI is permitted to recommend.
# Any unknown or malicious action (e.g. rm_rf, delete_database, execute_shell) must be rejected!
ALLOWED_ACTIONS = {
    "restart_container",
    "restart_service",
    "rollback_deployment",
    "no_action",
    "escalate",
}

AllowedActionType = Literal[
    "restart_container",
    "restart_service",
    "rollback_deployment",
    "no_action",
    "escalate",
]


class AIDiagnosisOutput(BaseModel):
    """Strict schema required from Ollama / AI model."""

    root_cause: str = Field(..., description="Identified root cause of the incident")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Model confidence between 0.0 and 1.0")
    recommended_action: str = Field(..., description="Action from recognized whitelist")
    reasoning_summary: str = Field(..., description="Summary reasoning for recommendation")

    @field_validator("recommended_action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in ALLOWED_ACTIONS:
            raise ValueError(
                f"Action '{v}' is unauthorized. Allowed actions: {sorted(list(ALLOWED_ACTIONS))}"
            )
        return clean


class DiagnosisResult(BaseModel):
    """Final validated diagnosis attached to an incident."""

    root_cause: str
    confidence: float
    recommended_action: str
    reasoning_summary: str
    source: DiagnosisSource = DiagnosisSource.ai
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
