"""Prometheus and operational metrics API routes."""

from typing import Any, Dict

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest

from app.core.metrics import kpi_tracker

router = APIRouter(tags=["Metrics"])


@router.get("/metrics", summary="Prometheus metrics scrape endpoint")
def prometheus_metrics() -> Response:
    """Standard Prometheus metrics exposition endpoint."""
    return Response(
        content=generate_latest(REGISTRY),
        media_type=CONTENT_TYPE_LATEST,
    )


@router.get("/api/v1/metrics/kpi", summary="Operational KPI metrics")
def get_operational_kpis() -> Dict[str, Any]:
    """Calculated operational impact metrics including MTTR, Success Rate, and Manual Intervention Rate."""
    return {
        "kpis": kpi_tracker.get_kpis(),
        "formulas": {
            "mttr": "sum(recovery duration) / number of resolved incidents",
            "success_rate": "successful remediations / total attempts * 100",
            "manual_intervention_rate": "incidents requiring manual intervention / total incidents * 100",
        },
    }
