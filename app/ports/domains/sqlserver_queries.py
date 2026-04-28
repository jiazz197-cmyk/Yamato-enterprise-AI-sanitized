"""SQL Server query outbound ports."""

from __future__ import annotations

from typing import Any, Callable, Optional, Protocol

CancelChecker = Optional[Callable[[], bool]]


class QueryCancelledError(RuntimeError):
    """Raised when an outbound SQL-backed query is aborted via cancel_checker."""


class U8BomInventoryQueryPort(Protocol):
    def run(self, payload: Any, *, cancel_checker: CancelChecker = None) -> Any:
        ...


class PdmBomQueryPort(Protocol):
    def run(self, payload: Any, *, cancel_checker: CancelChecker = None) -> Any:
        ...
