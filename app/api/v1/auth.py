"""登录、当前用户、注册与 superuser 用户管理。"""
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.adapters.auth import BcryptPasswordHasherAdapter, SqlAlchemyUserRepositoryAdapter
from app.core.dependencies import get_db
from app.core.exceptions import AuthenticationError, NotFoundError, PermissionDeniedError
from app.core.logging import get_logger
from app.core.security import get_current_user, require_roles, create_access_token
from app.ports.contracts.identity import CurrentUserPort, ROLE_SUPERUSER
from app.ports.dto.auth import LoginCommand, RegisterCommand, UpdateUserRoleCommand, UserDTO
from app.schemas.platform.token import TokenResponse
from app.schemas.platform.user import UserLogin, UserRead, UserRoleUpdate, UserRegister
from app.usecases.auth import (
    DeleteUserUseCase,
    GetUserUseCase,
    ListUsersUseCase,
    LoginUseCase,
    RegisterUseCase,
    UpdateUserRoleUseCase,
)

router = APIRouter()
logger = get_logger("security.auth")

_user_repo = SqlAlchemyUserRepositoryAdapter()
_password_hasher = BcryptPasswordHasherAdapter()


def _dto_to_user_read(dto: UserDTO) -> UserRead:
    return UserRead(
        id=uuid.UUID(dto.id) if dto.id else uuid.uuid4(),
        username=dto.username,
        name=dto.name,
        email=dto.email,
        phone=dto.phone,
        department=dto.department,
        avatar=dto.avatar,
        is_active=dto.is_active,
        role=dto.role,
        roles=[],
    )


@router.post("/login", response_model=TokenResponse, summary="用户登录")
def login(body: UserLogin, db: Session = Depends(get_db)):
    """校验账号密码，返回 JWT。"""
    try:
        uc = LoginUseCase(_user_repo, _password_hasher)
        result = uc.execute(LoginCommand(username=body.username, password=body.password))
        return result
    except AuthenticationError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail=e.message,
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.get("/me", response_model=UserRead, summary="获取当前用户信息")
def get_me(current_user: CurrentUserPort = Depends(get_current_user)):
    """当前登录用户信息。"""
    uc = GetUserUseCase(_user_repo)
    dto = uc.execute(current_user.id)
    return _dto_to_user_read(dto)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED, summary="用户注册")
def register(body: UserRegister, db: Session = Depends(get_db)):
    """新用户，角色固定为 user。"""
    try:
        uc = RegisterUseCase(_user_repo, _password_hasher)
        dto = uc.execute(RegisterCommand(
            username=body.username,
            email=str(body.email),
            password=body.password,
            name=body.name,
        ))
        return _dto_to_user_read(dto)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"注册失败: {e}")


@router.get(
    "/users",
    response_model=List[UserRead],
    summary="获取所有用户列表（仅 superuser）",
)
def list_users(
    db: Session = Depends(get_db),
    _: CurrentUserPort = Depends(require_roles(ROLE_SUPERUSER)),
):
    """全量用户列表，需 superuser。"""
    uc = ListUsersUseCase(_user_repo)
    dtos = uc.execute()
    return [_dto_to_user_read(d) for d in dtos]


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除用户（仅 superuser）",
)
def delete_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUserPort = Depends(require_roles(ROLE_SUPERUSER)),
):
    """按 UUID 删除；不能删自己。"""
    if str(user_id) == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )
    try:
        uc = DeleteUserUseCase(_user_repo, current_user)
        uc.execute(str(user_id))
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=e.message)


@router.patch(
    "/users/{user_id}/role",
    response_model=UserRead,
    summary="修改用户角色（仅 superuser）",
)
def update_user_role(
    user_id: uuid.UUID,
    body: UserRoleUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUserPort = Depends(require_roles(ROLE_SUPERUSER)),
):
    """改角色为 admin/user；不可授予 superuser，不可改自己。"""
    if str(user_id) == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change your own role",
        )
    try:
        uc = UpdateUserRoleUseCase(_user_repo)
        dto = uc.execute(UpdateUserRoleCommand(
            target_user_id=str(user_id),
            new_role=str(body.role.value if hasattr(body.role, "value") else body.role),
            current_user_id=current_user.id,
            current_user_name=current_user.username,
        ))
        return _dto_to_user_read(dto)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=e.message)
