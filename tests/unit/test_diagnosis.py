"""Unit tests for AI diagnosis validation and deterministic fallback."""

from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.core.exceptions import DiagnosisValidationError
from app.diagnosis.engine import DiagnosisEngine
from app.diagnosis.fallback import FallbackDiagnoser
from app.diagnosis.ollama_client import OllamaClient
from app.models.diagnosis import AIDiagnosisOutput, DiagnosisSource
from app.models.incident import Incident, IncidentSeverity, IncidentState, IncidentType


def test_valid_ai_output_schema_is_accepted():
    """Valid AI diagnosis payload must pass Pydantic schema validation."""
    data = {
        "root_cause": "application_process_failure",
        "confidence": 0.86,
        "recommended_action": "restart_container",
        "reasoning_summary": "The container is running but HTTP health check returned 500.",
    }
    validated = AIDiagnosisOutput.model_validate(data)
    assert validated.root_cause == "application_process_failure"
    assert validated.confidence == 0.86
    assert validated.recommended_action == "restart_container"


def test_invalid_action_name_is_rejected():
    """Rogue or dangerous actions from AI (e.g. delete_database, rm_rf) must be rejected."""
    dangerous_actions = ["delete_database", "rm_rf", "execute_shell", "wipe_disk"]

    for action in dangerous_actions:
        data = {
            "root_cause": "disk_error",
            "confidence": 0.99,
            "recommended_action": action,
            "reasoning_summary": "Malicious or unsupported recommendation.",
        }
        with pytest.raises(ValidationError):
            AIDiagnosisOutput.model_validate(data)


def test_invalid_confidence_range_is_rejected():
    """Confidence must strictly be between 0.0 and 1.0."""
    with pytest.raises(ValidationError):
        AIDiagnosisOutput.model_validate({
            "root_cause": "error",
            "confidence": 1.5,
            "recommended_action": "restart_container",
            "reasoning_summary": "Out of range confidence.",
        })


def test_deterministic_fallback_for_unhealthy_container():
    """Fallback diagnosis correctly identifies container failures."""
    incident = Incident(
        id="INC-TEST-1",
        type=IncidentType.container_unhealthy,
        severity=IncidentSeverity.medium,
        target="payment-api",
        status=IncidentState.investigating,
    )
    evidence = {
        "container_status": "running",
        "http_status_code": 500,
        "recent_logs": ["Worker failed"],
    }

    result = FallbackDiagnoser.diagnose(incident, evidence)
    assert result.root_cause == "application_process_failure"
    assert result.recommended_action == "restart_container"
    assert result.source == DiagnosisSource.fallback
    assert result.confidence >= 0.8


def test_deterministic_fallback_for_service_unavailable():
    """Fallback diagnosis correctly identifies service crashes."""
    incident = Incident(
        id="INC-TEST-2",
        type=IncidentType.service_unavailable,
        severity=IncidentSeverity.high,
        target="payment-api",
        status=IncidentState.investigating,
    )
    evidence = {"detected_error": "Connection refused"}

    result = FallbackDiagnoser.diagnose(incident, evidence)
    assert result.root_cause == "service_process_down"
    assert result.recommended_action == "restart_service"
    assert result.source == DiagnosisSource.fallback


def test_deterministic_fallback_for_failed_deployment():
    """Fallback diagnosis correctly recommends rollback for bad deployment."""
    incident = Incident(
        id="INC-TEST-3",
        type=IncidentType.failed_deployment,
        severity=IncidentSeverity.high,
        target="payment-api",
        status=IncidentState.investigating,
    )
    evidence = {}

    result = FallbackDiagnoser.diagnose(incident, evidence)
    assert result.root_cause == "deployment_initialization_error"
    assert result.recommended_action == "rollback_deployment"
    assert result.source == DiagnosisSource.fallback


@pytest.mark.asyncio
async def test_engine_falls_back_when_ollama_unavailable():
    """If Ollama throws an error, engine seamlessly invokes fallback diagnosis."""
    mock_ollama = AsyncMock(spec=OllamaClient)
    mock_ollama.diagnose_incident.side_effect = DiagnosisValidationError("Ollama offline")

    engine = DiagnosisEngine(ollama_client=mock_ollama)
    incident = Incident(
        id="INC-TEST-4",
        type=IncidentType.container_unhealthy,
        severity=IncidentSeverity.medium,
        target="payment-api",
        status=IncidentState.investigating,
    )

    result = await engine.diagnose(incident, {"http_status_code": 500})
    assert result.source == DiagnosisSource.fallback
    assert result.recommended_action == "restart_container"
