"""Unit tests for the independent verification engine."""

from unittest.mock import AsyncMock

import pytest

from app.detection.health_checker import HealthChecker
from app.models.incident import Incident, IncidentSeverity, IncidentState, IncidentType
from app.models.remediation import RemediationAttempt, RemediationStatus, VerificationStatus
from app.verification.verifier import Verifier


@pytest.fixture
def sample_incident() -> Incident:
    inc = Incident(
        id="INC-VERIFY-1",
        type=IncidentType.container_unhealthy,
        severity=IncidentSeverity.medium,
        target="payment-api",
        status=IncidentState.verifying,
        attempt_count=1,
        max_attempts=3,
    )
    inc.remediation_history.append(
        RemediationAttempt(
            attempt_number=1,
            action="restart_container",
            playbook="restart_container.yml",
            status=RemediationStatus.success,
        )
    )
    return inc


@pytest.mark.asyncio
async def test_verification_success_resolves_incident(sample_incident: Incident):
    """When target returns HTTP 200, verification marks success and resolves incident."""
    mock_health = AsyncMock(spec=HealthChecker)
    mock_health.check_http_health.return_value = {
        "healthy": True,
        "status_code": 200,
        "latency_ms": 15.0,
    }

    verifier = Verifier(health_checker=mock_health, delay_seconds=0.0)
    result = await verifier.verify(sample_incident)

    assert result["passed"] is True
    assert sample_incident.status == IncidentState.resolved
    assert sample_incident.remediation_history[-1].verification_status == VerificationStatus.passed


@pytest.mark.asyncio
async def test_verification_failure_triggers_retry_if_attempts_remain(sample_incident: Incident):
    """When verification fails and attempt < max_attempts, state transitions back to remediating for retry."""
    mock_health = AsyncMock(spec=HealthChecker)
    mock_health.check_http_health.return_value = {
        "healthy": False,
        "status_code": 500,
        "error": "HTTP 500 Internal Server Error",
    }

    sample_incident.attempt_count = 1
    sample_incident.max_attempts = 3

    verifier = Verifier(health_checker=mock_health, delay_seconds=0.0)
    result = await verifier.verify(sample_incident)

    assert result["passed"] is False
    assert sample_incident.status == IncidentState.remediating
    assert sample_incident.remediation_history[-1].verification_status == VerificationStatus.failed


@pytest.mark.asyncio
async def test_verification_failure_escalates_when_max_attempts_reached(sample_incident: Incident):
    """When verification fails and attempt count reaches max_attempts, incident escalates."""
    mock_health = AsyncMock(spec=HealthChecker)
    mock_health.check_http_health.return_value = {
        "healthy": False,
        "status_code": 500,
        "error": "HTTP 500 Internal Server Error",
    }

    sample_incident.attempt_count = 3
    sample_incident.max_attempts = 3

    verifier = Verifier(health_checker=mock_health, delay_seconds=0.0)
    result = await verifier.verify(sample_incident)

    assert result["passed"] is False
    assert sample_incident.status == IncidentState.escalated
    assert sample_incident.remediation_history[-1].verification_status == VerificationStatus.failed


@pytest.mark.asyncio
async def test_verification_distinguishes_failed_remediation_with_independent_recovery(sample_incident: Incident):
    """When remediation execution failed but target independently recovered, outcome must reflect this."""
    sample_incident.remediation_history[-1].status = RemediationStatus.failure
    mock_health = AsyncMock(spec=HealthChecker)
    mock_health.check_http_health.return_value = {
        "healthy": True,
        "status_code": 200,
        "latency_ms": 12.0,
    }

    verifier = Verifier(health_checker=mock_health, delay_seconds=0.0)
    result = await verifier.verify(sample_incident)

    assert result["passed"] is True
    assert result["remediation_succeeded"] is False
    assert result["outcome"] == "REMEDIATION_FAILED_BUT_RECOVERED_INDEPENDENTLY"
    assert sample_incident.status == IncidentState.resolved
    assert "recovered independently" in result["message"].lower()
