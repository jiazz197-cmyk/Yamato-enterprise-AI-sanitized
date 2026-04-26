"""Cross-cutting identity view for use cases and ports (no ORM)."""

from __future__ import annotations

from typing import Protocol


class CurrentUserPort(Protocol):
    """Minimal current-user view for authorization and auditing in use cases."""

    id: object
    username: str
    name: str
    role: object
