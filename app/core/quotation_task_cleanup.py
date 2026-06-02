"""Quotation task file cleanup (MinIO objects + file_resource rows)."""

from __future__ import annotations

from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.storage import delete_from_minio
from app.models.orm.file_resource import FileResource
from app.models.orm.quotation_task import QuotationTask

logger = get_logger("quotation_generation")


def _cleanup_task_files(db: Session, task: QuotationTask) -> Dict[str, Any]:
    cleanup_result = {
        "uploaded_file_deleted": False,
        "temp_image_deleted": False,
        "file_record_deleted": False,
        "xlsx_deleted": False,
    }

    if task.uploaded_file_minio_path:
        cleanup_result["uploaded_file_deleted"] = delete_from_minio(task.uploaded_file_minio_path)

    if task.temp_image_minio_path:
        cleanup_result["temp_image_deleted"] = delete_from_minio(task.temp_image_minio_path)

    payload = task.result_payload if isinstance(task.result_payload, dict) else {}
    xlsx_path = payload.get("u8_result_by_type_xlsx_minio_path")
    if isinstance(xlsx_path, str) and xlsx_path.strip():
        cleanup_result["xlsx_deleted"] = delete_from_minio(xlsx_path.strip())

    if task.uploaded_file_id:
        file_record = db.query(FileResource).filter(FileResource.id == task.uploaded_file_id).first()
        if file_record:
            # Break FK reference first, otherwise deleting file_resource can rollback the whole tx.
            task.uploaded_file_id = None
            db.flush()
            db.delete(file_record)
            cleanup_result["file_record_deleted"] = True

    return cleanup_result


def safe_cleanup_quotation_task_files(db: Session, task: QuotationTask, task_id: str) -> Dict[str, Any]:
    try:
        return _cleanup_task_files(db, task)
    except Exception as exc:
        logger.error(f"清理报价任务文件失败 {task_id}: {exc}", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        return {
            "uploaded_file_deleted": False,
            "temp_image_deleted": False,
            "file_record_deleted": False,
            "cleanup_error": str(exc),
        }


async def _cleanup_task_files_async(db: AsyncSession, task: QuotationTask) -> Dict[str, Any]:
    cleanup_result = {
        "uploaded_file_deleted": False,
        "temp_image_deleted": False,
        "file_record_deleted": False,
        "xlsx_deleted": False,
    }

    if task.uploaded_file_minio_path:
        cleanup_result["uploaded_file_deleted"] = delete_from_minio(task.uploaded_file_minio_path)

    if task.temp_image_minio_path:
        cleanup_result["temp_image_deleted"] = delete_from_minio(task.temp_image_minio_path)

    payload = task.result_payload if isinstance(task.result_payload, dict) else {}
    xlsx_path = payload.get("u8_result_by_type_xlsx_minio_path")
    if isinstance(xlsx_path, str) and xlsx_path.strip():
        cleanup_result["xlsx_deleted"] = delete_from_minio(xlsx_path.strip())

    if task.uploaded_file_id:
        result = await db.execute(
            select(FileResource).where(FileResource.id == task.uploaded_file_id)
        )
        file_record = result.scalars().first()
        if file_record:
            task.uploaded_file_id = None
            await db.flush()
            await db.delete(file_record)
            cleanup_result["file_record_deleted"] = True

    return cleanup_result


async def safe_cleanup_quotation_task_files_async(
    db: AsyncSession, task: QuotationTask, task_id: str
) -> Dict[str, Any]:
    try:
        return await _cleanup_task_files_async(db, task)
    except Exception as exc:
        logger.error(f"清理报价任务文件失败 {task_id}: {exc}", exc_info=True)
        try:
            await db.rollback()
        except Exception:
            pass
        return {
            "uploaded_file_deleted": False,
            "temp_image_deleted": False,
            "file_record_deleted": False,
            "cleanup_error": str(exc),
        }


async def cleanup_task_files_by_id(task_id: str) -> Dict[str, Any]:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(QuotationTask).where(QuotationTask.task_id == task_id)
            )
            task = result.scalars().first()
            if not task:
                return {}
            cleanup_result = await safe_cleanup_quotation_task_files_async(
                db, task, task_id
            )
            await db.commit()
            return cleanup_result
        except Exception:
            await db.rollback()
            raise


def cleanup_task_files_by_id_sync(task_id: str) -> Dict[str, Any]:
    """Sync wrapper for worker threads — uses thread-local sync session."""
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        try:
            result = db.execute(
                select(QuotationTask).where(QuotationTask.task_id == task_id)
            )
            task = result.scalars().first()
            if not task:
                return {}
            cleanup_result = safe_cleanup_quotation_task_files(db, task, task_id)
            db.commit()
            return cleanup_result
        except Exception:
            db.rollback()
            raise
