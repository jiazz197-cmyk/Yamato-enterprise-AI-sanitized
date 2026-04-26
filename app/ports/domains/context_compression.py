"""Context compression outbound port."""

from __future__ import annotations

from typing import Any, Protocol


class ContextCompressorPort(Protocol):
    def compress(self, context_data: dict) -> Any:
        ...
