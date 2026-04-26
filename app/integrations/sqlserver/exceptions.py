"""SQL Server integration errors."""

from __future__ import annotations

from typing import Callable, Optional


class QueryCancelledError(RuntimeError):
    """Raised when a SQL query loop is aborted via cancel_checker."""


def raise_if_cancelled(cancel_checker: Optional[Callable[[], bool]]) -> None:
    if cancel_checker is not None and cancel_checker():
        raise QueryCancelledError("cancelled")
