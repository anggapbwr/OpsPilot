"""Health check API routes."""

from typing import Any, Dict

import httpx
from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.dependencies import get_health_checker, get_policy_engine
from app.detection.health_checker import HealthChecker
from app.policy.engine import PolicyEngine

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Basic service health")
def get_basic_health(settings: Settings = Depends(get_settings)) -> Dict[str, Any]:
    """Liveness probe returning operational status of OpsPilot."""
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": "0.1.0",
        "environment": settings.app_env,
    }


@router.get("/api/v1/health", summary="Detailed platform health")
async def get_detailed_health(
    settings: Settings = Depends(get_settings),
    policy_engine: PolicyEngine = Depends(get_policy_engine),
    health_checker: HealthChecker = Depends(get_health_checker),
) -> Dict[str, Any]:
    """Comprehensive readiness report checking target service, policy rules, and Ollama."""
    target_health = await health_checker.check_http_health()

    # Check Ollama reachability
    ollama_ok = False
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            res = await client.get(f"{settings.ollama_base_url}/api/tags")
            ollama_ok = res.status_code == 200
    except Exception:
        ollama_ok = False

    return {
        "status": "healthy",
        "service": settings.app_name,
        "components": {
            "policy_engine": {
                "loaded_rules_count": len(policy_engine.policy_doc.policies),
                "status": "active",
            },
            "target_service": {
                "name": settings.target_service_name,
                "url": settings.target_service_url,
                "reachable": target_health.get("healthy", False),
                "status_code": target_health.get("status_code"),
            },
            "ollama_ai": {
                "base_url": settings.ollama_base_url,
                "model": settings.ollama_model,
                "reachable": ollama_ok,
                "fallback_available": True,
            },
        },
    }
