import time
from typing import Tuple, Callable

import redis.asyncio as redis
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.logging import logger


class RateLimiter:
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        # 从配置中读取限流设置
        self.auth_limit = settings.RATE_LIMIT_AUTH
        self.anon_limit = settings.RATE_LIMIT_ANON
        self.window_size = settings.RATE_LIMIT_WINDOW

    async def _get_client_identifier(self, request: Request) -> Tuple[str, bool]:
        """获取客户端标识符和认证状态"""
        # 检查是否有认证token
        auth_header = request.headers.get("Authorization")
        is_authenticated = bool(auth_header and auth_header.startswith("Bearer "))

        if is_authenticated:
            # 从token中提取用户ID
            # 这里需要根据您的token实现来修改
            user_id = "user_id_from_token"  # 示例
            return f"auth:{user_id}", True
        else:
            # 使用IP地址作为未认证用户的标识
            client_ip = request.client.host
            return f"anon:{client_ip}", False

    async def check_rate_limit(self, request: Request) -> bool:
        """检查是否超过速率限制"""
        try:
            client_id, is_authenticated = await self._get_client_identifier(request)
            limit = self.auth_limit if is_authenticated else self.anon_limit

            # 使用Redis的滑动窗口实现限流
            current_time = int(time.time())
            window_key = f"rate_limit:{client_id}:{current_time // self.window_size}"

            # 使用Redis的INCR命令增加计数器
            count = await self.redis.incr(window_key)
            if count == 1:
                # 设置过期时间
                await self.redis.expire(window_key, self.window_size)

            # 检查是否超过限制
            if count > limit:
                logger.warning(f"Rate limit exceeded for {client_id}")
                return False

            return True

        except Exception as e:
            logger.error(f"Rate limit check failed: {e}")
            return True  # 发生错误时默认允许请求通过


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.redis_client = None

    async def dispatch(self, request: Request, call_next: Callable):
        # 检查是否启用限流
        if not settings.ENABLE_RATE_LIMIT:
            return await call_next(request)

        # 获取Redis客户端
        if not self.redis_client:
            self.redis_client = getattr(request.app.state, 'redis', None)

        # 如果没有Redis连接，跳过限流
        if not self.redis_client:
            logger.warning("Redis not available, skipping rate limit check")
            return await call_next(request)

        # 创建限流器实例
        limiter = RateLimiter(self.redis_client)

        # 检查速率限制
        if not await limiter.check_rate_limit(request):
            return JSONResponse(
                status_code=429,
                content={
                    "code": 429,
                    "message": "请求过于频繁，请稍后再试",
                    "data": None
                }
            )

        # 继续处理请求
        response = await call_next(request)
        return response
