"""Shared access checks for executor-backed tasks."""

from __future__ import annotations

from typing import Any, Optional

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models.orm.platform.user import User, UserRole


def ensure_executor_task_exists(future: Optional[Any], *, not_found_message: str = "任务不存在") -> None:
    if not future:
        raise NotFoundError(not_found_message)


def ensure_task_owner_or_superuser(
    current_user: User,
    owner_id: str,
    *,
    detail: str,
) -> None:
    if current_user.role != UserRole.superuser and owner_id != str(current_user.id):
        raise PermissionDeniedError(detail)
