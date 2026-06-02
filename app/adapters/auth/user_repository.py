"""User repository adapter encapsulating SQLAlchemy User ORM."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.ports.domains.auth import UserRepositoryPort
from app.ports.dto.auth import UserDTO


def _orm_user_to_dto(user) -> UserDTO:
    """Map ORM User to UserDTO."""
    return UserDTO(
        id=str(user.id),
        username=str(user.username or ""),
        email=str(user.email or ""),
        name=str(user.name) if user.name else None,
        role=str(user.role.value if hasattr(user.role, "value") else user.role),
        is_active=bool(user.is_active),
        created_at=str(user.created_at) if user.created_at else "",
        phone=str(user.phone) if user.phone else None,
        department=str(user.department) if user.department else None,
        avatar=str(user.avatar) if user.avatar else None,
    )


class SqlAlchemyUserRepositoryAdapter(UserRepositoryPort):
    """SQLAlchemy-backed user repository (async session per method)."""

    async def get_by_username(self, username: str) -> Optional[object]:
        from app.models.orm.platform.user import User

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User).filter(User.username == username))
            return result.scalars().first()

    async def get_by_id(self, user_id: str) -> Optional[UserDTO]:
        from app.models.orm.platform.user import User

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(User).filter(User.id == uuid.UUID(user_id))
            )
            user = result.scalars().first()
            return _orm_user_to_dto(user) if user else None

    async def create(
        self, username: str, email: str, password: str, name: Optional[str]
    ) -> UserDTO:
        from app.models.orm.platform.user import User, UserRole

        async with AsyncSessionLocal() as db:
            user = User(
                username=username,
                email=email,
                password=password,
                name=name,
                role=UserRole.user,
                is_active=True,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            return _orm_user_to_dto(user)

    async def list_users(self) -> list[UserDTO]:
        from app.models.orm.platform.user import User

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User).order_by(User.created_at))
            users = result.scalars().all()
            return [_orm_user_to_dto(u) for u in users]

    async def delete(self, user_id: str) -> None:
        from app.models.orm.platform.user import User

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(User).filter(User.id == uuid.UUID(user_id))
            )
            user = result.scalars().first()
            if user:
                await db.delete(user)
                await db.commit()

    async def update_role(self, user_id: str, role: str) -> UserDTO:
        from app.models.orm.platform.user import User, UserRole

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(User).filter(User.id == uuid.UUID(user_id))
            )
            user = result.scalars().first()
            if not user:
                raise ValueError(f"User not found: {user_id}")
            role_map = {r.value: r for r in UserRole}
            user.role = role_map.get(role, UserRole.user)
            await db.commit()
            await db.refresh(user)
            return _orm_user_to_dto(user)
