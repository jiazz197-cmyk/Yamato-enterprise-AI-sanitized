"""Auth subsystem ports: user repository, authentication, password hashing."""

from __future__ import annotations

from typing import Optional, Protocol


class UserRepositoryPort(Protocol):
    """Persistence boundary for user CRUD operations."""

    def get_by_username(self, username: str) -> Optional[object]:
        ...

    def get_by_id(self, user_id: str) -> Optional[object]:
        ...

    def create(self, username: str, email: str, password: str, name: Optional[str]) -> object:
        ...

    def list_users(self) -> list[object]:
        ...

    def delete(self, user_id: str) -> None:
        ...

    def update_role(self, user_id: str, role: str) -> object:
        ...


class PasswordHasherPort(Protocol):
    """Abstraction for password hashing and verification."""

    def hash_password(self, password: str) -> str:
        ...

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        ...


class AuthPort(Protocol):
    """Authentication service boundary."""

    def authenticate(self, username: str, password: str) -> object:
        ...

    def register(self, username: str, email: str, password: str, name: Optional[str]) -> object:
        ...

    def create_tokens(self, user_id: str) -> dict:
        ...
