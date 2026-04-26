"""Compress chat context for Dify variables."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

from app.core.logging import get_logger
from app.core.security import normalize_self_user_identifier
from app.models.orm.platform.user import User, UserRole
from app.ports.domains.context_compression import ContextCompressorPort

logger = get_logger("context_compression_uc")


@dataclass
class CompressContextCommand:
    user_id: str
    conversation_id: str
    n_recent: int
    current_user: User


@dataclass
class CompressContextResult:
    compressed: Any


class CompressContextUseCase:
    def __init__(self, compressor: ContextCompressorPort):
        self._compressor = compressor

    def execute(self, cmd: CompressContextCommand) -> CompressContextResult:
        decoded_user_id = unquote(cmd.user_id).strip()
        logger.info(
            "Received context compression request for conversation %s from user %s",
            cmd.conversation_id,
            decoded_user_id,
        )
        if cmd.current_user.role in (UserRole.admin, UserRole.superuser):
            effective_user_id = decoded_user_id
        else:
            normalize_self_user_identifier(decoded_user_id, cmd.current_user)
            effective_user_id = decoded_user_id

        context_data = {
            "user_id": effective_user_id,
            "conversation_id": cmd.conversation_id,
            "n_recent": cmd.n_recent,
        }
        compressed = self._compressor.compress(context_data)
        return CompressContextResult(compressed=compressed)
