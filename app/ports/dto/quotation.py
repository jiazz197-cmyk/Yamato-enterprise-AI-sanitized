"""DTO: quotation task and stored file summary (quotation generation line)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class StoredFile:
    unique_name: str
    minio_path: str
    content_type: str
    file_size: int


@dataclass
class QuotationTaskSnapshot:
    task_id: str
    owner_id: str
    owner_username: str
    owner_ip: Optional[str]
    role_snapshot: str
    status: str
    progress: int
    message: str
    uploaded_file_id: Optional[int]
    uploaded_file_name: str
    display_name: str
    uploaded_file_minio_path: str
    uploaded_file_content_type: str
    uploaded_file_size: int
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    result_payload: Optional[Dict[str, Any]]
    error: Optional[str]
