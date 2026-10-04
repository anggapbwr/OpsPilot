"""Audit logger recording deterministic, structured incident history."""

from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.audit import AuditEntry
from app.models.incident import Incident

logger = get_logger("audit.logger")


class AuditLogger:
    """Records audit logs to disk in JSONL format and maintains in-memory lookup."""

    def __init__(self, log_file: Optional[Path] = None):
        settings = get_settings()
        self.log_file = log_file or settings.resolved_audit_log_file
        self._entries: List[AuditEntry] = []
        self._ensure_log_dir()

    def _ensure_log_dir(self) -> None:
        """Create parent directory for audit log file if it does not exist."""
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create audit log directory {self.log_file.parent}: {e}")

    def record_entry(self, entry: AuditEntry) -> None:
        """Append audit entry to disk and in-memory list."""
        self._entries.append(entry)
        line = entry.model_dump_json() + "\n"

        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(line)
            logger.info(
                f"Audit recorded for {entry.incident_id}: "
                f"Action={entry.recommended_action}, Decision={entry.policy_decision}, Final={entry.final_status}"
            )
        except Exception as e:
            logger.error(f"Failed writing audit entry to {self.log_file}: {e}")

    def record_from_incident(
        self,
        incident: Incident,
        execution_status: str = "success",
        verification_status: str = "passed",
        notes: Optional[str] = None,
    ) -> AuditEntry:
        """Construct and record an audit entry directly from current incident state."""
        diag_source = incident.diagnosis.source.value if incident.diagnosis else "none"
        root_cause = incident.diagnosis.root_cause if incident.diagnosis else "none"
        action = (
            incident.diagnosis.recommended_action if incident.diagnosis else "none"
        )

        policy_decision = "none"
        risk = "unknown"
        approval_required = False

        if incident.policy_decision:
            policy_decision = "allowed" if incident.policy_decision.allowed else "denied"
            if incident.policy_decision.blocked:
                policy_decision = "blocked"
            risk = incident.policy_decision.risk.value
            approval_required = incident.policy_decision.requires_approval

        # Determine outcome semantics
        outcome = "UNKNOWN"
        if policy_decision == "blocked" or execution_status in {"blocked", "not_executed"}:
            outcome = "BLOCKED_BY_POLICY"
        elif execution_status == "denied":
            outcome = "DENIED_BY_POLICY"
        elif execution_status == "pending_approval":
            outcome = "AWAITING_APPROVAL"
        elif execution_status == "failure":
            outcome = "REMEDIATION_FAILED"
        elif verification_status == "passed":
            if execution_status == "success":
                outcome = "REMEDIATION_SUCCEEDED_AND_VERIFIED"
            else:
                outcome = "REMEDIATION_FAILED_BUT_RECOVERED_INDEPENDENTLY"
        elif verification_status == "failed":
            outcome = "REMEDIATION_FAILED"

        # Calculate duration
        now = datetime.now(timezone.utc)
        duration_sec = round((now - incident.created_at).total_seconds(), 2)

        entry = AuditEntry(
            timestamp=now,
            incident_id=incident.id,
            incident_type=incident.type.value,
            severity=incident.severity.value,
            target=incident.target,
            diagnosis_source=diag_source,
            root_cause=root_cause,
            recommended_action=action,
            policy_decision=policy_decision,
            risk=risk,
            approval_required=approval_required,
            execution_status=execution_status,
            verification_status=verification_status,
            attempt=incident.attempt_count,
            final_status=incident.status.value,
            duration_seconds=duration_sec,
            outcome=outcome,
            notes=notes,
        )

        self.record_entry(entry)
        return entry

    def get_entries_for_incident(self, incident_id: str) -> List[AuditEntry]:
        """Retrieve recorded audit entries for an incident."""
        return [e for e in self._entries if e.incident_id == incident_id]

    def get_all_entries(self) -> List[AuditEntry]:
        """Return all recorded audit entries in memory."""
        return list(self._entries)
