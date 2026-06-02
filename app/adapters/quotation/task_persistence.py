"""Quotation task persistence adapter: encapsulated ORM operations for background workers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.orm.quotation_task import QuotationTask, QuotationTaskStatus

logger = get_logger("quotation.task_persistence")


class QuotationTaskPersistenceAdapter:
    """Encapsulates direct ORM operations needed by quotation background workers.

    Each method manages its own session lifecycle.
    """

    async def mark_task_failed(self, task_id: str, error_message: str) -> None:
        async with AsyncSessionLocal() as db:
            try:
                result = await db.execute(
                    select(QuotationTask).where(QuotationTask.task_id == task_id)
                )
                task = result.scalars().first()
                if not task:
                    return
                task.status = QuotationTaskStatus.failed.value
                task.progress = min(task.progress, 99)
                task.error = error_message
                task.message = "任务提交执行器失败"
                task.completed_at = datetime.utcnow()
                await db.commit()
            except Exception as exc:
                await db.rollback()
                logger.error("标记失败状态异常 %s: %s", task_id, exc, exc_info=True)

    async def patch_task_fields(self, task_id: str, updates: Dict[str, Any]) -> None:
        async with AsyncSessionLocal() as db:
            try:
                result = await db.execute(
                    select(QuotationTask).where(QuotationTask.task_id == task_id)
                )
                task = result.scalars().first()
                if not task:
                    return
                for key, value in updates.items():
                    setattr(task, key, value)
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def get_task_payload(self, task_id: str) -> Dict[str, Any]:
        """Fetch task fields needed by workers without returning an ORM object."""
        async with AsyncSessionLocal() as db:
            return await self._fetch_task_payload(db, task_id)

    async def _fetch_task_payload(self, db: AsyncSession, task_id: str) -> Dict[str, Any]:
        result = await db.execute(
            select(QuotationTask).where(QuotationTask.task_id == task_id)
        )
        task = result.scalars().first()
        if not task:
            return {}
        return {
            "task_id": task.task_id,
            "status": task.status,
            "progress": task.progress,
            "result_payload": dict(task.result_payload or {}),
            "uploaded_file_minio_path": task.uploaded_file_minio_path,
            "uploaded_file_name": task.uploaded_file_name,
        }

    def get_task_payload_sync(self, task_id: str) -> Dict[str, Any]:
        """Sync wrapper for worker threads — uses thread-local sync session."""
        from app.core.database import SessionLocal

        with SessionLocal() as db:
            result = db.execute(
                select(QuotationTask).where(QuotationTask.task_id == task_id)
            )
            task = result.scalars().first()
            if not task:
                return {}
            return {
                "task_id": task.task_id,
                "status": task.status,
                "progress": task.progress,
                "result_payload": dict(task.result_payload or {}),
                "uploaded_file_minio_path": task.uploaded_file_minio_path,
                "uploaded_file_name": task.uploaded_file_name,
            }

    def patch_task_fields_sync(self, task_id: str, updates: Dict[str, Any]) -> None:
        """Sync wrapper for worker threads — uses thread-local sync session."""
        from app.core.database import SessionLocal

        with SessionLocal() as db:
            try:
                result = db.execute(
                    select(QuotationTask).where(QuotationTask.task_id == task_id)
                )
                task = result.scalars().first()
                if not task:
                    return
                for key, value in updates.items():
                    setattr(task, key, value)
                db.commit()
            except Exception:
                db.rollback()
                raise

    def mark_task_failed_sync(self, task_id: str, error_message: str) -> None:
        """Sync wrapper for worker threads — uses thread-local sync session."""
        from app.core.database import SessionLocal

        with SessionLocal() as db:
            try:
                result = db.execute(
                    select(QuotationTask).where(QuotationTask.task_id == task_id)
                )
                task = result.scalars().first()
                if not task:
                    return
                task.status = QuotationTaskStatus.failed.value
                task.progress = min(task.progress, 99)
                task.error = error_message
                task.message = "任务提交执行器失败"
                task.completed_at = datetime.utcnow()
                db.commit()
            except Exception as exc:
                db.rollback()
                logger.error("标记失败状态异常 %s: %s", task_id, exc, exc_info=True)
