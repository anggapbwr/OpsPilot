"""Remediation and policy decision models."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    """Risk rating assigned by policy."""

    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class RemediationStatus(str, Enum):
    """Status of a remediation execution attempt."""

    pending = "pending"
    running = "running"
    success = "success"
    failure = "failure"
    timeout = "timeout"
    skipped = "skipped"


class VerificationStatus(str, Enum):
    """Status of health verification after remediation."""

    pending = "pending"
    passed = "passed"
    failed = "failed"


class PolicyDecision(BaseModel):
    """Deterministic decision produced by the policy engine."""

    action: str
    risk: RiskLevel = RiskLevel.low
    allowed: bool = False
    auto_execute: bool = False
    requires_approval: bool = False
    max_attempts: int = 3
    blocked: bool = False
    reason: Optional[str] = None
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ApprovalRecord(BaseModel):
    """Human approval record for high-risk actions."""

    approved: bool
    approved_by: str
    approved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    note: Optional[str] = None


class RemediationAttempt(BaseModel):
    """Audit record for an individual remediation execution attempt."""

    attempt_number: int
    action: str
    playbook: Optional[str] = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    status: RemediationStatus = RemediationStatus.pending
    verification_status: VerificationStatus = VerificationStatus.pending
    output: Optional[str] = None
    error: Optional[str] = None
