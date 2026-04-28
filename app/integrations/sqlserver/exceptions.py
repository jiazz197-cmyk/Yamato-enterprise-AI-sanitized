"""SQL Server integration errors."""

from __future__ import annotations

from typing import Callable, Optional

from app.ports.domains.sqlserver_queries import QueryCancelledError

__all__ = ["QueryCancelledError", "raise_if_cancelled"]


def raise_if_cancelled(cancel_checker: Optional[Callable[[], bool]]) -> None:
    if cancel_checker is not None and cancel_checker():
        raise QueryCancelledError("cancelled")
