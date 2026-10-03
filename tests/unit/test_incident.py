"""Unit tests for Incident domain model and state machine."""

import pytest

from app.core.exceptions import InvalidStateTransitionError
from app.models.incident import Incident, IncidentSeverity, IncidentState, IncidentType


def test_valid_state_transitions():
    """Verify standard happy-path lifecycle transitions."""
    incident = Incident(
        id="INC-100",
        type=IncidentType.container_unhealthy,
        severity=IncidentSeverity.medium,
        target="payment-api",
        status=IncidentState.detected,
    )

    incident.transition_to(IncidentState.investigating)
    assert incident.status == IncidentState.investigating

    incident.transition_to(IncidentState.diagnosed)
    assert incident.status == IncidentState.diagnosed

    incident.transition_to(IncidentState.remediating)
    assert incident.status == IncidentState.remediating

    incident.transition_to(IncidentState.verifying)
    assert incident.status == IncidentState.verifying

    incident.transition_to(IncidentState.resolved)
    assert incident.status == IncidentState.resolved
    assert incident.resolved_at is not None
    assert incident.is_terminal is True


def test_approval_state_transitions():
    """Verify transitions through awaiting_approval."""
    incident = Incident(
        id="INC-101",
        status=IncidentState.diagnosed,
    )

    incident.transition_to(IncidentState.awaiting_approval)
    assert incident.status == IncidentState.awaiting_approval

    incident.transition_to(IncidentState.remediating)
    assert incident.status == IncidentState.remediating


def test_invalid_state_transitions_raise_exception():
    """Illegal state jumps must raise InvalidStateTransitionError."""
    incident = Incident(
        id="INC-102",
        status=IncidentState.detected,
    )

    # Cannot skip directly to resolved
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        incident.transition_to(IncidentState.resolved)
    assert exc_info.value.current_state == "detected"
    assert exc_info.value.target_state == "resolved"

    # Move to resolved
    incident.status = IncidentState.resolved

    # Terminal state cannot transition back to remediating
    with pytest.raises(InvalidStateTransitionError):
        incident.transition_to(IncidentState.remediating)


def test_blocked_transition_on_policy_rejection():
    """Incident transitions to blocked when policy denies action."""
    incident = Incident(
        id="INC-103",
        status=IncidentState.diagnosed,
    )

    incident.transition_to(IncidentState.blocked)
    assert incident.status == IncidentState.blocked
