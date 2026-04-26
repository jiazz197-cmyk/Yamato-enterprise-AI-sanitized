"""Quotation adapters implementing ports on top of current infra."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import APIException
from app.core.storage import upload_stream_to_minio
from app.integrations.Quotation_Generation.quotation_task_workers import (
    dispatch_quotation_phase2,
    dispatch_quotation_queue_for_owner,
    safe_cleanup_quotation_task_files,
)
from app.models.orm.file_resource import FileResource
from app.models.orm.quotation_task import QuotationTask, QuotationTaskStatus
from app.ports.contracts.tasking import TaskDispatchPort
from app.ports.domains.quotation import FileStoragePort, QuotationTaskRepoPort
from app.ports.dto.quotation import QuotationTaskSnapshot


class MinioFileStorageAdapter(FileStoragePort):
    def upload_pdf(self, *, object_path: str, file_bytes: bytes, content_type: str) -> None:
        upload_result = upload_stream_to_minio(
            file_stream=BytesIO(file_bytes),
            file_name=object_path,
            file_size=len(file_bytes),
            content_type=content_type,
        )
        if isinstance(upload_result, str) and upload_result.startswith("Error"):
            raise APIException(
                "上传文件到 MinIO 失败",
                status_code=500,
                error_code="MINIO_UPLOAD_FAILED",
            )


class SqlAlchemyQuotationTaskRepoAdapter(QuotationTaskRepoPort):
    def __init__(self, db: Session):
        self._db = db

    @staticmethod
    def _to_snapshot(task: QuotationTask) -> QuotationTaskSnapshot:
        return QuotationTaskSnapshot(
            task_id=task.task_id,
            owner_id=task.owner_id,
            owner_username=task.owner_username,
            role_snapshot=task.role_snapshot,
            status=task.status,
            progress=task.progress,
            message=task.message,
            uploaded_file_id=task.uploaded_file_id,
            uploaded_file_name=task.uploaded_file_name,
            uploaded_file_minio_path=task.uploaded_file_minio_path,
            uploaded_file_content_type=task.uploaded_file_content_type,
            uploaded_file_size=task.uploaded_file_size,
            created_at=task.created_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
            result_payload=task.result_payload,
            error=task.error,
        )

    def _get_task_entity(self, task_id: str) -> Optional[QuotationTask]:
        return self._db.query(QuotationTask).filter(QuotationTask.task_id == task_id).first()

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
        file_record = FileResource(
            file_name=file_name,
            unique_name=unique_name,
            minio_object_path=minio_path,
            content_type=content_type,
            file_size=file_size,
            uploader=uploader,
        )
        self._db.add(file_record)
        self._db.flush()
        return int(file_record.id)

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
        quotation_task = QuotationTask(
            task_id=task_id,
            owner_id=owner_id,
            owner_username=owner_username,
            role_snapshot=role_snapshot,
            status=QuotationTaskStatus.queued.value,
            progress=0,
            message="任务已排队",
            uploaded_file_id=uploaded_file_id,
            uploaded_file_name=uploaded_file_name,
            uploaded_file_minio_path=uploaded_file_minio_path,
            uploaded_file_content_type=uploaded_file_content_type,
            uploaded_file_size=uploaded_file_size,
        )
        self._db.add(quotation_task)
        self._db.commit()
        self._db.refresh(quotation_task)
        return self._to_snapshot(quotation_task)

    def get_task(self, task_id: str) -> Optional[QuotationTaskSnapshot]:
        task = self._get_task_entity(task_id)
        if task is None:
            return None
        return self._to_snapshot(task)

    def patch_task(self, task_id: str, updates: Dict[str, Any]) -> QuotationTaskSnapshot:
        task = self._get_task_entity(task_id)
        if task is None:
            raise APIException("任务不存在", status_code=404, error_code="NOT_FOUND")

        for key, value in updates.items():
            setattr(task, key, value)

        self._db.commit()
        self._db.refresh(task)
        return self._to_snapshot(task)

    def count_owner_queued_before(self, owner_id: str, created_at: datetime) -> int:
        return (
            self._db.query(QuotationTask)
            .filter(
                QuotationTask.owner_id == owner_id,
                QuotationTask.status == QuotationTaskStatus.queued.value,
                QuotationTask.created_at <= created_at,
            )
            .count()
        )

    def cleanup_task_files(self, task_id: str) -> Dict[str, Any]:
        task = self._get_task_entity(task_id)
        if task is None:
            raise APIException("任务不存在", status_code=404, error_code="NOT_FOUND")
        return safe_cleanup_quotation_task_files(self._db, task, task_id)


class QuotationDispatchAdapter(TaskDispatchPort):
    def dispatch_owner_queue(self, owner_id: str) -> None:
        dispatch_quotation_queue_for_owner(owner_id)

    def dispatch_phase2(self, task_id: str, owner_id: str) -> None:
        dispatch_quotation_phase2(task_id, owner_id)
