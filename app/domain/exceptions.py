"""Shared domain exceptions."""

from __future__ import annotations


class QueryCancelledError(RuntimeError):
    """Raised when an SQL-backed query is aborted via cancel_checker."""
