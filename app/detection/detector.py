"""Incident detection engine."""

import itertools
from typing import Optional

from app.core.config import get_settings
from app.core.logging import get_logger
from app.detection.health_checker import HealthChecker
from app.models.incident import Incident, IncidentSeverity, IncidentState, IncidentType

logger = get_logger("detection.detector")

# Simple thread-safe counter for readable incident IDs
_counter = itertools.count(1)


def generate_incident_id() -> str:
    """Generate sequential incident ID like INC-0001."""
    return f"INC-{next(_counter):04d}"


class Detector:
    """Detects service and container anomalies, generating structured incidents."""

    def __init__(
        self,
        health_checker: Optional[HealthChecker] = None,
        target_name: Optional[str] = None,
    ):
        settings = get_settings()
        self.health_checker = health_checker or HealthChecker()
        self.target_name = target_name or settings.target_service_name

    async def detect_anomaly(self) -> Optional[Incident]:
        """Check target health and construct an Incident if an anomaly is detected."""
        health = await self.health_checker.check_http_health()

        if health["healthy"]:
            logger.debug(f"Target '{self.target_name}' is healthy.")
            return None

        # Determine incident type and severity
        error_msg = health.get("error") or ""
        if "Connection refused" in error_msg:
            inc_type = IncidentType.service_unavailable
            severity = IncidentSeverity.high
        elif health.get("status_code") == 500:
            inc_type = IncidentType.container_unhealthy
            severity = IncidentSeverity.medium
        else:
            inc_type = IncidentType.failed_health_check
            severity = IncidentSeverity.medium

        incident_id = generate_incident_id()
        incident = Incident(
            id=incident_id,
            type=inc_type,
            severity=severity,
            target=self.target_name,
            status=IncidentState.detected,
            evidence={
                "health_result": health,
                "detected_error": error_msg,
            },
        )

        logger.warning(
            f"Anomaly detected! Created Incident {incident.id} "
            f"(Type: {incident.type.value}, Target: {incident.target}, Severity: {incident.severity.value})"
        )
        return incident
