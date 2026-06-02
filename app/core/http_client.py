"""Shared httpx.AsyncClient singleton: connection pooling, timeouts, lifecycle."""

from __future__ import annotations

import httpx

from app.core.config import settings


class HttpClientManager:
    _instance: httpx.AsyncClient | None = None

    @classmethod
    async def get(cls) -> httpx.AsyncClient:
        if cls._instance is None or cls._instance.is_closed:
            cls._instance = httpx.AsyncClient(
                timeout=httpx.Timeout(settings.HTTP_CLIENT_TIMEOUT, connect=10.0),
                limits=httpx.Limits(
                    max_connections=settings.HTTP_CLIENT_MAX_CONNECTIONS,
                    max_keepalive_connections=settings.HTTP_CLIENT_MAX_KEEPALIVE,
                ),
            )
        return cls._instance

    @classmethod
    async def close(cls) -> None:
        if cls._instance and not cls._instance.is_closed:
            await cls._instance.aclose()
            cls._instance = None


async def get_http_client() -> httpx.AsyncClient:
    return await HttpClientManager.get()
