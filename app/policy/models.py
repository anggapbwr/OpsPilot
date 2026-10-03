"""Policy definitions and schema models."""

from typing import Dict, Optional

from pydantic import BaseModel, Field

from app.models.remediation import RiskLevel


class PolicyRule(BaseModel):
    """Configuration rule for a specific remediation action."""

    risk: RiskLevel = Field(default=RiskLevel.low)
    auto_execute: bool = Field(default=False)
    requires_approval: bool = Field(default=False)
    max_attempts: int = Field(default=1, ge=0)
    blocked: bool = Field(default=False)
    description: Optional[str] = None


class PolicyDocument(BaseModel):
    """Complete collection of remediation policies loaded from YAML."""

    policies: Dict[str, PolicyRule] = Field(default_factory=dict)
