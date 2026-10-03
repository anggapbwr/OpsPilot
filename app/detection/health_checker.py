"""Target health check evaluation."""

import time
from typing import Any, Dict, Optional

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("detection.health_checker")


class HealthChecker:
    """Performs HTTP and container health checks against target infrastructure."""

    def __init__(self, service_url: Optional[str] = None, timeout: float = 3.0):
        settings = get_settings()
        self.service_url = (service_url or settings.target_service_url).rstrip("/")
        self.timeout = timeout

    async def check_http_health(self, path: str = "/health") -> Dict[str, Any]:
        """Perform HTTP health check against target service endpoint."""
        url = f"{self.service_url}{path}"
        start_time = time.perf_counter()

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url)
                latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

                is_healthy = response.status_code == 200
                payload = {}
                try:
                    payload = response.json()
                except Exception:
                    payload = {"raw": response.text[:200]}

                return {
                    "healthy": is_healthy,
                    "status_code": response.status_code,
                    "latency_ms": latency_ms,
                    "endpoint": url,
                    "payload": payload,
                    "error": None if is_healthy else f"HTTP {response.status_code}",
                }
        except httpx.ConnectError as e:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.warning(f"Connection error to {url}: {e}")
            return {
                "healthy": False,
                "status_code": None,
                "latency_ms": latency_ms,
                "endpoint": url,
                "payload": {},
                "error": "Connection refused / Service unreachable",
            }
        except httpx.TimeoutException:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.warning(f"Timeout calling {url} after {self.timeout}s")
            return {
                "healthy": False,
                "status_code": None,
                "latency_ms": latency_ms,
                "endpoint": url,
                "payload": {},
                "error": f"HTTP request timed out after {self.timeout}s",
            }
        except Exception as e:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.error(f"Unexpected health check failure for {url}: {e}")
            return {
                "healthy": False,
                "status_code": None,
                "latency_ms": latency_ms,
                "endpoint": url,
                "payload": {},
                "error": str(e),
            }

    def check_http_health_sync(self, path: str = "/health") -> Dict[str, Any]:
        """Synchronous version of HTTP health check."""
        url = f"{self.service_url}{path}"
        start_time = time.perf_counter()

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(url)
                latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
                is_healthy = response.status_code == 200

                payload = {}
                try:
                    payload = response.json()
                except Exception:
                    payload = {"raw": response.text[:200]}

                return {
                    "healthy": is_healthy,
                    "status_code": response.status_code,
                    "latency_ms": latency_ms,
                    "endpoint": url,
                    "payload": payload,
                    "error": None if is_healthy else f"HTTP {response.status_code}",
                }
        except httpx.ConnectError:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return {
                "healthy": False,
                "status_code": None,
                "latency_ms": latency_ms,
                "endpoint": url,
                "payload": {},
                "error": "Connection refused / Service unreachable",
            }
        except httpx.TimeoutException:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return {
                "healthy": False,
                "status_code": None,
                "latency_ms": latency_ms,
                "endpoint": url,
                "payload": {},
                "error": f"HTTP request timed out after {self.timeout}s",
            }
        except Exception as e:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return {
                "healthy": False,
                "status_code": None,
                "latency_ms": latency_ms,
                "endpoint": url,
                "payload": {},
                "error": str(e),
            }
