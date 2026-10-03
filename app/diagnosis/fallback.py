"""Deterministic fallback diagnostic engine."""

from typing import Any, Dict

from app.core.logging import get_logger
from app.models.diagnosis import DiagnosisResult, DiagnosisSource
from app.models.incident import Incident, IncidentType

logger = get_logger("diagnosis.fallback")


class FallbackDiagnoser:
    """Provides deterministic, rule-based incident diagnosis when Ollama is unavailable."""

    @staticmethod
    def diagnose(incident: Incident, evidence: Dict[str, Any]) -> DiagnosisResult:
        """Evaluate incident and evidence to produce deterministic diagnosis."""
        incident_type = incident.type
        http_status = evidence.get("http_status_code")
        error_msg = evidence.get("detected_error", "") or ""

        logger.info(
            f"Executing deterministic fallback diagnosis for Incident {incident.id} (Type: {incident_type})"
        )

        if incident_type == IncidentType.container_unhealthy or http_status == 500:
            return DiagnosisResult(
                root_cause="application_process_failure",
                confidence=0.88,
                recommended_action="restart_container",
                reasoning_summary=(
                    "Target container is running but HTTP health endpoint returned internal server error (500). "
                    "Restarting container resolves stuck worker process."
                ),
                source=DiagnosisSource.fallback,
            )

        if incident_type == IncidentType.service_unavailable or "Connection refused" in error_msg:
            return DiagnosisResult(
                root_cause="service_process_down",
                confidence=0.85,
                recommended_action="restart_service",
                reasoning_summary=(
                    "Target service connection refused or process crashed; attempting service restart."
                ),
                source=DiagnosisSource.fallback,
            )

        if incident_type == IncidentType.failed_deployment:
            return DiagnosisResult(
                root_cause="deployment_initialization_error",
                confidence=0.82,
                recommended_action="rollback_deployment",
                reasoning_summary=(
                    "Application deployment failed initial health checks; rollback to previous stable release required."
                ),
                source=DiagnosisSource.fallback,
            )

        if incident_type == IncidentType.failed_health_check or "timed out" in error_msg.lower():
            return DiagnosisResult(
                root_cause="health_check_timeout",
                confidence=0.78,
                recommended_action="restart_container",
                reasoning_summary=(
                    "Health endpoint timed out; container may be deadlocked or hanging. Restart recommended."
                ),
                source=DiagnosisSource.fallback,
            )

        # Default fallback: safe escalation
        return DiagnosisResult(
            root_cause="unclassified_operational_anomaly",
            confidence=0.60,
            recommended_action="escalate",
            reasoning_summary=(
                "Unrecognized operational pattern or unrecoverable container state. Escalating to human operator."
            ),
            source=DiagnosisSource.fallback,
        )
