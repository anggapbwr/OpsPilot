"""Custom exception hierarchy for OpsPilot."""


class OpsPilotError(Exception):
    """Base exception for all OpsPilot domain errors."""

    def __init__(self, message: str, code: str = "internal_error"):
        super().__init__(message)
        self.message = message
        self.code = code


class IncidentNotFoundError(OpsPilotError):
    """Raised when an incident is not found by ID."""

    def __init__(self, incident_id: str):
        super().__init__(
            message=f"Incident with ID '{incident_id}' was not found.",
            code="incident_not_found",
        )
        self.incident_id = incident_id


class PolicyDeniedError(OpsPilotError):
    """Raised when remediation action is denied or blocked by policy."""

    def __init__(self, action: str, reason: str):
        super().__init__(
            message=f"Remediation action '{action}' denied: {reason}",
            code="policy_denied",
        )
        self.action = action
        self.reason = reason


class RemediationExecutionError(OpsPilotError):
    """Raised when an execution engine fails to run a playbook or action."""

    def __init__(self, action: str, details: str):
        super().__init__(
            message=f"Execution of remediation '{action}' failed: {details}",
            code="remediation_execution_failed",
        )
        self.action = action
        self.details = details


class VerificationFailedError(OpsPilotError):
    """Raised when post-remediation health verification fails."""

    def __init__(self, target: str, details: str):
        super().__init__(
            message=f"Verification failed for target '{target}': {details}",
            code="verification_failed",
        )
        self.target = target
        self.details = details


class InvalidStateTransitionError(OpsPilotError):
    """Raised when an illegal incident state transition is requested."""

    def __init__(self, current_state: str, target_state: str):
        super().__init__(
            message=f"Cannot transition incident from '{current_state}' to '{target_state}'.",
            code="invalid_state_transition",
        )
        self.current_state = current_state
        self.target_state = target_state


class DiagnosisValidationError(OpsPilotError):
    """Raised when AI diagnosis payload fails schema or safety validation."""

    def __init__(self, details: str):
        super().__init__(
            message=f"Diagnosis validation failed: {details}",
            code="diagnosis_validation_failed",
        )
