"""
请求体大小限制中间件
"""
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.logging import request_logger


class RequestSizeLimit:
    """封装请求体大小校验逻辑。"""

    def __init__(self):
        self.json_limit = settings.MAX_JSON_SIZE
        self.file_limit = settings.MAX_FILE_SIZE

    async def check_request_size(self, request: Request) -> bool:
        """返回 True 表示符合限制。"""
        try:
            content_length = request.headers.get("content-length")
            if not content_length:
                return True

            content_length = int(content_length)
            content_type = request.headers.get("content-type", "")

            if "multipart/form-data" in content_type:
                if content_length > self.file_limit:
                    request_logger.warning(
                        "File upload size %s exceeds limit %s", content_length, self.file_limit
                    )
                    return False
            elif "application/json" in content_type:
                if content_length > self.json_limit:
                    request_logger.warning(
                        "JSON request size %s exceeds limit %s", content_length, self.json_limit
                    )
                    return False

            return True
        except Exception as exc:
            request_logger.error("Request size check failed: %s", exc)
            return True


class RequestSizeMiddleware(BaseHTTPMiddleware):
    """应用层中间件，用于拦截超限请求。"""

    def __init__(self, app):
        super().__init__(app)
        self.limiter = RequestSizeLimit()

    async def dispatch(self, request: Request, call_next: Callable):
        if not settings.ENABLE_REQUEST_SIZE_LIMIT:
            return await call_next(request)

        if not await self.limiter.check_request_size(request):
            return JSONResponse(
                status_code=413,
                content={"code": 413, "message": "请求体过大", "data": None},
            )

        return await call_next(request)
