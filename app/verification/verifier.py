"""Independent Post-Remediation Verification Engine."""

import asyncio
from typing import Any, Dict, Optional

from app.core.config import get_settings
from app.core.logging import get_logger
from app.detection.health_checker import HealthChecker
from app.models.incident import Incident, IncidentState
from app.models.remediation import VerificationStatus

logger = get_logger("verification.verifier")


class Verifier:
    """Verifies infrastructure recovery independently of AI model decisions."""

    def __init__(
        self,
        health_checker: Optional[HealthChecker] = None,
        delay_seconds: Optional[float] = None,
    ):
        settings = get_settings()
        self.health_checker = health_checker or HealthChecker()
        self.delay_seconds = (
            delay_seconds if delay_seconds is not None else settings.verification_delay_seconds
        )

    async def verify(self, incident: Incident) -> Dict[str, Any]:
        """Perform verification checks against target service to confirm recovery."""
        if self.delay_seconds > 0:
            logger.info(f"Waiting {self.delay_seconds}s for target service initialization...")
            await asyncio.sleep(self.delay_seconds)

        # Ensure incident is in verifying state if arriving from remediating
        if incident.status == IncidentState.remediating:
            incident.transition_to(IncidentState.verifying)

        logger.info(f"Verifying target health for Incident {incident.id}...")
        check_result = await self.health_checker.check_http_health()
        passed = check_result.get("healthy", False)

        # Update last attempt in history if available
        if incident.remediation_history:
            last_attempt = incident.remediation_history[-1]
            last_attempt.verification_status = (
                VerificationStatus.passed if passed else VerificationStatus.failed
            )

        if passed:
            logger.info(
                f"Verification PASSED for Incident {incident.id} (HTTP {check_result.get('status_code')})"
            )
            incident.transition_to(
                IncidentState.resolved,
                reason="Target service passed health verification checks",
            )
            return {
                "passed": True,
                "status_code": check_result.get("status_code"),
                "latency_ms": check_result.get("latency_ms"),
                "message": "Service successfully recovered and is healthy.",
            }

        # Verification failed
        logger.warning(
            f"Verification FAILED for Incident {incident.id}: {check_result.get('error')}"
        )

        if incident.attempt_count < incident.max_attempts:
            logger.info(
                f"Incident {incident.id} retry permitted ({incident.attempt_count}/{incident.max_attempts}). "
                "Transitioning state to 'remediating' for next attempt."
            )
            incident.transition_to(
                IncidentState.remediating,
                reason=f"Verification failed; retrying ({incident.attempt_count}/{incident.max_attempts})",
            )
        else:
            logger.warning(
                f"Incident {incident.id} reached maximum remediation attempts ({incident.max_attempts}). "
                "Transitioning state to 'escalated'."
            )
            incident.transition_to(
                IncidentState.escalated,
                reason=f"Verification failed after max attempts ({incident.max_attempts})",
            )

        return {
            "passed": False,
            "status_code": check_result.get("status_code"),
            "latency_ms": check_result.get("latency_ms"),
            "error": check_result.get("error", "Verification failed"),
        }
