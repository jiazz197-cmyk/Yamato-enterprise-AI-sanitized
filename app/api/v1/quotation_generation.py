"""Quotation generation APIs with queueing, async execution and persistence."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.taskmanager import TaskManager, task_manager
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.dependencies import get_db
from app.core.executor import CancellationToken, executor_manager
from app.core.logging import get_logger
from app.core.quotation_dispatcher import quotation_dispatcher
from app.core.security import get_current_user
from app.core.storage import (
    MINIO_BUCKET_NAME,
    STREAM_CHUNK_SIZE,
    delete_from_minio,
    download_object_stream,
    get_minio_client,
    upload_stream_to_minio,
)
from app.integrations.Quotation_Generation.quotation_pipeline import (
    QuotationPipelineCancelledError,
    run_quotation_pipeline,
)
from app.models.orm.file_resource import FileResource
from app.models.orm.platform.user import User, UserRole
from app.models.orm.quotation_task import QuotationTask, QuotationTaskStatus

router = APIRouter()
logger = get_logger("quotation_generation")

SUPPORTED_PDF_TYPES = {"application/pdf"}


class QuotationTaskItemResponse(BaseModel):
    task_id: str
    status: str
    progress: int
    message: str
    owner_id: str
    owner_username: str
    uploaded_file_name: str
    uploaded_file_content_type: str
    uploaded_file_size: int
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class QuotationTaskListResponse(BaseModel):
    total: int
    items: List[QuotationTaskItemResponse]


class QuotationTaskSubmitResponse(BaseModel):
    task_id: str
    status: str
    message: str
    queue_position: int = Field(0, description="0 means not queued")


class CancelTaskResponse(BaseModel):
    success: bool
    message: str
    task_id: str


def _is_admin_like(user: User) -> bool:
    return user.role in (UserRole.admin, UserRole.superuser)


def _serialize_task(task: QuotationTask) -> QuotationTaskItemResponse:
    return QuotationTaskItemResponse(
        task_id=task.task_id,
        status=task.status,
        progress=task.progress,
        message=task.message,
        owner_id=task.owner_id,
        owner_username=task.owner_username,
        uploaded_file_name=task.uploaded_file_name,
        uploaded_file_content_type=task.uploaded_file_content_type,
        uploaded_file_size=task.uploaded_file_size,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        result=task.result_payload,
        error=task.error,
    )


def _mark_task_failed_in_db(task_id: str, error_message: str) -> None:
    db = SessionLocal()
    try:
        task = db.query(QuotationTask).filter(QuotationTask.task_id == task_id).first()
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
        logger.error(f"标记失败状态异常 {task_id}: {exc}", exc_info=True)
    finally:
        db.close()


def _cleanup_task_files(db: Session, task: QuotationTask) -> Dict[str, Any]:
    cleanup_result = {
        "uploaded_file_deleted": False,
        "temp_image_deleted": False,
        "file_record_deleted": False,
    }

    if task.uploaded_file_minio_path:
        cleanup_result["uploaded_file_deleted"] = delete_from_minio(task.uploaded_file_minio_path)

    if task.temp_image_minio_path:
        cleanup_result["temp_image_deleted"] = delete_from_minio(task.temp_image_minio_path)

    if task.uploaded_file_id:
        file_record = db.query(FileResource).filter(FileResource.id == task.uploaded_file_id).first()
        if file_record:
            # Break FK reference first, otherwise deleting file_resource can rollback the whole tx.
            task.uploaded_file_id = None
            db.flush()
            db.delete(file_record)
            cleanup_result["file_record_deleted"] = True

    return cleanup_result


def _safe_cleanup_task_files(db: Session, task: QuotationTask, task_id: str) -> Dict[str, Any]:
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


def _run_async_task_manager_call(coro: Any) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coro)
        return
    loop.create_task(coro)


def _dispatch_for_owner(owner_id: str) -> None:
    db = SessionLocal()
    try:
        dispatch_items = quotation_dispatcher.dequeue_for_owner(db, owner_id)
        for item in dispatch_items:
            try:
                future = executor_manager.submit_task(
                    item.task_id,
                    process_quotation_task_background,
                    item.task_id,
                )
                executor_manager.set_task_owner(item.task_id, item.owner_id)
                future.add_done_callback(
                    lambda _, owner_id=item.owner_id: _dispatch_for_owner(owner_id)
                )
            except Exception as exc:
                logger.error(f"提交报价任务到执行器失败 {item.task_id}: {exc}", exc_info=True)
                _mark_task_failed_in_db(item.task_id, f"执行器提交失败: {exc}")
                _run_async_task_manager_call(
                    task_manager.fail_task(item.task_id, str(exc), "任务提交执行器失败")
                )
    except Exception as exc:
        logger.error(f"调度报价任务失败 owner_id={owner_id}: {exc}", exc_info=True)
        db.rollback()
    finally:
        db.close()


def process_quotation_task_background(token: CancellationToken, task_id: str) -> Dict[str, Any]:
    """Run quotation pipeline in thread pool worker."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    thread_tm = TaskManager.create_thread_safe_instance()
    db = SessionLocal()

    try:
        task = db.query(QuotationTask).filter(QuotationTask.task_id == task_id).first()
        if not task:
            return {"status": "error", "message": f"任务不存在: {task_id}"}

        loop.run_until_complete(thread_tm.start_task(task_id))

        def update_progress(progress: int, message: str) -> None:
            task.progress = max(0, min(100, progress))
            task.message = message
            task.status = QuotationTaskStatus.running.value
            db.commit()
            loop.run_until_complete(thread_tm.update_task_progress(task_id, task.progress, message))

        if token.is_cancelled():
            raise QuotationPipelineCancelledError("任务在启动前被取消")

        update_progress(5, "正在下载上传PDF")
        with download_object_stream(task.uploaded_file_minio_path) as response:
            pdf_bytes = response.read()

        pipeline_result = run_quotation_pipeline(
            pdf_bytes=pdf_bytes,
            original_filename=task.uploaded_file_name,
            progress_callback=update_progress,
            cancel_checker=token.is_cancelled,
        )
        task.temp_image_minio_path = pipeline_result.temp_image_minio_path

        cleanup_result = _safe_cleanup_task_files(db, task, task_id)
        result_payload = pipeline_result.to_dict()
        result_payload["cleanup"] = cleanup_result

        task.status = QuotationTaskStatus.completed.value
        task.progress = 100
        task.message = "任务完成（源文件与中间文件已清理）"
        task.result_payload = result_payload
        task.error = None
        task.completed_at = datetime.utcnow()
        db.commit()

        loop.run_until_complete(thread_tm.complete_task(task_id, result_payload, task.message))
        return {"status": "success", "task_id": task_id}

    except QuotationPipelineCancelledError as exc:
        task = db.query(QuotationTask).filter(QuotationTask.task_id == task_id).first()
        if task:
            cleanup_result = _safe_cleanup_task_files(db, task, task_id)
            task.status = QuotationTaskStatus.cancelled.value
            task.message = "任务已取消"
            task.error = str(exc)
            task.completed_at = datetime.utcnow()
            task.result_payload = {"cleanup": cleanup_result}
            db.commit()
        loop.run_until_complete(thread_tm.fail_task(task_id, str(exc), "任务已取消"))
        return {"status": "cancelled", "task_id": task_id}

    except Exception as exc:
        logger.error(f"报价任务执行失败 {task_id}: {exc}", exc_info=True)
        task = db.query(QuotationTask).filter(QuotationTask.task_id == task_id).first()
        if task:
            cleanup_result = _safe_cleanup_task_files(db, task, task_id)
            task.status = QuotationTaskStatus.failed.value
            task.message = "任务执行失败"
            task.error = str(exc)
            task.completed_at = datetime.utcnow()
            task.result_payload = {"cleanup": cleanup_result}
            db.commit()
        loop.run_until_complete(thread_tm.fail_task(task_id, str(exc), "任务执行失败"))
        return {"status": "error", "task_id": task_id, "error": str(exc)}

    finally:
        try:
            db.close()
        except Exception:
            pass
        try:
            if hasattr(thread_tm, "storage") and hasattr(thread_tm.storage, "redis_client"):
                if thread_tm.storage.redis_client is not None:
                    async def close_redis() -> None:
                        if hasattr(thread_tm.storage.redis_client, "connection_pool"):
                            await thread_tm.storage.redis_client.connection_pool.disconnect()
                        await thread_tm.storage.redis_client.aclose()

                    loop.run_until_complete(close_redis())
        except Exception:
            pass
        finally:
            try:
                if not loop.is_closed():
                    loop.close()
            except Exception:
                pass


def _get_task_or_404(db: Session, task_id: str) -> QuotationTask:
    task = db.query(QuotationTask).filter(QuotationTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return task


def _check_task_permission(task: QuotationTask, current_user: User) -> None:
    if _is_admin_like(current_user):
        return
    if task.owner_id != str(current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该任务")


@router.post("/tasks", response_model=QuotationTaskSubmitResponse, summary="创建报价生成任务")
async def create_quotation_task(
    file: UploadFile = File(..., description="仅支持 PDF 文件"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QuotationTaskSubmitResponse:
    if file.content_type not in SUPPORTED_PDF_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持 PDF 文件")

    file_data = await file.read()
    if not file_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空")
    if len(file_data) > settings.MAX_FILE_SIZE:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="文件超过大小限制")

    suffix = Path(file.filename or "document.pdf").suffix or ".pdf"
    unique_name = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex}{suffix}"
    minio_path = f"quotation/uploads/{unique_name}"

    upload_result = upload_stream_to_minio(
        file_stream=BytesIO(file_data),
        file_name=minio_path,
        file_size=len(file_data),
        content_type=file.content_type or "application/pdf",
    )
    if upload_result.startswith("Error"):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="上传文件到 MinIO 失败")

    file_record = FileResource(
        file_name=file.filename or unique_name,
        unique_name=unique_name,
        minio_object_path=minio_path,
        content_type=file.content_type or "application/pdf",
        file_size=len(file_data),
        uploader=current_user.username,
    )
    db.add(file_record)
    db.flush()

    task_id = await task_manager.create_task(
        task_type="quotation_generation",
        metadata={
            "owner_id": str(current_user.id),
            "owner_username": current_user.username,
            "file_id": file_record.id,
            "file_name": file_record.file_name,
        },
    )

    quotation_task = QuotationTask(
        task_id=task_id,
        owner_id=str(current_user.id),
        owner_username=current_user.username,
        role_snapshot=current_user.role.value,
        status=QuotationTaskStatus.queued.value,
        progress=0,
        message="任务已排队",
        uploaded_file_id=file_record.id,
        uploaded_file_name=file_record.file_name,
        uploaded_file_minio_path=minio_path,
        uploaded_file_content_type=file_record.content_type,
        uploaded_file_size=file_record.file_size or len(file_data),
    )
    db.add(quotation_task)
    db.commit()
    db.refresh(quotation_task)

    executor_manager.set_task_owner(task_id, str(current_user.id))
    _dispatch_for_owner(str(current_user.id))

    db.refresh(quotation_task)
    queue_position = 0
    if quotation_task.status == QuotationTaskStatus.queued.value:
        queue_position = (
            db.query(QuotationTask)
            .filter(
                QuotationTask.owner_id == str(current_user.id),
                QuotationTask.status == QuotationTaskStatus.queued.value,
                QuotationTask.created_at <= quotation_task.created_at,
            )
            .count()
        )

    return QuotationTaskSubmitResponse(
        task_id=quotation_task.task_id,
        status=quotation_task.status,
        message="任务创建成功",
        queue_position=queue_position,
    )


@router.get("/tasks", response_model=QuotationTaskListResponse, summary="查询报价任务列表")
async def list_quotation_tasks(
    status_filter: Optional[str] = Query(None, alias="status", description="按状态过滤"),
    owner_username: Optional[str] = Query(None, description="管理员可按用户名过滤"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QuotationTaskListResponse:
    query = db.query(QuotationTask)

    if not _is_admin_like(current_user):
        query = query.filter(QuotationTask.owner_id == str(current_user.id))
    elif owner_username:
        query = query.filter(QuotationTask.owner_username == owner_username)

    if status_filter:
        query = query.filter(QuotationTask.status == status_filter)

    tasks = query.order_by(QuotationTask.created_at.desc()).limit(limit).all()
    return QuotationTaskListResponse(total=len(tasks), items=[_serialize_task(task) for task in tasks])


@router.get("/tasks/{task_id}", response_model=QuotationTaskItemResponse, summary="查询报价任务详情")
async def get_quotation_task(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QuotationTaskItemResponse:
    task = _get_task_or_404(db, task_id)
    _check_task_permission(task, current_user)
    return _serialize_task(task)


@router.post("/tasks/{task_id}/cancel", response_model=CancelTaskResponse, summary="取消报价任务")
async def cancel_quotation_task(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CancelTaskResponse:
    task = _get_task_or_404(db, task_id)
    _check_task_permission(task, current_user)

    if task.status in {
        QuotationTaskStatus.completed.value,
        QuotationTaskStatus.failed.value,
        QuotationTaskStatus.cancelled.value,
    }:
        return CancelTaskResponse(success=False, message="任务已结束，无法取消", task_id=task_id)

    if task.status == QuotationTaskStatus.queued.value:
        task.status = QuotationTaskStatus.cancelled.value
        task.message = "任务已取消"
        task.error = "用户取消"
        task.completed_at = datetime.utcnow()
        db.commit()
        await task_manager.fail_task(task.task_id, "用户取消", "任务已取消")
        _dispatch_for_owner(task.owner_id)
        return CancelTaskResponse(success=True, message="排队任务已取消", task_id=task_id)

    cancelled = executor_manager.cancel_task(task.task_id)
    if not cancelled:
        # Executor state can be lost after restart while DB status remains running.
        # Fallback to DB cancellation so UI can leave "running" state.
        task.status = QuotationTaskStatus.cancelled.value
        task.message = "任务已取消（执行器未持有该任务）"
        task.error = "用户取消"
        task.completed_at = datetime.utcnow()
        db.commit()
        await task_manager.fail_task(task.task_id, "用户取消", "任务已取消")
        _dispatch_for_owner(task.owner_id)
        return CancelTaskResponse(success=True, message="任务已标记取消", task_id=task_id)

    task.message = "任务正在取消"
    db.commit()
    return CancelTaskResponse(success=True, message="取消请求已发送", task_id=task_id)


@router.get("/tasks/{task_id}/file", summary="查看或下载任务上传文件")
async def get_quotation_task_file(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = _get_task_or_404(db, task_id)
    _check_task_permission(task, current_user)

    try:
        client = get_minio_client()
        client.stat_object(MINIO_BUCKET_NAME, task.uploaded_file_minio_path)
    except Exception:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="文件已清理，当前不可查看")

    def stream_file():
        with download_object_stream(task.uploaded_file_minio_path) as response:
            for chunk in response.stream(STREAM_CHUNK_SIZE):
                yield chunk

    return StreamingResponse(
        stream_file(),
        media_type=task.uploaded_file_content_type,
        headers={"Content-Disposition": f'attachment; filename="{task.uploaded_file_name}"'},
    )

