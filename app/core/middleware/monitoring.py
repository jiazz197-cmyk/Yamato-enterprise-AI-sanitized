import logging
import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.integrations.monitoring.prometheus import metrics

logger = logging.getLogger(__name__)


class MonitoringMiddleware(BaseHTTPMiddleware):
    """监控中间件"""

    async def dispatch(self, request: Request, call_next):
        # 记录请求开始时间
        start_time = time.time()

        try:
            # 处理请求
            response = await call_next(request)

            # 计算请求处理时间
            process_time = time.time() - start_time

            # 记录请求指标
            metrics.record_request(
                method=request.method,
                endpoint=request.url.path,
                status_code=response.status_code,
                duration=process_time
            )

            # 添加处理时间到响应头
            response.headers["X-Process-Time"] = str(process_time)

            return response

        except Exception as e:
            # 记录异常
            logger.error(f"Request failed: {str(e)}", exc_info=True)

            # 记录失败的请求指标
            metrics.record_request(
                method=request.method,
                endpoint=request.url.path,
                status_code=500,
                duration=time.time() - start_time
            )

            # 重新抛出异常
            raise
