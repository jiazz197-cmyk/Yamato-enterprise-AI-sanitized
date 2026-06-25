"""API Key、JWT、密码哈希及角色依赖。"""
import uuid
from datetime import timedelta
from typing import Any, Callable

from app.core.time_utils import utcnow

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.dependencies import get_async_db
from app.core.rbac_queries import load_user_permissions
from app.ports.contracts.identity import CurrentUserDTO

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")


def hash_password(password: str) -> str:
    """bcrypt 哈希明文密码。"""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验明文与 bcrypt 哈希是否匹配。"""
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


def create_access_token(
    subject: str,
    expires_delta: timedelta | None = None,
    role: str | None = None,
) -> str:
    """签发 JWT，sub 为 UUID 字符串。

    role 非空时写入 ``role`` claim，供限流中间件按角色分级（无需 DB 查询）。
    鉴权仍以 ``sub`` + DB 权威查询为准（见 get_current_user），role claim 仅用于限流分档。
    """
    expire = utcnow() + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload: dict[str, Any] = {"sub": str(subject), "exp": expire}
    if role is not None:
        payload["role"] = role
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _orm_to_dto(user, permissions: list[str] | None = None) -> CurrentUserDTO:
    """Map SQLAlchemy User ORM to CurrentUserDTO."""
    return CurrentUserDTO(
        id=str(user.id),
        username=str(user.username or ""),
        name=str(user.name or ""),
        role=str(user.role.value if hasattr(user.role, "value") else user.role),
        permissions=permissions or [],
    )


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_async_db),
) -> CurrentUserDTO:
    """解析 Bearer，返回 CurrentUserDTO；无效则 401。"""
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

    result = await db.execute(select(User).filter(User.id == user_uuid))
    user = result.scalars().first()
    if user is None or not user.is_active:
        raise credentials_exception
    perms = await load_user_permissions(db, user.id)
    return _orm_to_dto(user, perms)


async def get_current_user_detached(token: str = Depends(oauth2_scheme)) -> CurrentUserDTO:
    """解析 Bearer 并立即关闭 DB session；适合慢接口避免长时间占用连接。"""
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

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).filter(User.id == user_uuid))
        user = result.scalars().first()
        if user is None or not user.is_active:
            raise credentials_exception
        perms = await load_user_permissions(db, user.id)
        db.expunge(user)
        return _orm_to_dto(user, perms)


def _normalize_identifier(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def get_user_aliases(user: object) -> set[str]:
    """返回当前用户可接受的身份别名（UUID / username / name）。"""
    aliases = {
        _normalize_identifier(getattr(user, "id", "")),
        _normalize_identifier(getattr(user, "username", "")),
        _normalize_identifier(getattr(user, "name", "")),
    }
    aliases.discard("")
    return aliases


def normalize_self_user_identifier(raw_identifier: str, current_user: object) -> str:
    """
    仅允许当前登录用户使用自己的 UUID / username / 中文姓名标识自己。
    返回规范化后的 UUID 字符串。
    """
    normalized = _normalize_identifier(raw_identifier)
    aliases = get_user_aliases(current_user)

    if normalized in aliases:
        return _normalize_identifier(getattr(current_user, "id", ""))

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="无权访问其他用户资源",
    )


def normalize_self_uploader(raw_uploader: str, current_user: object) -> str:
    """
    仅允许当前用户以自身别名上传，统一落库为 username（便于权限一致性）。
    """
    normalize_self_user_identifier(raw_uploader, current_user)
    username = _normalize_identifier(getattr(current_user, "username", ""))
    if not username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前用户缺少 username，无法执行该操作",
        )
    return username


def require_roles(*roles: str) -> Callable:
    """要求当前用户角色在指定集合内。"""

    def dependency(current_user=Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return dependency


def require_permission(perm: str) -> Callable:
    """要求当前用户拥有指定权限（admin/superuser 自动放行）。"""

    def dependency(current_user=Depends(get_current_user)):
        if not current_user.has_permission(perm):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return dependency
