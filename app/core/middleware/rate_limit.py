"""
基于 Redis 的限流中间件
"""
import time
from typing import Callable, Tuple

from fastapi import Request
from fastapi.responses import JSONResponse
import jwt
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.cache import redis_manager
from app.core.config import settings
from app.core.logging import request_logger


class RateLimiter:
    """按认证状态区分限流，使用滑动窗口。"""

    def __init__(self):
        self.auth_limit = settings.RATE_LIMIT_AUTH
        self.anon_limit = settings.RATE_LIMIT_ANON
        self.expensive_auth_limit = settings.RATE_LIMIT_EXPENSIVE_AUTH
        self.expensive_anon_limit = settings.RATE_LIMIT_EXPENSIVE_ANON
        self.window_size = settings.RATE_LIMIT_WINDOW
        self.expensive_path_prefixes = (
            f"{settings.API_V1_STR}/retriever",
            f"{settings.API_V1_STR}/chat-summary",
            f"{settings.API_V1_STR}/context-compression",
        )

    async def _get_client_identifier(self, request: Request) -> Tuple[str, bool]:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()
            if token:
                try:
                    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
                    user_id = str(payload.get("sub", "")).strip()
                    if user_id:
                        return f"auth:{user_id}", True
                except jwt.PyJWTError:
                    # fallback to IP bucket when token is invalid
                    pass
        client_ip = request.client.host
        return f"anon:{client_ip}", False

    def _get_limit_for_request(self, request: Request, is_authenticated: bool) -> int:
        if request.url.path.startswith(self.expensive_path_prefixes):
            return self.expensive_auth_limit if is_authenticated else self.expensive_anon_limit
        return self.auth_limit if is_authenticated else self.anon_limit

    async def check_rate_limit(self, request: Request) -> bool:
        identifier, is_authenticated = await self._get_client_identifier(request)
        limit = self._get_limit_for_request(request, is_authenticated)
        current_time = int(time.time())
        window_key = f"rate_limit:{identifier}:{current_time // self.window_size}"

        try:
            count = await redis_manager.redis_client.incr(window_key)
            if count == 1:
                await redis_manager.redis_client.expire(window_key, self.window_size)
        except Exception as exc:
            request_logger.warning("Rate limiter fallback due to Redis error: %s", exc)
            return True

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
