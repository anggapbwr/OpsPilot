"""Audit logging model for compliance and observability."""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class AuditEntry(BaseModel):
    """Structured audit entry for every policy decision and remediation execution."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    incident_id: str
    incident_type: str
    target: str
    diagnosis_source: str
    root_cause: str
    recommended_action: str
    policy_decision: str
    risk: str
    approval_required: bool
    execution_status: str
    verification_status: str
    attempt: int
    final_status: str
    notes: Optional[str] = None
