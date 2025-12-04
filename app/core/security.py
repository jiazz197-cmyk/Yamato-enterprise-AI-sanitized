"""
安全工具：API Key 依赖

使用方式:
    from app.core.security import require_api_key
    
    @router.get("/protected", dependencies=[Depends(require_api_key())])
    async def protected_endpoint():
        return {"message": "Access granted"}
"""
from typing import Callable

from fastapi import Depends, HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader

from app.core.config import settings

API_KEY_NAME = "X-API-KEY"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


async def verify_api_key(api_key_header_value: str = Security(api_key_header)) -> str:
    """验证 Header 中的 API Key。"""
    if api_key_header_value and api_key_header_value == settings.INTERNAL_API_KEY:
        return api_key_header_value
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Invalid API Key",
    )


def require_api_key() -> Callable:
    """返回 FastAPI 依赖，用于路由级别校验 API Key。"""
    async def dependency(_: str = Depends(verify_api_key)) -> str:
        return _

    return dependency
