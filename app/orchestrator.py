"""End-to-end incident orchestration pipeline."""

import time
from typing import Dict, List, Optional

from app.audit.logger import AuditLogger
from app.core.exceptions import PolicyDeniedError
from app.core.logging import get_logger
from app.core.metrics import (
    ACTIVE_INCIDENTS,
    INCIDENTS_ESCALATED_TOTAL,
    INCIDENTS_RESOLVED_TOTAL,
    INCIDENTS_TOTAL,
    REMEDIATION_ATTEMPTS_TOTAL,
    REMEDIATION_DURATION_SECONDS,
    REMEDIATION_FAILURE_TOTAL,
    REMEDIATION_SUCCESS_TOTAL,
    VERIFICATION_TOTAL,
    kpi_tracker,
)
from app.detection.detector import Detector
from app.diagnosis.engine import DiagnosisEngine
from app.evidence.collector import EvidenceCollector
from app.models.incident import Incident, IncidentState
from app.models.remediation import RemediationStatus
from app.policy.engine import PolicyEngine
from app.remediation.executor import RemediationExecutor
from app.verification.verifier import Verifier

logger = get_logger("orchestrator")


class IncidentOrchestrator:
    """Coordinates the full autonomous remediation pipeline:

    Detect -> Evidence -> Diagnose -> Policy -> Remediate -> Verify -> Resolve/Escalate
    """

    def __init__(
        self,
        detector: Optional[Detector] = None,
        evidence_collector: Optional[EvidenceCollector] = None,
        diagnosis_engine: Optional[DiagnosisEngine] = None,
        policy_engine: Optional[PolicyEngine] = None,
        remediation_executor: Optional[RemediationExecutor] = None,
        verifier: Optional[Verifier] = None,
        audit_logger: Optional[AuditLogger] = None,
    ):
        self.detector = detector or Detector()
        self.evidence_collector = evidence_collector or EvidenceCollector()
        self.diagnosis_engine = diagnosis_engine or DiagnosisEngine()
        self.policy_engine = policy_engine or PolicyEngine()
        self.remediation_executor = remediation_executor or RemediationExecutor(
            policy_engine=self.policy_engine
        )
        self.verifier = verifier or Verifier()
        self.audit_logger = audit_logger or AuditLogger()

        # In-memory incident repository
        self.incidents: Dict[str, Incident] = {}

    def get_incident(self, incident_id: str) -> Optional[Incident]:
        """Look up incident by ID."""
        return self.incidents.get(incident_id)

    def list_incidents(self) -> List[Incident]:
        """Return all tracked incidents sorted by creation date."""
        return sorted(self.incidents.values(), key=lambda inc: inc.created_at, reverse=True)

    def register_incident(self, incident: Incident) -> Incident:
        """Register a new incident into memory and metrics."""
        self.incidents[incident.id] = incident
        INCIDENTS_TOTAL.labels(
            type=incident.type.value,
            severity=incident.severity.value,
            target=incident.target,
        ).inc()
        ACTIVE_INCIDENTS.inc()
        kpi_tracker.record_incident_created()
        return incident

    async def detect_and_register(self) -> Optional[Incident]:
        """Probe target and create incident if anomaly detected."""
        incident = await self.detector.detect_anomaly()
        if incident:
            return self.register_incident(incident)
        return None

    async def run_pipeline(
        self,
        incident: Incident,
        max_retries: Optional[int] = None,
    ) -> Incident:
        """Execute complete autonomous remediation pipeline for an incident."""
        start_time = time.perf_counter()
        logger.info(f"--- Starting Autonomous Pipeline for Incident {incident.id} ---")

        if max_retries is not None:
            incident.max_attempts = max_retries

        # Ensure registered
        if incident.id not in self.incidents:
            self.register_incident(incident)

        try:
            # 1. Evidence Collection
            if incident.status == IncidentState.detected:
                incident.transition_to(IncidentState.investigating)
                logger.info(f"[{incident.id}] Collecting diagnostic evidence...")
                evidence = await self.evidence_collector.collect_evidence(
                    target_name=incident.target,
                    incident_type=incident.type.value,
                )
                incident.evidence = evidence

            # 2. Diagnosis (AI with deterministic fallback)
            if incident.status == IncidentState.investigating:
                logger.info(f"[{incident.id}] Performing diagnosis (Ollama / Fallback)...")
                diagnosis = await self.diagnosis_engine.diagnose(
                    incident=incident,
                    evidence=incident.evidence or {},
                )
                incident.diagnosis = diagnosis
                incident.transition_to(IncidentState.diagnosed)
                logger.info(
                    f"[{incident.id}] Diagnosed: RootCause='{diagnosis.root_cause}', "
                    f"Action='{diagnosis.recommended_action}' (Source: {diagnosis.source.value})"
                )

            # 3. Policy Check & Remediation Execution
            rec_action = incident.diagnosis.recommended_action if incident.diagnosis else "no_action"

            # Check Policy upfront
            decision = self.policy_engine.evaluate(
                action=rec_action,
                current_attempts=incident.attempt_count,
            )
            incident.policy_decision = decision

            # Blocked action handling
            if decision.blocked:
                incident.transition_to(IncidentState.blocked, reason=decision.reason or "Blocked by policy")
                self.audit_logger.record_from_incident(
                    incident=incident,
                    execution_status="blocked",
                    verification_status="failed",
                    notes=f"Prohibited action '{rec_action}' strictly blocked by policy.",
                )
                INCIDENTS_ESCALATED_TOTAL.labels(target=incident.target, reason="policy_blocked").inc()
                ACTIVE_INCIDENTS.dec()
                return incident

            # Approval requirement handling
            if decision.requires_approval and not (incident.approval and incident.approval.approved):
                incident.transition_to(IncidentState.awaiting_approval, reason="Action requires human approval")
                self.audit_logger.record_from_incident(
                    incident=incident,
                    execution_status="pending_approval",
                    verification_status="pending",
                    notes=f"Action '{rec_action}' paused awaiting manual operator approval.",
                )
                kpi_tracker.record_manual_intervention()
                return incident

            # Bounded Remediation & Verification Loop
            while incident.status in {
                IncidentState.diagnosed,
                IncidentState.awaiting_approval,
                IncidentState.remediating,
                IncidentState.verifying,
            }:
                # Execute remediation attempt
                try:
                    attempt = await self.remediation_executor.execute(incident=incident)
                except PolicyDeniedError as e:
                    self.audit_logger.record_from_incident(
                        incident=incident,
                        execution_status="denied",
                        verification_status="failed",
                        notes=f"Policy denied execution: {e.reason}",
                    )
                    ACTIVE_INCIDENTS.dec()
                    return incident

                # Update execution metrics
                REMEDIATION_ATTEMPTS_TOTAL.labels(action=attempt.action, target=incident.target).inc()
                if attempt.status == RemediationStatus.success:
                    REMEDIATION_SUCCESS_TOTAL.labels(action=attempt.action, target=incident.target).inc()
                    REMEDIATION_DURATION_SECONDS.labels(action=attempt.action).observe(
                        attempt.duration_seconds or 0.0
                    )
                else:
                    REMEDIATION_FAILURE_TOTAL.labels(action=attempt.action, target=incident.target).inc()

                # If execution failed or skipped
                if incident.status in {IncidentState.resolved, IncidentState.escalated, IncidentState.blocked}:
                    break

                # 4. Independent Verification
                if incident.status == IncidentState.verifying:
                    verify_result = await self.verifier.verify(incident=incident)
                    verif_status_str = "passed" if verify_result.get("passed") else "failed"
                    VERIFICATION_TOTAL.labels(status=verif_status_str, target=incident.target).inc()

                    if verify_result.get("passed"):
                        # Pipeline resolved!
                        total_duration = round(time.perf_counter() - start_time, 2)
                        kpi_tracker.record_remediation_result(success=True, duration_seconds=total_duration)
                        INCIDENTS_RESOLVED_TOTAL.labels(target=incident.target, action=attempt.action).inc()
                        ACTIVE_INCIDENTS.dec()

                        self.audit_logger.record_from_incident(
                            incident=incident,
                            execution_status=attempt.status.value,
                            verification_status="passed",
                            notes=f"Incident resolved in {total_duration}s after {incident.attempt_count} attempt(s).",
                        )
                        logger.info(
                            f"=== INCIDENT {incident.id} RESOLVED SUCCESSFULLY in {total_duration}s ==="
                        )
                        return incident
                    else:
                        # Verification failed
                        if incident.status == IncidentState.escalated:
                            # Reached max attempts
                            kpi_tracker.record_remediation_result(success=False, duration_seconds=0.0)
                            kpi_tracker.record_manual_intervention()
                            INCIDENTS_ESCALATED_TOTAL.labels(
                                target=incident.target, reason="max_attempts_exceeded"
                            ).inc()
                            ACTIVE_INCIDENTS.dec()

                            self.audit_logger.record_from_incident(
                                incident=incident,
                                execution_status=attempt.status.value,
                                verification_status="failed",
                                notes=f"Remediation failed verification across {incident.attempt_count} attempts. Escalated.",
                            )
                            logger.warning(
                                f"=== INCIDENT {incident.id} ESCALATED: Max attempts reached ==="
                            )
                            return incident
                        # If retrying, loop continues

        except Exception as e:
            logger.error(f"Unhandled error in orchestrator pipeline for {incident.id}: {e}", exc_info=True)
            if not incident.is_terminal:
                incident.transition_to(IncidentState.escalated, reason=f"Unhandled pipeline error: {str(e)}")
            self.audit_logger.record_from_incident(
                incident=incident,
                execution_status="error",
                verification_status="failed",
                notes=f"Pipeline exception: {str(e)}",
            )
            ACTIVE_INCIDENTS.dec()

        return incident
