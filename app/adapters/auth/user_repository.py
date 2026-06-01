"""User repository adapter encapsulating SQLAlchemy User ORM."""

from __future__ import annotations

import uuid
from typing import Optional

from app.core.database import SessionLocal
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
    """SQLAlchemy-backed user repository.

    Each method opens and closes its own session.
    """

    def get_by_username(self, username: str) -> Optional[object]:
        from app.models.orm.platform.user import User

        db = SessionLocal()
        try:
            return db.query(User).filter(User.username == username).first()
        finally:
            db.close()

    def get_by_id(self, user_id: str) -> Optional[UserDTO]:
        from app.models.orm.platform.user import User

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
            return _orm_user_to_dto(user) if user else None
        finally:
            db.close()

    def create(self, username: str, email: str, password: str, name: Optional[str]) -> UserDTO:
        from app.models.orm.platform.user import User, UserRole

        db = SessionLocal()
        try:
            user = User(
                username=username,
                email=email,
                password=password,
                name=name,
                role=UserRole.user,
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return _orm_user_to_dto(user)
        finally:
            db.close()

    def list_users(self) -> list[UserDTO]:
        from app.models.orm.platform.user import User

        db = SessionLocal()
        try:
            users = db.query(User).order_by(User.created_at).all()
            return [_orm_user_to_dto(u) for u in users]
        finally:
            db.close()

    def delete(self, user_id: str) -> None:
        from app.models.orm.platform.user import User

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
            if user:
                db.delete(user)
                db.commit()
        finally:
            db.close()

    def update_role(self, user_id: str, role: str) -> UserDTO:
        from app.models.orm.platform.user import User, UserRole

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
            if not user:
                raise ValueError(f"User not found: {user_id}")
            # Map string role to UserRole enum
            role_map = {r.value: r for r in UserRole}
            user.role = role_map.get(role, UserRole.user)
            db.commit()
            db.refresh(user)
            return _orm_user_to_dto(user)
        finally:
            db.close()
