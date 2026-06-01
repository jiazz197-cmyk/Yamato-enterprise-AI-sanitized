"""Login use case."""

from __future__ import annotations

from app.core.exceptions import AuthenticationError
from app.core.logging import get_logger
from app.core.security import create_access_token
from app.ports.domains.auth import PasswordHasherPort, UserRepositoryPort
from app.ports.dto.auth import LoginCommand, TokenPair

logger = get_logger("auth.login")


class LoginUseCase:
    """Authenticate user credentials and return JWT token."""

    def __init__(self, user_repo: UserRepositoryPort, password_hasher: PasswordHasherPort):
        self._user_repo = user_repo
        self._password_hasher = password_hasher

    def execute(self, cmd: LoginCommand) -> TokenPair:
        user = self._user_repo.get_by_username(cmd.username)
        if not user:
            raise AuthenticationError("用户名或密码错误")

        if not getattr(user, "is_active", True):
            raise AuthenticationError("账号已禁用")

        password_hash = getattr(user, "password", "")
        if not self._password_hasher.verify_password(cmd.password, password_hash):
            raise AuthenticationError("用户名或密码错误")

        user_id = str(getattr(user, "id", ""))
        access_token = create_access_token(subject=user_id)
        logger.info("User logged in: %s (id=%s)", getattr(user, "username", ""), user_id)
        return TokenPair(access_token=access_token)
