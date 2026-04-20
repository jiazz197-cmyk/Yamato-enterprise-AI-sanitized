"""另一套 GET 响应 Redis 缓存中间件（与 middleware_cache 并存时注意只启用其一）。"""
import json
from typing import Callable, Optional

from fastapi import Request, Response, FastAPI
from fastapi.responses import StreamingResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.cache import redis_manager
from app.core.config import settings
from app.core.logging import logger


class CacheMiddleware(BaseHTTPMiddleware):
    """仅缓存 GET JSON 200；流式响应跳过。"""

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
        if not settings.ENABLE_CACHE:
            return await call_next(request)

        if not self._should_cache(request):
            return await call_next(request)

        cache_key = self._generate_cache_key(request)

        try:
            cached_response = await self._get_cached_response(cache_key)
            if cached_response:
                logger.debug(f"Cache hit for {cache_key}")
                return cached_response
        except Exception as e:
            logger.error(f"Failed to get cached response: {e}")

        response = await call_next(request)

        try:
            if response.status_code == 200:
                await self._cache_response(cache_key, response)
        except Exception as e:
            logger.error(f"Failed to cache response for {cache_key}: {e}")

        return response

    def _should_cache(self, request: Request) -> bool:
        """GET 且非排除路径且未要求 no-store。"""
        if request.method != "GET":
            return False

        if request.url.path in self.excluded_paths:
            return False

        cache_control = request.headers.get("Cache-Control", "")
        if "no-cache" in cache_control or "no-store" in cache_control:
            return False

        return True

    def _generate_cache_key(self, request: Request) -> str:
        """path + querystring。"""
        key_parts = [request.url.path]
        if request.query_params:
            key_parts.append(str(request.query_params))
        return f"cache:{':'.join(key_parts)}"

    async def _get_cached_response(self, cache_key: str) -> Optional[Response]:
        """反序列化为 JSONResponse。"""
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
        """只存 JSON 可解析的 body；异常吞掉不打断响应。"""
        try:
            if isinstance(response, StreamingResponse):
                logger.debug(f"Skipping cache for streaming response: {cache_key}")
                return

            if response.status_code != 200:
                return

            body = b""
            if hasattr(response, "body") and response.body:
                body = response.body
            elif hasattr(response, "body_iterator"):
                try:
                    chunks = []
                    async for chunk in response.body_iterator:
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    response.body_iterator = iter(chunks)
                except Exception as e:
                    logger.debug(f"Failed to read response body for caching: {e}")
                    return

            if not body:
                return

            try:
                content = json.loads(body) if body else None
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.debug(f"Response body is not valid JSON, skipping cache: {e}")
                return

            cache_data = {
                "content": content,
                "status_code": response.status_code,
                "headers": {k: v for k, v in response.headers.items() if
                            k.lower() not in ['content-length', 'transfer-encoding']}
            }

            await redis_manager.set(
                cache_key,
                json.dumps(cache_data),
                ttl=self.cache_ttl
            )
            logger.debug(f"Response cached successfully: {cache_key}")

        except Exception as e:
            logger.error(f"Failed to cache response: {e}")


async def cache_middleware(request: Request, call_next: Callable) -> Response:
    """独立入口：逻辑与 CacheMiddleware.dispatch 类似。"""
    redis_client = request.app.state.redis
    cache = CacheMiddleware(request.app)

    cached_response = await cache._get_cached_response(cache._generate_cache_key(request))
    if cached_response:
        return cached_response

    response = await call_next(request)

    if response.status_code == 200:
        try:
            await cache._cache_response(cache._generate_cache_key(request), response)
        except Exception as e:
            logger.error(f"Failed to cache response: {e}")

    return response
