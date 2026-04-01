"""
监控中间件：记录请求耗时并上报 Prometheus
"""
import time
from typing import Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import get_logger
from app.integrations.monitoring.prometheus import metrics

logger = get_logger("monitoring")


def _normalize_endpoint(request: Request) -> str:
    """Use route template to avoid high-cardinality metric labels."""
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if isinstance(route_path, str) and route_path:
        return route_path
    return request.url.path


class MonitoringMiddleware(BaseHTTPMiddleware):
    """记录请求耗时、状态并写入 metrics。"""

    async def dispatch(self, request: Request, call_next: Callable):
        start_time = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration = time.perf_counter() - start_time
            logger.exception("Request failed: %s %s", request.method, request.url.path)
            metrics.record_request(
                method=request.method,
                endpoint=_normalize_endpoint(request),
                status_code=500,
                duration=duration,
            )
            raise

        duration = time.perf_counter() - start_time
        metrics.record_request(
            method=request.method,
            endpoint=_normalize_endpoint(request),
            status_code=response.status_code,
            duration=duration,
        )
        response.headers["X-Process-Time"] = f"{duration:.6f}"
        return response
