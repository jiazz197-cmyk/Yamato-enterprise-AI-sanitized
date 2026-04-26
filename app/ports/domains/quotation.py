"""Quotation generation outbound ports."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional, Protocol

from app.ports.dto.quotation import QuotationTaskSnapshot


class FileStoragePort(Protocol):
    """Object storage abstraction for quotation files."""

    def upload_pdf(
        self,
        *,
        object_path: str,
        file_bytes: bytes,
        content_type: str,
    ) -> None:
        ...


class QuotationTaskRepoPort(Protocol):
    """Persistence boundary for quotation task + file metadata."""

    def create_file_record(
        self,
        *,
        file_name: str,
        unique_name: str,
        minio_path: str,
        content_type: str,
        file_size: int,
        uploader: str,
    ) -> int:
        ...

    def create_task(
        self,
        *,
        task_id: str,
        owner_id: str,
        owner_username: str,
        role_snapshot: str,
        uploaded_file_id: int,
        uploaded_file_name: str,
        uploaded_file_minio_path: str,
        uploaded_file_content_type: str,
        uploaded_file_size: int,
    ) -> QuotationTaskSnapshot:
        ...

    def get_task(self, task_id: str) -> Optional[QuotationTaskSnapshot]:
        ...

    def patch_task(self, task_id: str, updates: Dict[str, Any]) -> QuotationTaskSnapshot:
        ...

    def count_owner_queued_before(self, owner_id: str, created_at: datetime) -> int:
        ...

    def cleanup_task_files(self, task_id: str) -> Dict[str, Any]:
        ...
