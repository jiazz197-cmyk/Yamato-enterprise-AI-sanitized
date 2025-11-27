"""
基于 Redis 的限流中间件
"""
import time
from typing import Callable, Tuple

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.cache import redis_manager
from app.core.config import settings
from app.core.logging import request_logger


class RateLimiter:
    """按认证状态区分限流，使用滑动窗口。"""

    def __init__(self):
        self.auth_limit = settings.RATE_LIMIT_AUTH
        self.anon_limit = settings.RATE_LIMIT_ANON
        self.window_size = settings.RATE_LIMIT_WINDOW

    async def _get_client_identifier(self, request: Request) -> Tuple[str, bool]:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            # 实际项目中应解析 token 获取用户 ID；此处用 IP 代替
            user_id = request.client.host
            return f"auth:{user_id}", True
        client_ip = request.client.host
        return f"anon:{client_ip}", False

    async def check_rate_limit(self, request: Request) -> bool:
        identifier, is_authenticated = await self._get_client_identifier(request)
        limit = self.auth_limit if is_authenticated else self.anon_limit
        current_time = int(time.time())
        window_key = f"rate_limit:{identifier}:{current_time // self.window_size}"

        count = await redis_manager.redis_client.incr(window_key)
        if count == 1:
            await redis_manager.redis_client.expire(window_key, self.window_size)

        if count > limit:
            request_logger.warning("Rate limit exceeded for %s", identifier)
            return False
        return True


class RateLimitMiddleware(BaseHTTPMiddleware):
    """在 FastAPI 中应用限流策略。"""

    def __init__(self, app):
        super().__init__(app)
        self.limiter = RateLimiter()

    async def dispatch(self, request: Request, call_next: Callable):
        if not settings.ENABLE_RATE_LIMIT:
            return await call_next(request)

        if not await self.limiter.check_rate_limit(request):
            return JSONResponse(
                status_code=429,
                content={"code": 429, "message": "请求过于频繁，请稍后再试", "data": None},
            )

        return await call_next(request)
