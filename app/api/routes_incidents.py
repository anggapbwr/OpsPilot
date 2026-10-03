"""Incident management API routes."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.audit.logger import AuditLogger
from app.dependencies import get_audit_logger, get_orchestrator
from app.detection.detector import generate_incident_id
from app.models.incident import Incident, IncidentSeverity, IncidentState, IncidentType
from app.models.remediation import ApprovalRecord
from app.orchestrator import IncidentOrchestrator

router = APIRouter(prefix="/api/v1/incidents", tags=["Incidents"])


class CreateIncidentRequest(BaseModel):
    """Payload to manually trigger or record an incident."""

    type: Optional[IncidentType] = Field(default=None, description="Incident type")
    severity: Optional[IncidentSeverity] = Field(
        default=IncidentSeverity.medium, description="Severity rating"
    )
    target: Optional[str] = Field(default=None, description="Target container/service")
    auto_detect: bool = Field(
        default=False, description="Whether to probe target before creating"
    )


class ApprovalRequest(BaseModel):
    """Payload to authorize a high-risk remediation action."""

    approved_by: str = Field(..., description="User or operator granting approval")
    note: Optional[str] = Field(default=None, description="Operational justification")


@router.get("", response_model=List[Incident], summary="List all incidents")
def list_incidents(
    orchestrator: IncidentOrchestrator = Depends(get_orchestrator),
) -> List[Incident]:
    """Retrieve all operational incidents tracked by OpsPilot."""
    return orchestrator.list_incidents()


@router.post("", response_model=Incident, status_code=status.HTTP_201_CREATED, summary="Create or detect incident")
async def create_incident(
    req: CreateIncidentRequest,
    orchestrator: IncidentOrchestrator = Depends(get_orchestrator),
) -> Incident:
    """Manually register an incident or probe target infrastructure for anomalies."""
    if req.auto_detect:
        detected = await orchestrator.detect_and_register()
        if detected:
            return detected
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No operational anomalies detected on target service.",
        )

    incident = Incident(
        id=generate_incident_id(),
        type=req.type or IncidentType.container_unhealthy,
        severity=req.severity or IncidentSeverity.medium,
        target=req.target or "payment-api",
        status=IncidentState.detected,
    )
    return orchestrator.register_incident(incident)


@router.get("/{incident_id}", response_model=Incident, summary="Get incident details")
def get_incident(
    incident_id: str,
    orchestrator: IncidentOrchestrator = Depends(get_orchestrator),
) -> Incident:
    """Retrieve a specific incident by ID."""
    incident = orchestrator.get_incident(incident_id)
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found.",
        )
    return incident


@router.post("/{incident_id}/diagnose", summary="Trigger diagnosis")
async def diagnose_incident(
    incident_id: str,
    orchestrator: IncidentOrchestrator = Depends(get_orchestrator),
) -> Dict[str, Any]:
    """Run evidence collection and AI/fallback diagnosis for an incident."""
    incident = orchestrator.get_incident(incident_id)
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found.",
        )

    # Transition to investigating if in detected state
    if incident.status == IncidentState.detected:
        incident.transition_to(IncidentState.investigating)

    # Collect comprehensive evidence if not already fully collected
    if not incident.evidence or "recent_logs" not in incident.evidence:
        evidence = await orchestrator.evidence_collector.collect_evidence(
            target_name=incident.target,
            incident_type=incident.type.value,
        )
        incident.evidence = evidence

    # Run diagnosis
    diagnosis = await orchestrator.diagnosis_engine.diagnose(
        incident=incident,
        evidence=incident.evidence or {},
    )
    incident.diagnosis = diagnosis
    if incident.status == IncidentState.investigating:
        incident.transition_to(IncidentState.diagnosed)

    return {
        "incident_id": incident.id,
        "status": incident.status.value,
        "diagnosis": diagnosis.model_dump(),
    }


@router.post("/{incident_id}/approve", summary="Approve remediation action")
def approve_incident(
    incident_id: str,
    req: ApprovalRequest,
    orchestrator: IncidentOrchestrator = Depends(get_orchestrator),
) -> Dict[str, Any]:
    """Approve a high-risk remediation action that requires explicit operator consent."""
    incident = orchestrator.get_incident(incident_id)
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found.",
        )

    if incident.status != IncidentState.awaiting_approval:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Incident is not awaiting approval (current status: '{incident.status.value}').",
        )

    incident.approval = ApprovalRecord(
        approved=True,
        approved_by=req.approved_by,
        approved_at=datetime.now(timezone.utc),
        note=req.note,
    )

    return {
        "incident_id": incident.id,
        "status": incident.status.value,
        "approval": incident.approval.model_dump(),
        "message": f"Remediation action approved by {req.approved_by}.",
    }


@router.get("/{incident_id}/audit", summary="Get incident audit trail")
def get_incident_audit(
    incident_id: str,
    orchestrator: IncidentOrchestrator = Depends(get_orchestrator),
    audit_logger: AuditLogger = Depends(get_audit_logger),
) -> Dict[str, Any]:
    """Retrieve complete audit history and execution trail for an incident."""
    incident = orchestrator.get_incident(incident_id)
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found.",
        )

    entries = audit_logger.get_entries_for_incident(incident_id)
    return {
        "incident_id": incident_id,
        "entries_count": len(entries),
        "audit_trail": [e.model_dump() for e in entries],
        "remediation_history": [a.model_dump() for a in incident.remediation_history],
    }


@router.post("/{incident_id}/run", response_model=Incident, summary="Run end-to-end pipeline")
async def run_incident_pipeline(
    incident_id: str,
    orchestrator: IncidentOrchestrator = Depends(get_orchestrator),
) -> Incident:
    """Execute the complete autonomous remediation workflow for an incident."""
    incident = orchestrator.get_incident(incident_id)
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found.",
        )

    return await orchestrator.run_pipeline(incident)
