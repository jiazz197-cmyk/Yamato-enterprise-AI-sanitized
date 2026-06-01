"""Quotation domain entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class QuotationTaskStatus(str, Enum):
    """Domain enumeration for quotation task lifecycle statuses."""

    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    awaiting_approval = "awaiting_approval"


@dataclass
class QuotationTaskEntity:
    """Aggregate root for quotation generation tasks.

    Represents the core business entity independent of persistence concerns.
    """

    task_id: str
    owner_id: str
    owner_username: str
    status: QuotationTaskStatus = QuotationTaskStatus.queued
    progress: int = 0
    message: str = ""
    uploaded_file_name: str = ""
    display_name: str = ""
    uploaded_file_content_type: str = ""
    uploaded_file_size: int = 0
    owner_ip: Optional[str] = None
    role_snapshot: str = "user"
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result_payload: Optional[dict] = None
    error: Optional[str] = None

    def is_terminal(self) -> bool:
        return self.status in (
            QuotationTaskStatus.completed,
            QuotationTaskStatus.failed,
            QuotationTaskStatus.cancelled,
        )
