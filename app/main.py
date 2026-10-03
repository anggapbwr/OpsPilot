"""Main FastAPI application entry point for OpsPilot."""

from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.api import api_router
from app.core.config import get_settings
from app.core.exceptions import (
    IncidentNotFoundError,
    InvalidStateTransitionError,
    OpsPilotError,
    PolicyDeniedError,
    RemediationExecutionError,
    VerificationFailedError,
)
from app.core.logging import get_logger, setup_logging
from app.dependencies import get_policy_engine

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    settings = get_settings()
    setup_logging(log_level=settings.log_level)
    logger.info(f"Starting {settings.app_name} in {settings.app_env} mode...")

    # Preload and validate policy configuration
    policy_engine = get_policy_engine()
    logger.info(
        f"Policy engine initialized with {len(policy_engine.policy_doc.policies)} rules from '{settings.policy_file}'."
    )
    yield
    logger.info(f"Shutting down {settings.app_name}...")


settings = get_settings()
app = FastAPI(
    title="OpsPilot",
    description=(
        "Policy-Driven Autonomous Operations & Remediation Platform.\n\n"
        "**Core Principle:**\n"
        "- AI = Analyze\n"
        "- Policy Engine = Decide\n"
        "- Ansible = Execute\n"
        "- Verifier = Validate\n\n"
        "AI model commands are never executed directly; all actions pass through deterministic policy rules."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Attach API routes
app.include_router(api_router)


@app.get("/", summary="Root index banner")
def root_index() -> Dict[str, Any]:
    """Root platform information and endpoint index."""
    return {
        "name": "OpsPilot",
        "tagline": "Detect. Diagnose. Decide. Remediate. Verify.",
        "description": "Policy-Driven Autonomous Operations & Remediation Platform",
        "version": "0.1.0",
        "documentation": {
            "swagger": "/docs",
            "redoc": "/redoc",
        },
        "endpoints": {
            "health": "/health",
            "detailed_health": "/api/v1/health",
            "incidents": "/api/v1/incidents",
            "metrics": "/metrics",
            "kpis": "/api/v1/metrics/kpi",
            "demo_failure": "/api/v1/demo/failure",
        },
    }


# --- EXCEPTION HANDLERS ---


@app.exception_handler(PolicyDeniedError)
async def policy_denied_handler(request: Request, exc: PolicyDeniedError):
    """Handle deterministic policy denials."""
    logger.warning(f"Policy denied request on {request.url.path}: {exc.message}")
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={
            "error": "policy_denied",
            "action": exc.action,
            "message": exc.reason,
        },
    )


@app.exception_handler(IncidentNotFoundError)
async def incident_not_found_handler(request: Request, exc: IncidentNotFoundError):
    """Handle missing incident lookup."""
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "error": "incident_not_found",
            "incident_id": exc.incident_id,
            "message": exc.message,
        },
    )


@app.exception_handler(InvalidStateTransitionError)
async def invalid_transition_handler(request: Request, exc: InvalidStateTransitionError):
    """Handle illegal incident state transitions."""
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "invalid_state_transition",
            "current_state": exc.current_state,
            "target_state": exc.target_state,
            "message": exc.message,
        },
    )


@app.exception_handler(RemediationExecutionError)
async def remediation_execution_handler(request: Request, exc: RemediationExecutionError):
    """Handle playbook execution failures."""
    logger.error(f"Remediation execution error: {exc.message}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "remediation_execution_failed",
            "action": exc.action,
            "message": exc.details,
        },
    )


@app.exception_handler(VerificationFailedError)
async def verification_failed_handler(request: Request, exc: VerificationFailedError):
    """Handle post-remediation verification failures."""
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "verification_failed",
            "target": exc.target,
            "message": exc.details,
        },
    )


@app.exception_handler(OpsPilotError)
async def generic_opspilot_error_handler(request: Request, exc: OpsPilotError):
    """Handle general domain exceptions without leaking stack trace."""
    logger.error(f"Domain error: {exc.message}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": exc.code,
            "message": exc.message,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all handler ensuring internal stack traces are logged but not leaked."""
    logger.critical(f"Unhandled exception on {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "internal_server_error",
            "message": "An unexpected server error occurred. Please consult the system audit log.",
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
