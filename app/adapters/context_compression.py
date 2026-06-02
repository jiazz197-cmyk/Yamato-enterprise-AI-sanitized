"""Adapter: context compression integration."""

from __future__ import annotations

from typing import Any

from app.core.exceptions import ExternalServiceError
from app.integrations.context_compression import (
    LlmEndpointMisconfiguredError,
    compress_context,
)
from app.ports.domains.context_compression import ContextCompressorPort


class IntegrationContextCompressorAdapter(ContextCompressorPort):
    async def compress(self, context_data: dict) -> Any:
        try:
            return await compress_context(context_data)
        except LlmEndpointMisconfiguredError as e:
            raise ExternalServiceError("context_compression", str(e)) from e
