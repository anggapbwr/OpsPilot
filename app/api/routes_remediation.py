"""Remediation and demo failure API routes."""

from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.core.exceptions import PolicyDeniedError
from app.dependencies import get_orchestrator
from app.orchestrator import IncidentOrchestrator

router = APIRouter(tags=["Remediation & Demo"])


class RemediateRequest(BaseModel):
    """Optional action override for remediation trigger."""

    action: Optional[str] = Field(
        default=None, description="Optional action override subject to policy validation"
    )


@router.post("/api/v1/incidents/{incident_id}/remediate", summary="Trigger remediation execution")
async def remediate_incident(
    incident_id: str,
    req: RemediateRequest = RemediateRequest(),
    orchestrator: IncidentOrchestrator = Depends(get_orchestrator),
) -> Dict[str, Any]:
    """Execute policy-checked Ansible remediation for an incident."""
    incident = orchestrator.get_incident(incident_id)
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found.",
        )

    try:
        attempt = await orchestrator.remediation_executor.execute(
            incident=incident,
            override_action=req.action,
        )
        return {
            "incident_id": incident.id,
            "status": incident.status.value,
            "attempt": attempt.model_dump(),
        }
    except PolicyDeniedError as e:
        orchestrator.audit_logger.record_from_incident(
            incident=incident,
            execution_status="denied",
            verification_status="failed",
            notes=f"Policy denied execution: {e.reason}",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "policy_denied",
                "message": e.reason,
                "action": e.action,
            },
        )


@router.post("/api/v1/incidents/{incident_id}/verify", summary="Trigger verification")
async def verify_incident(
    incident_id: str,
    orchestrator: IncidentOrchestrator = Depends(get_orchestrator),
) -> Dict[str, Any]:
    """Execute independent health verification against target infrastructure."""
    incident = orchestrator.get_incident(incident_id)
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found.",
        )

    result = await orchestrator.verifier.verify(incident=incident)
    verif_status = "passed" if result.get("passed") else "failed"
    orchestrator.audit_logger.record_from_incident(
        incident=incident,
        execution_status="success" if result.get("passed") else "failed",
        verification_status=verif_status,
        notes=result.get("message") or result.get("error"),
    )
    return {
        "incident_id": incident.id,
        "status": incident.status.value,
        "verification": result,
    }


# --- DEMO FAILURE ENDPOINT ---


class DemoFailureResponse(BaseModel):
    """Outcome of controlled failure injection demo."""

    fault_injected: bool
    incident_id: Optional[str]
    target: str
    final_status: str
    summary: str


@router.post(
    "/api/v1/demo/failure",
    response_model=DemoFailureResponse,
    summary="Trigger controlled demo failure",
)
async def trigger_demo_failure(
    orchestrator: IncidentOrchestrator = Depends(get_orchestrator),
    settings: Settings = Depends(get_settings),
) -> DemoFailureResponse:
    """Safely triggers a controlled failure in the sample target service

    and automatically executes the OpsPilot pipeline to demonstrate autonomous recovery.
    """
    fault_url = f"{settings.target_service_url.rstrip('/')}/fault/unhealthy"

    # 1. Inject failure into target
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            res = await client.post(fault_url)
            res.raise_for_status()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to inject fault into target service at {fault_url}: {str(e)}. Ensure payment-api is running.",
        )

    # 2. Detect anomaly
    incident = await orchestrator.detect_and_register()
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Fault was sent, but detector failed to capture an anomaly.",
        )

    # 3. Run complete autonomous pipeline
    resolved_incident = await orchestrator.run_pipeline(incident)

    return DemoFailureResponse(
        fault_injected=True,
        incident_id=resolved_incident.id,
        target=resolved_incident.target,
        final_status=resolved_incident.status.value,
        summary=(
            f"Anomaly injected into '{resolved_incident.target}', detected as '{resolved_incident.id}', "
            f"remediated via policy-approved Ansible playbook, and final state is '{resolved_incident.status.value}'."
        ),
    )
