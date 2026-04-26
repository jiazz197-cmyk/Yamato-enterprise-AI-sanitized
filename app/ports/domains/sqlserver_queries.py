"""SQL Server query outbound ports."""

from __future__ import annotations

from typing import Any, Protocol


class U8BomInventoryQueryPort(Protocol):
    def run(self, payload: Any) -> Any:
        ...


class PdmBomQueryPort(Protocol):
    def run(self, payload: Any) -> Any:
        ...
