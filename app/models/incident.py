"""Incident core domain model with state machine."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.core.exceptions import InvalidStateTransitionError
from app.models.diagnosis import DiagnosisResult
from app.models.remediation import ApprovalRecord, PolicyDecision, RemediationAttempt


class IncidentType(str, Enum):
    """Supported incident types."""

    container_unhealthy = "container_unhealthy"
    service_unavailable = "service_unavailable"
    failed_health_check = "failed_health_check"
    failed_deployment = "failed_deployment"


class IncidentSeverity(str, Enum):
    """Supported severity levels."""

    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class IncidentState(str, Enum):
    """Supported incident states."""

    detected = "detected"
    investigating = "investigating"
    diagnosed = "diagnosed"
    awaiting_approval = "awaiting_approval"
    remediating = "remediating"
    verifying = "verifying"
    resolved = "resolved"
    escalated = "escalated"
    blocked = "blocked"


# Strict deterministic state machine transition rules
VALID_TRANSITIONS: Dict[IncidentState, List[IncidentState]] = {
    IncidentState.detected: [
        IncidentState.investigating,
        IncidentState.escalated,
    ],
    IncidentState.investigating: [
        IncidentState.diagnosed,
        IncidentState.escalated,
    ],
    IncidentState.diagnosed: [
        IncidentState.awaiting_approval,
        IncidentState.remediating,
        IncidentState.blocked,
        IncidentState.escalated,
        IncidentState.resolved,  # E.g. no_action taken
    ],
    IncidentState.awaiting_approval: [
        IncidentState.remediating,
        IncidentState.blocked,
        IncidentState.escalated,
    ],
    IncidentState.remediating: [
        IncidentState.verifying,
        IncidentState.escalated,
    ],
    IncidentState.verifying: [
        IncidentState.resolved,
        IncidentState.remediating,  # Bounded retry
        IncidentState.escalated,
    ],
    IncidentState.blocked: [
        IncidentState.escalated,
    ],
    IncidentState.resolved: [],
    IncidentState.escalated: [],
}


class Incident(BaseModel):
    """Core domain model representing an operational incident."""

    id: str = Field(..., description="Unique incident identifier (e.g. INC-0001)")
    type: IncidentType = Field(default=IncidentType.container_unhealthy)
    severity: IncidentSeverity = Field(default=IncidentSeverity.medium)
    target: str = Field(default="payment-api", description="Target service or container")
    status: IncidentState = Field(default=IncidentState.detected)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None

    attempt_count: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1)

    evidence: Optional[Dict[str, Any]] = None
    diagnosis: Optional[DiagnosisResult] = None
    policy_decision: Optional[PolicyDecision] = None
    approval: Optional[ApprovalRecord] = None
    remediation_history: List[RemediationAttempt] = Field(default_factory=list)

    def transition_to(self, new_state: IncidentState, reason: str = "") -> None:
        """Safely transition incident to a new state or raise InvalidStateTransitionError."""
        allowed = VALID_TRANSITIONS.get(self.status, [])
        if new_state not in allowed:
            raise InvalidStateTransitionError(
                current_state=self.status.value,
                target_state=new_state.value,
            )

        self.status = new_state
        self.updated_at = datetime.now(timezone.utc)
        if new_state == IncidentState.resolved:
            self.resolved_at = datetime.now(timezone.utc)

    @property
    def is_terminal(self) -> bool:
        """Check if incident is in a final state."""
        return self.status in {IncidentState.resolved, IncidentState.escalated}
