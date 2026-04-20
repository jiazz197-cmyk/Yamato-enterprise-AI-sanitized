"""
Authentication router
Provides login, current-user, and superuser management endpoints.
"""
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.logging import get_logger
from app.core.security import (
    verify_password,
    hash_password,
    create_access_token,
    get_current_user,
    require_roles,
)
from app.models.orm.platform.user import User, UserRole
from app.schemas.platform.token import TokenResponse
from app.schemas.platform.user import UserLogin, UserRead, UserRoleUpdate, UserRegister

router = APIRouter()
logger = get_logger("auth")


@router.post("/login", response_model=TokenResponse, summary="用户登录")
def login(body: UserLogin, db: Session = Depends(get_db)):
    """Authenticate with username/password and receive a JWT access token."""
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    access_token = create_access_token(subject=str(user.id))
    logger.info(f"User logged in: {user.username} (id={user.id})")
    return TokenResponse(access_token=access_token, token_type="bearer")


@router.get("/me", response_model=UserRead, summary="获取当前用户信息")
def get_me(current_user: User = Depends(get_current_user)):
    """Return the profile of the currently authenticated user."""
    return current_user


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED, summary="用户注册")
def register(body: UserRegister, db: Session = Depends(get_db)):
    """Register a new account. Role is always set to user."""
    conflict = db.query(User).filter(
        or_(User.username == body.username, User.email == body.email)
    ).first()
    if conflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名或邮箱已被注册",
        )
    user = User(
        username=body.username,
        email=body.email,
        password=hash_password(body.password),
        name=body.name,
        role=UserRole.user,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info(f"New user registered: {user.username} (id={user.id})")
    return user


# ==================== Superuser Management ====================


@router.get(
    "/users",
    response_model=List[UserRead],
    summary="获取所有用户列表（仅 superuser）",
)
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.superuser)),
):
    """Return a list of all registered users. Requires superuser role."""
    return db.query(User).order_by(User.created_at).all()


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除用户（仅 superuser）",
)
def delete_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.superuser)),
):
    """Delete a user by UUID. Superuser cannot delete themselves."""
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    db.delete(user)
    db.commit()
    logger.info(f"User deleted: {user.username} (id={user.id}) by superuser {current_user.username}")


@router.patch(
    "/users/{user_id}/role",
    response_model=UserRead,
    summary="修改用户角色（仅 superuser）",
)
def update_user_role(
    user_id: uuid.UUID,
    body: UserRoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.superuser)),
):
    """
    Change a user's role. Superuser can assign admin or user roles.
    The superuser role cannot be granted through this endpoint.
    """
    if body.role == UserRole.superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot grant superuser role",
        )
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change your own role",
        )
    user.role = body.role
    db.commit()
    db.refresh(user)
    logger.info(
        f"Role updated: {user.username} (id={user.id}) → {body.role.value} "
        f"by superuser {current_user.username}"
    )
    return user
