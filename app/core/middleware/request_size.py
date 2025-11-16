from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.logging import logger


class RequestSizeLimit:
    def __init__(self):
        # 从配置中读取大小限制
        self.json_limit = settings.MAX_JSON_SIZE
        self.file_limit = settings.MAX_FILE_SIZE

    async def check_request_size(self, request: Request) -> bool:
        """检查请求大小是否超过限制"""
        try:
            content_length = request.headers.get("content-length")
            if not content_length:
                return True

            content_length = int(content_length)
            content_type = request.headers.get("content-type", "")

            # 检查文件上传
            if "multipart/form-data" in content_type:
                if content_length > self.file_limit:
                    logger.warning(f"File upload size {content_length} exceeds limit {self.file_limit}")
                    return False
            # 检查JSON请求
            elif "application/json" in content_type:
                if content_length > self.json_limit:
                    logger.warning(f"JSON request size {content_length} exceeds limit {self.json_limit}")
                    return False

            return True

        except Exception as e:
            logger.error(f"Request size check failed: {e}")
            return True


class RequestSizeMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.limiter = RequestSizeLimit()

    async def dispatch(self, request: Request, call_next: Callable):
        # 检查是否启用请求大小限制
        if not settings.ENABLE_REQUEST_SIZE_LIMIT:
            return await call_next(request)

        if not await self.limiter.check_request_size(request):
            return JSONResponse(
                status_code=413,
                content={
                    "code": 413,
                    "message": "请求体过大",
                    "data": None
                }
            )

        response = await call_next(request)
        return response
