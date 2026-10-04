"""Sample target service: payment-api.

Simulates a production microservice with controllable fault injection for OpsPilot.
"""

import os
import sys
import time
from typing import Any, Dict

import uvicorn
from fastapi import FastAPI, Response, status

app = FastAPI(
    title="Payment API Simulator",
    description="Sample production target service for OpsPilot autonomous remediation testing.",
    version="1.0.0",
)

# In-memory operational health flag
_state: Dict[str, Any] = {
    "is_healthy": True,
    "has_crashed": False,
    "version": "1.0.0",
    "latency_seconds": 0.0,
    "deployment_error": None,
}


@app.get("/")
def read_root():
    """Service root banner."""
    return {
        "service": "payment-api",
        "version": _state["version"],
        "status": "healthy" if _state["is_healthy"] else "degraded",
        "description": "Payment Processing Microservice",
    }


@app.get("/health")
def health_check(response: Response):
    """Health check endpoint monitored by OpsPilot."""
    # 1. Latency delay simulation if active
    latency = _state.get("latency_seconds", 0.0)
    if latency > 0:
        time.sleep(latency)

    # 2. Bad deployment failure mode (503)
    if _state.get("deployment_error"):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "unhealthy",
            "service": "payment-api",
            "version": _state.get("version", "2.0.0-broken"),
            "error": _state["deployment_error"],
            "error_code": "ERR_DEPLOYMENT_FAILED",
            "detail": "Release v2.0.0 schema migration incompatible with live database",
        }

    # 3. Standard internal failure mode (500)
    if not _state["is_healthy"]:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {
            "status": "unhealthy",
            "service": "payment-api",
            "version": _state.get("version", "1.0.0"),
            "error": "Worker thread deadlocked; database connection pool exhausted",
            "error_code": "ERR_PAYMENT_GATEWAY_DOWN",
        }

    return {
        "status": "healthy",
        "service": "payment-api",
        "version": _state.get("version", "1.0.0"),
        "dependencies": {
            "database": "connected",
            "queue": "idle",
            "worker_threads": 4,
        },
    }


@app.get("/metrics")
def get_metrics():
    """Simulated Prometheus metrics."""
    return Response(
        content=(
            "# HELP payment_api_requests_total Total payment requests\n"
            "# TYPE payment_api_requests_total counter\n"
            "payment_api_requests_total 4210\n"
            "# HELP payment_api_healthy Current health flag (1=healthy, 0=unhealthy)\n"
            "# TYPE payment_api_healthy gauge\n"
            f"payment_api_healthy {1 if _state['is_healthy'] else 0}\n"
        ),
        media_type="text/plain",
    )


# --- FAULT INJECTION CONTROLS (Isolated to simulator) ---


@app.post("/fault/unhealthy")
def inject_unhealthy():
    """Inject internal failure causing /health to return HTTP 500."""
    _state["is_healthy"] = False
    _state["deployment_error"] = None
    _state["latency_seconds"] = 0.0
    return {
        "action": "fault_injected",
        "target": "payment-api",
        "new_status": "unhealthy",
        "detail": "/health endpoint will now return HTTP 500",
    }


@app.post("/fault/deployment-failed")
def inject_deployment_failure():
    """Inject buggy deployment v2.0.0 causing /health to return HTTP 503."""
    _state["is_healthy"] = False
    _state["version"] = "2.0.0-broken"
    _state["deployment_error"] = "Deployment v2.0.0 failed schema migration; rollback required."
    _state["latency_seconds"] = 0.0
    return {
        "action": "deployment_failure_injected",
        "target": "payment-api",
        "version": "2.0.0-broken",
        "new_status": "unhealthy (503)",
        "detail": "Simulating defective v2.0.0 release that requires rollback_deployment",
    }


@app.post("/fault/latency")
def inject_latency(seconds: float = 5.0):
    """Inject response latency delay into /health to test timeout detection."""
    _state["latency_seconds"] = seconds
    return {
        "action": "latency_injected",
        "target": "payment-api",
        "latency_seconds": seconds,
        "detail": f"/health endpoint will now pause {seconds}s before responding",
    }


@app.post("/fault/rollback")
def inject_rollback():
    """Roll back release to previous stable version 1.0.0 (used by Ansible rollback playbook)."""
    _state["is_healthy"] = True
    _state["version"] = "1.0.0"
    _state["deployment_error"] = None
    _state["latency_seconds"] = 0.0
    return {
        "action": "rolled_back",
        "target": "payment-api",
        "new_status": "healthy",
        "version": "1.0.0",
        "detail": "Target restored to stable release v1.0.0 (HTTP 200)",
    }


@app.post("/fault/recover")
def inject_recovery():
    """Recover the service back to normal healthy operation (HTTP 200)."""
    _state["is_healthy"] = True
    _state["version"] = "1.0.0"
    _state["deployment_error"] = None
    _state["latency_seconds"] = 0.0
    return {
        "action": "recovered",
        "target": "payment-api",
        "new_status": "healthy",
        "version": "1.0.0",
        "detail": "/health endpoint restored to HTTP 200",
    }


@app.post("/fault/crash")
def inject_crash():
    """Simulate ungraceful process crash."""
    _state["has_crashed"] = True
    sys.exit(1)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, log_level="info")
