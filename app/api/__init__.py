"""API package router aggregation."""

from fastapi import APIRouter

from app.api.routes_health import router as health_router
from app.api.routes_incidents import router as incidents_router
from app.api.routes_metrics import router as metrics_router
from app.api.routes_remediation import router as remediation_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(incidents_router)
api_router.include_router(remediation_router)
api_router.include_router(metrics_router)

__all__ = ["api_router"]
