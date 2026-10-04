"""End-to-end integration tests for the autonomous remediation pipeline and API."""

from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient

from app.audit.logger import AuditLogger
from app.detection.detector import Detector
from app.detection.health_checker import HealthChecker
from app.diagnosis.engine import DiagnosisEngine
from app.diagnosis.ollama_client import OllamaClient
from app.evidence.collector import EvidenceCollector
from app.main import app
from app.models.diagnosis import AIDiagnosisOutput, DiagnosisResult, DiagnosisSource
from app.models.incident import Incident, IncidentSeverity, IncidentState, IncidentType
from app.models.remediation import RiskLevel
from app.orchestrator import IncidentOrchestrator
from app.policy.engine import PolicyEngine
from app.policy.models import PolicyDocument, PolicyRule
from app.remediation.ansible_runner import AnsibleRunner
from app.remediation.executor import RemediationExecutor
from app.verification.verifier import Verifier


@pytest.fixture
def mock_pipeline_components():
    """Setup orchestrator with controlled mock components for deterministic pipeline testing."""
    # Policy document
    policy_doc = PolicyDocument(
        policies={
            "restart_container": PolicyRule(
                risk=RiskLevel.low,
                auto_execute=True,
                requires_approval=False,
                max_attempts=3,
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
    policy_engine = PolicyEngine(policy_doc=policy_doc)

    mock_health = AsyncMock(spec=HealthChecker)
    detector = Detector(health_checker=mock_health)
    evidence_collector = EvidenceCollector(health_checker=mock_health)

    mock_ollama = AsyncMock(spec=OllamaClient)
    diagnosis_engine = DiagnosisEngine(ollama_client=mock_ollama)

    mock_ansible = AsyncMock(spec=AnsibleRunner)
    mock_ansible.get_playbook_for_action.side_effect = lambda a: f"{a}.yml" if a == "restart_container" else None
    mock_ansible.execute_action.return_value = {
        "success": True,
        "action": "restart_container",
        "playbook": "restart_container.yml",
        "returncode": 0,
        "duration_seconds": 1.0,
        "stdout": "Restarted container",
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
async def test_full_pipeline_happy_path(mock_pipeline_components):
    """Scenario 1: Unhealthy container -> Detected -> Diagnosed -> Policy -> Remediation -> Verified -> Resolved."""
    comps = mock_pipeline_components
    orchestrator: IncidentOrchestrator = comps["orchestrator"]
    mock_health = comps["mock_health"]
    mock_ollama = comps["mock_ollama"]

    # 1. Detection probe reports unhealthy (500)
    mock_health.check_http_health.side_effect = [
        {"healthy": False, "status_code": 500, "error": "HTTP 500"},  # Detection
        {"healthy": False, "status_code": 500, "error": "HTTP 500"},  # Evidence
        {"healthy": True, "status_code": 200, "latency_ms": 10.0},     # Verification
    ]

    # AI returns valid diagnosis
    mock_ollama.diagnose_incident.return_value = AIDiagnosisOutput(
        root_cause="application_process_failure",
        confidence=0.92,
        recommended_action="restart_container",
        reasoning_summary="Worker deadlocked; restart container to clear memory pool.",
    )

    incident = await orchestrator.detect_and_register()
    assert incident is not None
    assert incident.status == IncidentState.detected

    # Run pipeline
    resolved = await orchestrator.run_pipeline(incident)

    assert resolved.status == IncidentState.resolved
    assert resolved.attempt_count == 1
    assert resolved.diagnosis.recommended_action == "restart_container"
    assert resolved.policy_decision.allowed is True

    # Audit recorded
    audits = comps["audit_logger"].get_entries_for_incident(resolved.id)
    assert len(audits) >= 1
    assert audits[-1].final_status == "resolved"


@pytest.mark.asyncio
async def test_full_pipeline_repeated_failure_escalates(mock_pipeline_components):
    """Scenario 2: Persistent failure -> Retries up to max_attempts (3) -> Escalates."""
    comps = mock_pipeline_components
    orchestrator: IncidentOrchestrator = comps["orchestrator"]
    mock_health = comps["mock_health"]
    mock_ollama = comps["mock_ollama"]

    # Target remains permanently unhealthy across all verification attempts
    mock_health.check_http_health.return_value = {
        "healthy": False,
        "status_code": 500,
        "error": "Persistent internal server error",
    }

    mock_ollama.diagnose_incident.return_value = AIDiagnosisOutput(
        root_cause="application_process_failure",
        confidence=0.85,
        recommended_action="restart_container",
        reasoning_summary="Attempting restart.",
    )

    incident = Incident(
        id="INC-RETRY-1",
        type=IncidentType.container_unhealthy,
        severity=IncidentSeverity.medium,
        target="payment-api",
        status=IncidentState.detected,
        max_attempts=3,
    )

    escalated = await orchestrator.run_pipeline(incident)

    assert escalated.status == IncidentState.escalated
    assert escalated.attempt_count == 3
    assert len(escalated.remediation_history) == 3


@pytest.mark.asyncio
async def test_full_pipeline_repeated_ansible_execution_failure_escalates(mock_pipeline_components):
    """When Ansible execution itself repeatedly fails, pipeline bounded retry halts and escalates."""
    comps = mock_pipeline_components
    orchestrator: IncidentOrchestrator = comps["orchestrator"]
    mock_ansible = comps["mock_ansible"]
    mock_ollama = comps["mock_ollama"]

    # Ansible execution fails on every attempt
    mock_ansible.execute_action.return_value = {
        "success": False,
        "action": "restart_container",
        "playbook": "restart_container.yml",
        "returncode": 1,
        "duration_seconds": 0.5,
        "stdout": "",
        "stderr": "docker restart payment-api failed: container not found",
    }

    mock_ollama.diagnose_incident.return_value = AIDiagnosisOutput(
        root_cause="application_process_failure",
        confidence=0.85,
        recommended_action="restart_container",
        reasoning_summary="Attempting restart.",
    )

    incident = Incident(
        id="INC-EXEC-FAIL-1",
        type=IncidentType.container_unhealthy,
        severity=IncidentSeverity.medium,
        target="payment-api",
        status=IncidentState.detected,
        max_attempts=3,
    )

    escalated = await orchestrator.run_pipeline(incident)

    assert escalated.status == IncidentState.escalated
    assert escalated.attempt_count == 3
    assert len(escalated.remediation_history) == 3

    audits = comps["audit_logger"].get_entries_for_incident(escalated.id)
    assert len(audits) >= 1
    assert audits[-1].final_status == "escalated"
    assert audits[-1].outcome == "REMEDIATION_FAILED"


@pytest.mark.asyncio
async def test_full_pipeline_prohibited_action_is_blocked(mock_pipeline_components):
    """Scenario 3: AI recommends delete_resource -> Policy blocks it -> Blocked without Ansible execution."""
    comps = mock_pipeline_components
    orchestrator: IncidentOrchestrator = comps["orchestrator"]
    mock_health = comps["mock_health"]
    mock_ansible = comps["mock_ansible"]

    mock_health.check_http_health.return_value = {
        "healthy": False,
        "status_code": 500,
        "error": "Corrupted filesystem",
    }

    # Simulate rogue diagnosis recommending destructive delete_resource
    # Note: AI diagnosis engine will bypass Ollama validation if simulated as raw DiagnosisResult
    incident = Incident(
        id="INC-ROGUE-1",
        type=IncidentType.container_unhealthy,
        severity=IncidentSeverity.critical,
        target="payment-api",
        status=IncidentState.diagnosed,
        diagnosis=DiagnosisResult(
            root_cause="corrupted_state",
            confidence=0.99,
            recommended_action="delete_resource",
            reasoning_summary="Destroy target container.",
            source=DiagnosisSource.ai,
        ),
    )

    blocked = await orchestrator.run_pipeline(incident)

    assert blocked.status == IncidentState.blocked
    assert blocked.policy_decision.blocked is True
    assert blocked.policy_decision.allowed is False
    mock_ansible.execute_action.assert_not_called()

    # Verify structured audit trail accurately records blocked outcome without execution
    audits = comps["audit_logger"].get_entries_for_incident(blocked.id)
    assert len(audits) >= 1
    assert audits[-1].recommended_action == "delete_resource"
    assert audits[-1].policy_decision == "blocked"
    assert audits[-1].execution_status == "not_executed"
    assert audits[-1].verification_status == "not_executed"
    assert audits[-1].outcome == "BLOCKED_BY_POLICY"


@pytest.mark.asyncio
async def test_full_pipeline_ollama_offline_uses_fallback(mock_pipeline_components):
    """Scenario 4: Ollama is unreachable -> Fallback diagnosis automatically selected -> Recovery proceeds."""
    comps = mock_pipeline_components
    orchestrator: IncidentOrchestrator = comps["orchestrator"]
    mock_health = comps["mock_health"]
    mock_ollama = comps["mock_ollama"]

    # Ollama is down (connection error)
    mock_ollama.diagnose_incident.side_effect = Exception("Ollama connection refused")

    # Health transitions: 500 -> 200
    mock_health.check_http_health.side_effect = [
        {"healthy": False, "status_code": 500, "error": "HTTP 500"},  # Evidence
        {"healthy": True, "status_code": 200, "latency_ms": 12.0},     # Verification
    ]

    incident = Incident(
        id="INC-FALLBACK-1",
        type=IncidentType.container_unhealthy,
        severity=IncidentSeverity.medium,
        target="payment-api",
        status=IncidentState.investigating,
    )

    recovered = await orchestrator.run_pipeline(incident)

    assert recovered.status == IncidentState.resolved
    assert recovered.diagnosis.source == DiagnosisSource.fallback
    assert recovered.diagnosis.recommended_action == "restart_container"


def test_api_endpoints_integration():
    """Verify HTTP API contracts using FastAPI TestClient."""
    client = TestClient(app)

    # 1. Health endpoints
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "healthy"

    res_diag = client.get("/api/v1/health")
    assert res_diag.status_code == 200
    assert "components" in res_diag.json()

    # 2. Incidents endpoints
    create_res = client.post(
        "/api/v1/incidents",
        json={"type": "container_unhealthy", "severity": "medium", "target": "payment-api"},
    )
    assert create_res.status_code == 201
    inc_data = create_res.json()
    inc_id = inc_data["id"]

    get_res = client.get(f"/api/v1/incidents/{inc_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == inc_id

    # 3. Metrics endpoints
    metrics_res = client.get("/metrics")
    assert metrics_res.status_code == 200
    assert "opspilot_incidents_total" in metrics_res.text

    kpi_res = client.get("/api/v1/metrics/kpi")
    assert kpi_res.status_code == 200
    assert "kpis" in kpi_res.json()
    assert "mttr" in kpi_res.json()["formulas"]

    # 4. Dashboard and audit endpoints
    dash_res = client.get("/dashboard")
    assert dash_res.status_code == 200
    assert "OpsPilot" in dash_res.text
    assert "text/html" in dash_res.headers.get("content-type", "")

    audit_res = client.get("/api/v1/audit")
    assert audit_res.status_code == 200
    assert "entries" in audit_res.json()

