"""Remediation Executor enforcing policy checks before executing playbooks."""

from datetime import datetime, timezone
from typing import Optional

from app.core.exceptions import PolicyDeniedError, RemediationExecutionError
from app.core.logging import get_logger
from app.models.incident import Incident, IncidentState
from app.models.remediation import (
    PolicyDecision,
    RemediationAttempt,
    RemediationStatus,
    VerificationStatus,
)
from app.policy.engine import PolicyEngine
from app.remediation.ansible_runner import AnsibleRunner

logger = get_logger("remediation.executor")


class RemediationExecutor:
    """Orchestrates policy verification and execution of remediation playbooks."""

    def __init__(
        self,
        policy_engine: Optional[PolicyEngine] = None,
        ansible_runner: Optional[AnsibleRunner] = None,
    ):
        self.policy_engine = policy_engine or PolicyEngine()
        self.ansible_runner = ansible_runner or AnsibleRunner()

    async def execute(
        self,
        incident: Incident,
        override_action: Optional[str] = None,
    ) -> RemediationAttempt:
        """Evaluate policy and execute remediation action for the incident."""
        # 1. Determine action
        action = override_action
        if not action:
            if not incident.diagnosis:
                raise RemediationExecutionError(
                    action="unknown",
                    details=f"Incident {incident.id} has not been diagnosed yet.",
                )
            action = incident.diagnosis.recommended_action

        # Handle 'no_action'
        if action == "no_action":
            logger.info(f"Diagnosis recommended 'no_action' for incident {incident.id}.")
            decision = self.policy_engine.evaluate(action, current_attempts=incident.attempt_count)
            incident.policy_decision = decision
            incident.transition_to(IncidentState.resolved, reason="No action required")
            attempt = RemediationAttempt(
                attempt_number=incident.attempt_count,
                action="no_action",
                playbook=None,
                status=RemediationStatus.skipped,
                verification_status=VerificationStatus.passed,
                output="No action requested by diagnosis.",
            )
            incident.remediation_history.append(attempt)
            return attempt

        # Handle 'escalate'
        if action == "escalate":
            logger.info(f"Diagnosis recommended 'escalate' for incident {incident.id}.")
            decision = self.policy_engine.evaluate(action, current_attempts=incident.attempt_count)
            incident.policy_decision = decision
            incident.transition_to(IncidentState.escalated, reason="Escalated by diagnosis")
            attempt = RemediationAttempt(
                attempt_number=incident.attempt_count,
                action="escalate",
                playbook=None,
                status=RemediationStatus.skipped,
                verification_status=VerificationStatus.failed,
                output="Incident escalated to on-call engineer.",
            )
            incident.remediation_history.append(attempt)
            return attempt

        # 2. Evaluate Policy
        decision: PolicyDecision = self.policy_engine.evaluate(
            action=action,
            current_attempts=incident.attempt_count,
        )
        incident.policy_decision = decision

        # 3. Check if Action is Blocked or Denied
        if not decision.allowed:
            if decision.blocked:
                logger.warning(
                    f"Action '{action}' is BLOCKED by policy for Incident {incident.id}: {decision.reason}"
                )
                incident.transition_to(IncidentState.blocked, reason=decision.reason or "Blocked by policy")
            else:
                logger.warning(
                    f"Action '{action}' is DENIED by policy for Incident {incident.id}: {decision.reason}"
                )
                incident.transition_to(IncidentState.escalated, reason=decision.reason or "Denied by policy")

            attempt = RemediationAttempt(
                attempt_number=incident.attempt_count,
                action=action,
                playbook=None,
                status=RemediationStatus.failure,
                verification_status=VerificationStatus.failed,
                output=f"Execution rejected by policy engine: {decision.reason}",
            )
            incident.remediation_history.append(attempt)
            raise PolicyDeniedError(action=action, reason=decision.reason or "Policy denied")

        # 4. Check Approval Requirement
        if decision.requires_approval and not (incident.approval and incident.approval.approved):
            logger.info(
                f"Action '{action}' requires human approval. Incident {incident.id} awaiting approval."
            )
            incident.transition_to(
                IncidentState.awaiting_approval,
                reason="High-risk action requires human approval",
            )
            attempt = RemediationAttempt(
                attempt_number=incident.attempt_count,
                action=action,
                playbook=None,
                status=RemediationStatus.pending,
                verification_status=VerificationStatus.pending,
                output="Remediation paused: awaiting manual human approval.",
            )
            incident.remediation_history.append(attempt)
            return attempt

        # 5. Check Bounded Retries
        if incident.attempt_count >= incident.max_attempts:
            logger.warning(
                f"Incident {incident.id} reached max remediation attempts ({incident.attempt_count}/{incident.max_attempts}). Escalating."
            )
            incident.transition_to(IncidentState.escalated, reason="Max attempts reached")
            attempt = RemediationAttempt(
                attempt_number=incident.attempt_count,
                action=action,
                playbook=None,
                status=RemediationStatus.failure,
                verification_status=VerificationStatus.failed,
                output="Max remediation attempts exceeded.",
            )
            incident.remediation_history.append(attempt)
            return attempt

        # 6. Execute Predefined Ansible Playbook
        if incident.status != IncidentState.remediating:
            incident.transition_to(IncidentState.remediating)

        incident.attempt_count += 1
        current_attempt_num = incident.attempt_count
        started_at = datetime.now(timezone.utc)
        playbook_name = self.ansible_runner.get_playbook_for_action(action)

        logger.info(
            f"Executing remediation attempt {current_attempt_num}/{incident.max_attempts} "
            f"for Incident {incident.id}: action '{action}' -> playbook '{playbook_name}'"
        )

        exec_result = await self.ansible_runner.execute_action(
            action=action,
            target=incident.target,
        )

        finished_at = datetime.now(timezone.utc)
        duration = exec_result.get("duration_seconds", 0.0)
        success = exec_result.get("success", False)

        attempt = RemediationAttempt(
            attempt_number=current_attempt_num,
            action=action,
            playbook=playbook_name,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration,
            status=RemediationStatus.success if success else RemediationStatus.failure,
            verification_status=VerificationStatus.pending,
            output=exec_result.get("stdout"),
            error=exec_result.get("stderr"),
        )
        incident.remediation_history.append(attempt)

        if success:
            logger.info(
                f"Remediation playbook '{playbook_name}' executed successfully. Transitioning to 'verifying'."
            )
            incident.transition_to(IncidentState.verifying)
        else:
            logger.error(f"Remediation execution failed for attempt {current_attempt_num}.")
            if incident.attempt_count >= incident.max_attempts:
                logger.warning(f"Incident {incident.id} max attempts reached after failure. Escalating.")
                incident.transition_to(IncidentState.escalated, reason="Playbook execution failed and max attempts reached")

        return attempt
