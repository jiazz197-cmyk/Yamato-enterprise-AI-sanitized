import json
from typing import Callable, Optional

from fastapi import Request, Response, FastAPI
from fastapi.responses import StreamingResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.cache import redis_manager
from app.core.config import settings
from app.core.logging import logger


class CacheMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI):
        super().__init__(app)
        self.redis_client = redis_manager.redis_client
        self.cache_ttl = settings.CACHE_TTL
        self.excluded_paths = {
            "/api/v1/health",
            "/api/v1/metrics",
            "/api/v1/docs",
            "/api/v1/openapi.json",
            "/api/v1/redoc"
        }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 检查是否启用缓存
        if not settings.ENABLE_CACHE:
            return await call_next(request)

        # 检查是否应该缓存此请求
        if not self._should_cache(request):
            return await call_next(request)

        # 生成缓存键
        cache_key = self._generate_cache_key(request)

        # 尝试从缓存获取响应
        try:
            cached_response = await self._get_cached_response(cache_key)
            if cached_response:
                logger.debug(f"Cache hit for {cache_key}")
                return cached_response
        except Exception as e:
            logger.error(f"Failed to get cached response: {e}")

        # 获取新响应
        response = await call_next(request)

        # 尝试缓存响应（异步，不阻塞响应）
        try:
            # 只在响应成功时尝试缓存
            if response.status_code == 200:
                await self._cache_response(cache_key, response)
        except Exception as e:
            logger.error(f"Failed to cache response for {cache_key}: {e}")
            # 不要重新抛出异常，确保不影响正常响应

        return response

    def _should_cache(self, request: Request) -> bool:
        """检查是否应该缓存此请求"""
        # 只缓存GET请求
        if request.method != "GET":
            return False

        # 检查路径是否在排除列表中
        if request.url.path in self.excluded_paths:
            return False

        # 检查缓存控制头
        cache_control = request.headers.get("Cache-Control", "")
        if "no-cache" in cache_control or "no-store" in cache_control:
            return False

        return True

    def _generate_cache_key(self, request: Request) -> str:
        """生成缓存键"""
        # 使用请求路径和查询参数作为键
        key_parts = [request.url.path]
        if request.query_params:
            key_parts.append(str(request.query_params))
        return f"cache:{':'.join(key_parts)}"

    async def _get_cached_response(self, cache_key: str) -> Optional[Response]:
        """从缓存获取响应"""
        try:
            cached_data = await redis_manager.get(cache_key)
            if cached_data:
                data = json.loads(cached_data)
                return JSONResponse(
                    content=data["content"],
                    status_code=data["status_code"],
                    headers=data["headers"]
                )
        except Exception as e:
            logger.error(f"Failed to get cached response: {e}")
        return None

    async def _cache_response(self, cache_key: str, response: Response) -> None:
        """缓存响应"""
        try:
            # 检查响应类型，跳过不适合缓存的响应
            if isinstance(response, StreamingResponse):
                logger.debug(f"Skipping cache for streaming response: {cache_key}")
                return

            # 只缓存成功的响应
            if response.status_code != 200:
                return

            # 安全获取响应内容
            body = b""
            if hasattr(response, "body") and response.body:
                body = response.body
            elif hasattr(response, "body_iterator"):
                try:
                    chunks = []
                    async for chunk in response.body_iterator:
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    # 重新设置body_iterator以供后续使用
                    response.body_iterator = iter(chunks)
                except Exception as e:
                    logger.debug(f"Failed to read response body for caching: {e}")
                    return

            # 如果没有body内容，跳过缓存
            if not body:
                return

            # 尝试解析JSON内容
            try:
                content = json.loads(body) if body else None
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.debug(f"Response body is not valid JSON, skipping cache: {e}")
                return

            # 准备缓存数据
            cache_data = {
                "content": content,
                "status_code": response.status_code,
                "headers": {k: v for k, v in response.headers.items() if
                            k.lower() not in ['content-length', 'transfer-encoding']}
            }

            # 存储到Redis
            await redis_manager.set(
                cache_key,
                json.dumps(cache_data),
                ttl=self.cache_ttl
            )
            logger.debug(f"Response cached successfully: {cache_key}")

        except Exception as e:
            logger.error(f"Failed to cache response: {e}")
            # 不要重新抛出异常，避免影响正常响应


async def cache_middleware(request: Request, call_next: Callable) -> Response:
    """缓存中间件"""
    # 获取Redis客户端
    redis_client = request.app.state.redis
    cache = CacheMiddleware(request.app)

    # 尝试获取缓存的响应
    cached_response = await cache._get_cached_response(cache._generate_cache_key(request))
    if cached_response:
        return cached_response

    # 如果没有缓存，处理请求
    response = await call_next(request)

    # 如果响应成功，尝试缓存
    if response.status_code == 200:
        try:
            await cache._cache_response(cache._generate_cache_key(request), response)
        except Exception as e:
            logger.error(f"Failed to cache response: {e}")

    return response
