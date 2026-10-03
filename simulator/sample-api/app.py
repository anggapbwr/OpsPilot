"""Sample target service: payment-api.

Simulates a production microservice with controllable fault injection for OpsPilot.
"""

import os
import sys
from typing import Dict

import uvicorn
from fastapi import FastAPI, Response, status

app = FastAPI(
    title="Payment API Simulator",
    description="Sample production target service for OpsPilot autonomous remediation testing.",
    version="1.0.0",
)

# In-memory operational health flag
_state: Dict[str, bool] = {
    "is_healthy": True,
    "has_crashed": False,
}


@app.get("/")
def read_root():
    """Service root banner."""
    return {
        "service": "payment-api",
        "version": "1.0.0",
        "status": "healthy" if _state["is_healthy"] else "degraded",
        "description": "Payment Processing Microservice",
    }


@app.get("/health")
def health_check(response: Response):
    """Health check endpoint monitored by OpsPilot."""
    if not _state["is_healthy"]:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {
            "status": "unhealthy",
            "service": "payment-api",
            "error": "Worker thread deadlocked; database connection pool exhausted",
            "error_code": "ERR_PAYMENT_GATEWAY_DOWN",
        }

    return {
        "status": "healthy",
        "service": "payment-api",
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
    return {
        "action": "fault_injected",
        "target": "payment-api",
        "new_status": "unhealthy",
        "detail": "/health endpoint will now return HTTP 500",
    }


@app.post("/fault/recover")
def inject_recovery():
    """Recover the service back to normal healthy operation (HTTP 200)."""
    _state["is_healthy"] = True
    return {
        "action": "recovered",
        "target": "payment-api",
        "new_status": "healthy",
        "detail": "/health endpoint restored to HTTP 200",
    }


@app.post("/fault/crash")
def inject_crash():
    """Simulate ungraceful process crash."""
    _state["has_crashed"] = True
    # Exit process cleanly to simulate crash
    sys.exit(1)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, log_level="info")
