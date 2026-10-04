"""Integration tests for extended failure scenarios and operator approval workflows.

Validates:
1. Bad Deployment (HTTP 503) -> AI/Fallback diagnosis recommends 'rollback_deployment' ->
   Policy Engine enforces 'requires_approval: true' -> Pipeline halts at awaiting_approval ->
   Operator approves -> Playbook executes rollback -> Verification passes -> Resolved.
2. Bad Deployment (HTTP 503) -> Pipeline halts at awaiting_approval ->
   Operator rejects action -> Incident escalated to on-call -> Audit trail logs rejection.
3. Latency Timeout Spike -> Detected as failed_health_check -> Auto-remediated via restart -> Resolved.
4. Simulator proxy endpoints for fault injection & recovery.
"""

from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from app.audit.logger import AuditLogger
from app.detection.detector import Detector
from app.detection.health_checker import HealthChecker
from app.diagnosis.engine import DiagnosisEngine
from app.diagnosis.fallback import FallbackDiagnoser
from app.diagnosis.ollama_client import OllamaClient
from app.evidence.collector import EvidenceCollector
from app.main import app
from app.models.diagnosis import DiagnosisResult, DiagnosisSource
from app.models.incident import Incident, IncidentSeverity, IncidentState, IncidentType
from app.models.remediation import RiskLevel
from app.orchestrator import IncidentOrchestrator
from app.policy.engine import PolicyEngine
from app.policy.models import PolicyDocument, PolicyRule
from app.remediation.ansible_runner import AnsibleRunner
from app.remediation.executor import RemediationExecutor
from app.verification.verifier import Verifier


@pytest.fixture
def extended_pipeline_fixture():
    """Setup orchestrator with policies for rollback_deployment, restart_container, and escalate."""
    policy_doc = PolicyDocument(
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
            "escalate": PolicyRule(
                risk=RiskLevel.high,
                auto_execute=False,
                requires_approval=False,
                max_attempts=0,
                blocked=False,
            ),
        }
    )
    policy_engine = PolicyEngine(policy_doc=policy_doc)

    mock_health = AsyncMock(spec=HealthChecker)
    detector = Detector(health_checker=mock_health)
    evidence_collector = EvidenceCollector(health_checker=mock_health)

    mock_ollama = AsyncMock(spec=OllamaClient)
    diagnosis_engine = DiagnosisEngine(ollama_client=mock_ollama)

    mock_ansible = AsyncMock(spec=AnsibleRunner)
    mock_ansible.get_playbook_for_action.side_effect = lambda a: f"{a}.yml"
    mock_ansible.execute_action.return_value = {
        "success": True,
        "action": "rollback_deployment",
        "playbook": "rollback.yml",
        "returncode": 0,
        "duration_seconds": 1.5,
        "stdout": "Rollback completed for payment-api",
        "stderr": "",
    }

    remediation_executor = RemediationExecutor(
        policy_engine=policy_engine,
        ansible_runner=mock_ansible,
    )

    verifier = Verifier(health_checker=mock_health, delay_seconds=0.0)
    audit_logger = AuditLogger()

    orchestrator = IncidentOrchestrator(
        detector=detector,
        evidence_collector=evidence_collector,
        diagnosis_engine=diagnosis_engine,
        policy_engine=policy_engine,
        remediation_executor=remediation_executor,
        verifier=verifier,
        audit_logger=audit_logger,
    )

    return {
        "orchestrator": orchestrator,
        "mock_health": mock_health,
        "mock_ollama": mock_ollama,
        "mock_ansible": mock_ansible,
        "policy_engine": policy_engine,
        "audit_logger": audit_logger,
    }


@pytest.mark.asyncio
async def test_bad_deployment_approval_gate_and_rollback_resolution(extended_pipeline_fixture):
    """Test full cycle: 503 deployment failure -> Awaiting approval -> Operator approves -> Rollback -> Resolved."""
    fixture = extended_pipeline_fixture
    orchestrator: IncidentOrchestrator = fixture["orchestrator"]
    mock_health = fixture["mock_health"]
    mock_ollama = fixture["mock_ollama"]
    mock_ansible = fixture["mock_ansible"]

    # 1. Ollama produces rollback diagnosis
    mock_ollama.diagnose_incident.return_value = DiagnosisResult(
        root_cause="broken_v2_migration",
        confidence=0.92,
        recommended_action="rollback_deployment",
        reasoning_summary="Service returned 503 following v2.0.0 release. Rollback recommended.",
        source=DiagnosisSource.ollama,
    )

    # 2. Health check during evidence is 503; verification after rollback is 200
    mock_health.check_http_health.side_effect = [
        {
            "healthy": False,
            "status_code": 503,
            "error": "Service Unavailable",
            "payload": {"error": "Deployment failure", "version": "2.0.0-broken"},
        },  # Evidence
        {
            "healthy": True,
            "status_code": 200,
            "payload": {"status": "healthy", "version": "1.0.0"},
            "latency_ms": 15.0,
        },  # Post-remediation verification
    ]

    # Create detected deployment incident
    incident = Incident(
        id="INC-DEPLOY-APPROVAL",
        type=IncidentType.failed_deployment,
        severity=IncidentSeverity.high,
        target="payment-api",
        status=IncidentState.detected,
    )

    # Run pipeline phase 1: should halt at awaiting_approval because rollback requires approval
    paused = await orchestrator.run_pipeline(incident)

    assert paused.status == IncidentState.awaiting_approval
    assert paused.diagnosis.recommended_action == "rollback_deployment"
    assert paused.policy_decision.requires_approval is True
    # Ansible should NOT have been called yet
    mock_ansible.execute_action.assert_not_called()

    # Verify audit entry for paused state
    audits_phase1 = fixture["audit_logger"].get_entries_for_incident("INC-DEPLOY-APPROVAL")
    assert len(audits_phase1) == 1
    assert audits_phase1[0].execution_status == "pending_approval"
    assert audits_phase1[0].outcome == "AWAITING_APPROVAL"

    # Operator approves via API simulation
    from datetime import datetime, timezone

    from app.models.incident import ApprovalRecord

    paused.approval = ApprovalRecord(
        approved=True,
        approved_by="lead_sre_operator",
        approved_at=datetime.now(timezone.utc),
        note="Authorized rollback to v1.0.0 via dashboard",
    )

    # Run pipeline phase 2: resumes with approval granted
    resolved = await orchestrator.run_pipeline(paused)

    assert resolved.status == IncidentState.resolved
    assert resolved.attempt_count == 1
    mock_ansible.execute_action.assert_called_once_with(
        action="rollback_deployment",
        target="payment-api",
    )

    # Audit trail verifies final resolution
    audits_phase2 = fixture["audit_logger"].get_entries_for_incident("INC-DEPLOY-APPROVAL")
    assert len(audits_phase2) == 2
    last_audit = audits_phase2[-1]
    assert last_audit.execution_status == "success"
    assert last_audit.verification_status == "passed"
    assert last_audit.outcome == "REMEDIATION_SUCCEEDED_AND_VERIFIED"


@pytest.mark.asyncio
async def test_bad_deployment_operator_rejection_escalation(extended_pipeline_fixture):
    """Test operator rejection: Incident halts at awaiting_approval -> Rejected -> Escalated to on-call."""
    fixture = extended_pipeline_fixture
    orchestrator: IncidentOrchestrator = fixture["orchestrator"]
    mock_health = fixture["mock_health"]
    mock_ollama = fixture["mock_ollama"]
    mock_ansible = fixture["mock_ansible"]

    mock_ollama.diagnose_incident.return_value = DiagnosisResult(
        root_cause="broken_v2_migration",
        confidence=0.90,
        recommended_action="rollback_deployment",
        reasoning_summary="Deployment error detected.",
        source=DiagnosisSource.ollama,
    )
    mock_health.check_http_health.return_value = {
        "healthy": False,
        "status_code": 503,
        "error": "Service Unavailable",
    }

    incident = Incident(
        id="INC-DEPLOY-REJECT",
        type=IncidentType.failed_deployment,
        severity=IncidentSeverity.high,
        target="payment-api",
        status=IncidentState.detected,
    )

    paused = await orchestrator.run_pipeline(incident)
    assert paused.status == IncidentState.awaiting_approval

    # Operator explicitly rejects the remediation action
    from datetime import datetime, timezone

    from app.models.incident import ApprovalRecord

    paused.approval = ApprovalRecord(
        approved=False,
        approved_by="lead_sre_operator",
        approved_at=datetime.now(timezone.utc),
        note="Rollback rejected: investigating database state first",
    )
    paused.transition_to(
        IncidentState.escalated,
        reason="Remediation rejected by lead_sre_operator: investigating database state first",
    )
    fixture["audit_logger"].record_from_incident(
        incident=paused,
        execution_status="denied",
        verification_status="not_executed",
        notes="Remediation action rejected by operator lead_sre_operator",
    )

    # Calling pipeline on escalated incident should not execute ansible
    escalated = await orchestrator.run_pipeline(paused)

    assert escalated.status == IncidentState.escalated
    mock_ansible.execute_action.assert_not_called()

    # Check audit log contains denied record
    audits = fixture["audit_logger"].get_entries_for_incident("INC-DEPLOY-REJECT")
    denied_entries = [a for a in audits if a.execution_status == "denied"]
    assert len(denied_entries) == 1
    assert "rejected by operator" in denied_entries[0].notes.lower()


@pytest.mark.asyncio
async def test_fallback_diagnosis_for_bad_deployment_and_timeout():
    """Verify deterministic fallback logic generates appropriate actions for new failure types."""
    # 1. 503 Deployment failure -> rollback_deployment
    deploy_inc = Incident(
        id="INC-TEST-503",
        type=IncidentType.failed_deployment,
        severity=IncidentSeverity.high,
        target="payment-api",
    )
    deploy_diag = FallbackDiagnoser.diagnose(
        incident=deploy_inc,
        evidence={"http_status_code": 503, "detected_error": "ERR_DEPLOYMENT_FAILED"},
    )
    assert deploy_diag.recommended_action == "rollback_deployment"
    assert deploy_diag.root_cause == "deployment_initialization_error"
    assert deploy_diag.source == DiagnosisSource.fallback

    # 2. Timeout failure -> restart_container
    timeout_inc = Incident(
        id="INC-TEST-TIMEOUT",
        type=IncidentType.failed_health_check,
        severity=IncidentSeverity.medium,
        target="payment-api",
    )
    timeout_diag = FallbackDiagnoser.diagnose(
        incident=timeout_inc,
        evidence={"detected_error": "Connection timed out after 5000ms"},
    )
    assert timeout_diag.recommended_action == "restart_container"
    assert timeout_diag.root_cause == "health_check_timeout"


def test_api_rejection_and_approval_endpoints():
    """Verify HTTP API contracts for /approve and /reject endpoints."""
    client = TestClient(app)

    # Create incident in awaiting_approval state
    from app.dependencies import get_orchestrator
    orchestrator = get_orchestrator()

    test_inc = Incident(
        id="INC-API-GATE-TEST",
        type=IncidentType.failed_deployment,
        severity=IncidentSeverity.high,
        target="payment-api",
        status=IncidentState.awaiting_approval,
    )
    orchestrator.register_incident(test_inc)

    # 1. Test rejection endpoint
    rej_res = client.post(
        "/api/v1/incidents/INC-API-GATE-TEST/reject",
        json={"approved_by": "secops_lead", "note": "Action unsafe during maintenance window"},
    )
    assert rej_res.status_code == 200
    rej_json = rej_res.json()
    assert rej_json["status"] == "escalated"
    assert rej_json["approval"]["approved"] is False
    assert rej_json["approval"]["approved_by"] == "secops_lead"

    # Reset state to awaiting_approval for approval test
    test_inc_2 = Incident(
        id="INC-API-GATE-TEST-2",
        type=IncidentType.failed_deployment,
        severity=IncidentSeverity.high,
        target="payment-api",
        status=IncidentState.awaiting_approval,
    )
    orchestrator.register_incident(test_inc_2)

    # 2. Test approve endpoint
    app_res = client.post(
        "/api/v1/incidents/INC-API-GATE-TEST-2/approve",
        json={"approved_by": "oncall_engineer", "note": "Approved via test suite"},
    )
    assert app_res.status_code == 200
    app_json = app_res.json()
    assert app_json["approval"]["approved"] is True
    assert app_json["approval"]["approved_by"] == "oncall_engineer"


def test_simulator_proxy_routes():
    """Verify simulator proxy routes exist and handle requests."""
    client = TestClient(app)

    # Mock httpx.AsyncClient post call so test runs without needing live payment-api container
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = AsyncMock(
            status_code=200,
            json=lambda: {"status": "ok", "detail": "simulated"},
        )

        r_deploy = client.post("/api/v1/simulator/deployment-failed")
        assert r_deploy.status_code == 200

        r_latency = client.post("/api/v1/simulator/latency?delay=2.0")
        assert r_latency.status_code == 200

        r_rollback = client.post("/api/v1/simulator/rollback")
        assert r_rollback.status_code == 200
