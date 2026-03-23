"""
安全工具：API Key / JWT / 密码哈希

使用方式:
    # API Key 保护
    from app.core.security import require_api_key

    @router.get("/protected", dependencies=[Depends(require_api_key())])
    async def protected_endpoint():
        return {"message": "Access granted"}

    # JWT 保护
    from app.core.security import get_current_user

    @router.get("/me")
    def me(current_user = Depends(get_current_user)):
        return current_user

    # 角色保护
    from app.core.security import require_roles
    from app.models.orm.platform.user import UserRole

    @router.delete("/users/{user_id}")
    def delete_user(current_user = Depends(require_roles(UserRole.superuser))):
        ...
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import OAuth2PasswordBearer
from fastapi.security.api_key import APIKeyHeader
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_db

# ==================== Password Hashing ====================


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


# ==================== JWT ====================

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    """Create a signed JWT access token with UUID subject."""
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {"sub": str(subject), "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    """FastAPI dependency: decode Bearer token and return User ORM object."""
    from app.models.orm.platform.user import User

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        user_uuid = uuid.UUID(user_id)
    except (jwt.PyJWTError, ValueError):
        raise credentials_exception

    user = db.query(User).filter(User.id == user_uuid).first()
    if user is None or not user.is_active:
        raise credentials_exception
    return user


def require_roles(*roles: "UserRole") -> Callable:
    """Return a FastAPI dependency that enforces one of the given roles."""
    from app.models.orm.platform.user import UserRole

    def dependency(current_user=Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return dependency


# ==================== API Key ====================

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
