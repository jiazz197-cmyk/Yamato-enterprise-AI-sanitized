"""Usecase: create quotation generation task."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

from app.core.exceptions import APIException
from app.ports.contracts.tasking import TaskDispatchPort, TaskExecutionPort, TaskStatePort
from app.ports.domains.quotation import FileStoragePort, QuotationTaskRepoPort

SUPPORTED_PDF_TYPES = {"application/pdf"}


@dataclass
class CreateQuotationTaskCommand:
    file_name: Optional[str]
    task_name: Optional[str]
    content_type: Optional[str]
    file_bytes: bytes
    max_file_size: int
    owner_id: str
    owner_username: str
    owner_ip: Optional[str]
    role_snapshot: str


@dataclass
class CreateQuotationTaskResult:
    task_id: str
    status: str
    message: str
    queue_position: int


class CreateQuotationTaskUseCase:
    def __init__(
        self,
        task_state: TaskStatePort,
        task_repo: QuotationTaskRepoPort,
        file_storage: FileStoragePort,
        task_execution: TaskExecutionPort,
        task_dispatch: TaskDispatchPort,
    ):
        self._task_state = task_state
        self._task_repo = task_repo
        self._file_storage = file_storage
        self._task_execution = task_execution
        self._task_dispatch = task_dispatch

    async def execute(self, cmd: CreateQuotationTaskCommand) -> CreateQuotationTaskResult:
        content_type = (cmd.content_type or "application/pdf").strip()
        if content_type not in SUPPORTED_PDF_TYPES:
            raise APIException("仅支持 PDF 文件", status_code=400, error_code="INVALID_FILE_TYPE")
        if not cmd.file_bytes:
            raise APIException("上传文件为空", status_code=400, error_code="EMPTY_FILE")
        if len(cmd.file_bytes) > cmd.max_file_size:
            raise APIException("文件超过大小限制", status_code=413, error_code="FILE_TOO_LARGE")

        suffix = Path(cmd.file_name or "document.pdf").suffix or ".pdf"
        unique_name = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex}{suffix}"
        minio_path = f"quotation/uploads/{unique_name}"
        display_name = str(cmd.task_name or "").strip() or (cmd.file_name or unique_name)

        self._file_storage.upload_pdf(
            object_path=minio_path,
            file_bytes=cmd.file_bytes,
            content_type=content_type,
        )

        stored_file_id = self._task_repo.create_file_record(
            file_name=cmd.file_name or unique_name,
            unique_name=unique_name,
            minio_path=minio_path,
            content_type=content_type,
            file_size=len(cmd.file_bytes),
            uploader=cmd.owner_username,
        )

        task_id = await self._task_state.create_task(
            task_type="quotation_generation",
            metadata={
                "owner_id": cmd.owner_id,
                "owner_username": cmd.owner_username,
                "owner_ip": cmd.owner_ip,
                "file_id": stored_file_id,
                "file_name": cmd.file_name or unique_name,
                "task_name": display_name,
            },
        )

        task = self._task_repo.create_task(
            task_id=task_id,
            owner_id=cmd.owner_id,
            owner_username=cmd.owner_username,
            owner_ip=cmd.owner_ip,
            role_snapshot=cmd.role_snapshot,
            uploaded_file_id=stored_file_id,
            uploaded_file_name=cmd.file_name or unique_name,
            display_name=display_name,
            uploaded_file_minio_path=minio_path,
            uploaded_file_content_type=content_type,
            uploaded_file_size=len(cmd.file_bytes),
        )

        self._task_execution.set_task_owner(task_id, cmd.owner_id)
        self._task_dispatch.dispatch_owner_queue(cmd.owner_id)
        task = self._task_repo.get_task(task_id) or task

        queue_position = 0
        if task.status == "queued":
            queue_position = self._task_repo.count_owner_queued_before(cmd.owner_id, task.created_at)

        return CreateQuotationTaskResult(
            task_id=task.task_id,
            status=task.status,
            message="任务创建成功",
            queue_position=queue_position,
        )
