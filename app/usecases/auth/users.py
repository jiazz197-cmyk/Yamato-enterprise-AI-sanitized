"""Admin user management use cases."""

from __future__ import annotations

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.core.logging import get_logger
from app.ports.contracts.identity import CurrentUserPort
from app.ports.domains.auth import UserRepositoryPort
from app.ports.dto.auth import UpdateUserRoleCommand, UserDTO

logger = get_logger("auth.users")


def _orm_to_dto(user: object) -> UserDTO:
    """Map repository-returned object to UserDTO."""
    return UserDTO(
        id=str(getattr(user, "id", "")),
        username=getattr(user, "username", ""),
        email=getattr(user, "email", ""),
        name=getattr(user, "name", None),
        role=getattr(user, "role", "user"),
        is_active=getattr(user, "is_active", True),
        created_at=str(getattr(user, "created_at", "")),
        phone=getattr(user, "phone", None),
        department=getattr(user, "department", None),
        avatar=getattr(user, "avatar", None),
    )


class GetUserUseCase:
    """Fetch a single user by ID."""

    def __init__(self, user_repo: UserRepositoryPort):
        self._user_repo = user_repo

    def execute(self, user_id: str) -> UserDTO:
        user = self._user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("用户不存在")
        return _orm_to_dto(user)


class ListUsersUseCase:
    """Fetch all users."""

    def __init__(self, user_repo: UserRepositoryPort):
        self._user_repo = user_repo

    def execute(self) -> list[UserDTO]:
        users = self._user_repo.list_users()
        return [_orm_to_dto(u) for u in users]


class DeleteUserUseCase:
    """Remove a user (admin-only)."""

    def __init__(self, user_repo: UserRepositoryPort, current_user: CurrentUserPort):
        self._user_repo = user_repo
        self._current_user = current_user

    def execute(self, user_id: str) -> None:
        if not self._current_user.is_admin_like():
            raise PermissionDeniedError("需要管理员权限")

        target = self._user_repo.get_by_id(user_id)
        if not target:
            raise NotFoundError("用户不存在")

        self._user_repo.delete(user_id)
        logger.info(
            "User deleted: %s by %s (id=%s)",
            user_id,
            self._current_user.username,
            self._current_user.id,
        )


class UpdateUserRoleUseCase:
    """Change a user's role (admin-only)."""

    def __init__(self, user_repo: UserRepositoryPort):
        self._user_repo = user_repo

    def execute(self, cmd: UpdateUserRoleCommand) -> UserDTO:
        user = self._user_repo.update_role(cmd.target_user_id, cmd.new_role)
        if not user:
            raise NotFoundError("用户不存在")

        logger.info(
            "User role updated: %s -> %s by %s (id=%s)",
            cmd.target_user_id,
            cmd.new_role,
            cmd.current_user_name,
            cmd.current_user_id,
        )
        return _orm_to_dto(user)
