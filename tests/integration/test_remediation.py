"""Integration tests for remediation execution and policy enforcement."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import PolicyDeniedError, RemediationExecutionError
from app.models.diagnosis import DiagnosisResult, DiagnosisSource
from app.models.incident import Incident, IncidentState
from app.models.remediation import ApprovalRecord, RiskLevel
from app.policy.engine import PolicyEngine
from app.policy.models import PolicyDocument, PolicyRule
from app.remediation.ansible_runner import AnsibleRunner
from app.remediation.executor import RemediationExecutor


@pytest.fixture
def mock_policy_engine() -> PolicyEngine:
    doc = PolicyDocument(
        policies={
            "restart_container": PolicyRule(
                risk=RiskLevel.low,
                auto_execute=True,
                requires_approval=False,
                max_attempts=3,
                blocked=False,
            ),
            "rollback_deployment": PolicyRule(
                risk=RiskLevel.medium,
                auto_execute=False,
                requires_approval=True,
                max_attempts=1,
                blocked=False,
            ),
            "delete_resource": PolicyRule(
                risk=RiskLevel.critical,
                auto_execute=False,
                requires_approval=True,
                max_attempts=0,
                blocked=True,
            ),
        }
    )
    return PolicyEngine(policy_doc=doc)


@pytest.fixture
def mock_ansible_runner() -> AnsibleRunner:
    runner = AsyncMock(spec=AnsibleRunner)
    runner.get_playbook_for_action.side_effect = lambda a: f"{a}.yml" if a in {"restart_container", "rollback_deployment"} else None
    runner.execute_action.return_value = {
        "success": True,
        "action": "restart_container",
        "playbook": "restart_container.yml",
        "returncode": 0,
        "duration_seconds": 1.2,
        "stdout": "Restarted container payment-api",
        "stderr": "",
    }
    return runner


@pytest.mark.asyncio
async def test_low_risk_action_executes_automatically(mock_policy_engine, mock_ansible_runner):
    """Low risk action (restart_container) is executed without requiring manual approval."""
    incident = Incident(
        id="INC-EXEC-1",
        status=IncidentState.diagnosed,
        diagnosis=DiagnosisResult(
            root_cause="worker_hang",
            confidence=0.9,
            recommended_action="restart_container",
            reasoning_summary="Worker hung.",
            source=DiagnosisSource.fallback,
        ),
    )

    executor = RemediationExecutor(
        policy_engine=mock_policy_engine,
        ansible_runner=mock_ansible_runner,
    )

    attempt = await executor.execute(incident)

    assert attempt.action == "restart_container"
    assert incident.status == IncidentState.verifying
    assert incident.attempt_count == 1
    assert len(incident.remediation_history) == 1
    mock_ansible_runner.execute_action.assert_called_once()


@pytest.mark.asyncio
async def test_high_risk_action_pauses_for_approval(mock_policy_engine, mock_ansible_runner):
    """Medium/High risk action (rollback_deployment) must pause in awaiting_approval."""
    incident = Incident(
        id="INC-EXEC-2",
        status=IncidentState.diagnosed,
        diagnosis=DiagnosisResult(
            root_cause="bad_version",
            confidence=0.85,
            recommended_action="rollback_deployment",
            reasoning_summary="Bad build.",
            source=DiagnosisSource.fallback,
        ),
    )

    executor = RemediationExecutor(
        policy_engine=mock_policy_engine,
        ansible_runner=mock_ansible_runner,
    )

    attempt = await executor.execute(incident)

    # Must NOT have executed Ansible
    mock_ansible_runner.execute_action.assert_not_called()
    assert incident.status == IncidentState.awaiting_approval
    assert attempt.output == "Remediation paused: awaiting manual human approval."

    # Now grant approval
    incident.approval = ApprovalRecord(
        approved=True,
        approved_by="sre_operator_1",
        approved_at=datetime.now(timezone.utc),
        note="Approved for rollback after manual review",
    )

    # Re-execute after approval
    await executor.execute(incident)
    mock_ansible_runner.execute_action.assert_called_once()
    assert incident.status == IncidentState.verifying


@pytest.mark.asyncio
async def test_blocked_action_raises_policy_denied(mock_policy_engine, mock_ansible_runner):
    """Prohibited action (delete_resource) transitions incident to blocked and raises PolicyDeniedError."""
    incident = Incident(
        id="INC-EXEC-3",
        status=IncidentState.diagnosed,
        diagnosis=DiagnosisResult(
            root_cause="disk_full",
            confidence=0.99,
            recommended_action="delete_resource",
            reasoning_summary="Delete database files.",
            source=DiagnosisSource.ai,
        ),
    )

    executor = RemediationExecutor(
        policy_engine=mock_policy_engine,
        ansible_runner=mock_ansible_runner,
    )

    with pytest.raises(PolicyDeniedError) as exc_info:
        await executor.execute(incident)

    assert exc_info.value.action == "delete_resource"
    assert incident.status == IncidentState.blocked
    mock_ansible_runner.execute_action.assert_not_called()


@pytest.mark.asyncio
async def test_action_registry_enforces_known_playbooks():
    """AnsibleRunner rejects actions that are not registered in the immutable action registry."""
    runner = AnsibleRunner()
    with pytest.raises(RemediationExecutionError):
        await runner.execute_action("arbitrary_bash_script", "payment-api")
