"""
Authentication router
Provides login and current-user endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.logging import get_logger
from app.core.security import (
    verify_password,
    create_access_token,
    get_current_user,
)
from app.models.orm.platform.user import User
from app.schemas.platform.token import TokenResponse
from app.schemas.platform.user import UserLogin, UserRead

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
