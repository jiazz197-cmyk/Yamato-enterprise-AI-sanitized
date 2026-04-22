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
    QuotationPipelineError,
    run_phase1_keywords_and_pdm,
    run_phase2_u8_bom_inventory,
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


class ApproveTaskRequest(BaseModel):
    approved_partids: List[str] = Field(
        ...,
        min_length=1,
        description="用户勾选的 PARTID 列表，仅这些将被送入 U8 BOM Inventory",
    )


class ApproveTaskResponse(BaseModel):
    success: bool
    message: str
    task_id: str
    status: str
    approved_count: int


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


# `quotation_tasks.message` is VARCHAR(512); keep a safe headroom when writing.
_MESSAGE_COLUMN_LIMIT = 500


def _clamp_message(message: str, limit: int = _MESSAGE_COLUMN_LIMIT) -> str:
    """Ensure progress messages fit inside quotation_tasks.message (VARCHAR 512)."""
    if message is None:
        return ""
    if len(message) <= limit:
        return message
    suffix = "…(truncated)"
    head = max(0, limit - len(suffix))
    return message[:head] + suffix


def map_parent_inv_code(partid: Any) -> str:
    """PARTID 映射为 U8 ParentInvCode。"""
    if partid is None:
        return ""
    code = str(partid).strip()
    if not code:
        return ""
    if code.startswith("50GB"):
        return f"Z{code[4:]}"
    if code.startswith("50CB"):
        return f"X{code[4:]}"
    if code.startswith("50JC"):
        return f"P{code[4:]}"
    return code


def _convert_pdm_partids_to_u8_codes(partids: List[str]) -> tuple[List[str], List[Dict[str, str]]]:
    """将 PDM PARTID 列表转换为 U8 可查询的 parent_inv_codes。"""
    converted_codes: List[str] = []
    mappings: List[Dict[str, str]] = []
    seen_codes: set[str] = set()

    for partid in partids:
        source = str(partid).strip()
        if not source:
            continue
        mapped = map_parent_inv_code(source)
        if not mapped:
            continue
        mappings.append({"pdm_partid": source, "u8_parent_inv_code": mapped})
        if mapped in seen_codes:
            continue
        seen_codes.add(mapped)
        converted_codes.append(mapped)

    return converted_codes, mappings


def _close_thread_tm(loop: asyncio.AbstractEventLoop, thread_tm: TaskManager) -> None:
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


def process_quotation_task_background(token: CancellationToken, task_id: str) -> Dict[str, Any]:
    """Phase 1 worker: OCR -> keywords_payload -> PDM BOM, then pause for approval."""
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
            safe_message = _clamp_message(message)
            task.progress = max(0, min(100, progress))
            task.message = safe_message
            task.status = QuotationTaskStatus.running.value
            db.commit()
            loop.run_until_complete(
                thread_tm.update_task_progress(task_id, task.progress, safe_message)
            )

        if token.is_cancelled():
            raise QuotationPipelineCancelledError("任务在启动前被取消")

        update_progress(5, "正在下载上传PDF")
        with download_object_stream(task.uploaded_file_minio_path) as response:
            pdf_bytes = response.read()

        phase1_result = run_phase1_keywords_and_pdm(
            pdf_bytes=pdf_bytes,
            original_filename=task.uploaded_file_name,
            progress_callback=update_progress,
            cancel_checker=token.is_cancelled,
        )
        task.temp_image_minio_path = phase1_result.temp_image_minio_path

        result_payload = dict(task.result_payload or {})
        result_payload.update(phase1_result.to_dict())

        if not phase1_result.pdm_partids:
            task.status = QuotationTaskStatus.failed.value
            task.progress = min(task.progress, 99)
            task.message = "PDM 查询未返回任何 PARTID"
            task.error = "PDM 结果为空，无法继续 U8 查询"
            task.completed_at = datetime.utcnow()
            task.result_payload = result_payload
            db.commit()
            loop.run_until_complete(thread_tm.fail_task(task_id, task.error, task.message))
            return {"status": "error", "task_id": task_id, "error": task.error}

        converted_u8_codes, pdm_to_u8_mappings = _convert_pdm_partids_to_u8_codes(
            phase1_result.pdm_partids
        )
        result_payload["u8_parent_inv_codes"] = converted_u8_codes
        result_payload["pdm_to_u8_code_mappings"] = pdm_to_u8_mappings
        logger.info(
            "Phase1 PDM->U8 编码转换完成: task_id=%s, pdm_count=%s, u8_count=%s, sample=%s",
            task_id,
            len(phase1_result.pdm_partids),
            len(converted_u8_codes),
            pdm_to_u8_mappings[:8],
        )

        task.status = QuotationTaskStatus.awaiting_approval.value
        task.progress = 50
        task.message = "等待用户审核 PDM 结果"
        task.result_payload = result_payload
        task.error = None
        db.commit()

        loop.run_until_complete(
            thread_tm.update_task_progress(task_id, task.progress, task.message)
        )
        return {"status": "awaiting_approval", "task_id": task_id}

    except QuotationPipelineCancelledError as exc:
        task = db.query(QuotationTask).filter(QuotationTask.task_id == task_id).first()
        if task:
            cleanup_result = _safe_cleanup_task_files(db, task, task_id)
            existing_payload = dict(task.result_payload or {})
            existing_payload["cleanup"] = cleanup_result
            task.status = QuotationTaskStatus.cancelled.value
            task.message = "任务已取消"
            task.error = str(exc)
            task.completed_at = datetime.utcnow()
            task.result_payload = existing_payload
            db.commit()
        loop.run_until_complete(thread_tm.fail_task(task_id, str(exc), "任务已取消"))
        return {"status": "cancelled", "task_id": task_id}

    except Exception as exc:
        logger.error(f"报价任务 Phase1 执行失败 {task_id}: {exc}", exc_info=True)
        task = db.query(QuotationTask).filter(QuotationTask.task_id == task_id).first()
        if task:
            cleanup_result = _safe_cleanup_task_files(db, task, task_id)
            existing_payload = dict(task.result_payload or {})
            existing_payload["cleanup"] = cleanup_result
            task.status = QuotationTaskStatus.failed.value
            task.message = "Phase1 执行失败"
            task.error = str(exc)
            task.completed_at = datetime.utcnow()
            task.result_payload = existing_payload
            db.commit()
        loop.run_until_complete(thread_tm.fail_task(task_id, str(exc), "Phase1 执行失败"))
        return {"status": "error", "task_id": task_id, "error": str(exc)}

    finally:
        try:
            db.close()
        except Exception:
            pass
        _close_thread_tm(loop, thread_tm)


def process_quotation_task_phase2_background(
    token: CancellationToken, task_id: str
) -> Dict[str, Any]:
    """Phase 2 worker: call U8 BOM Inventory using previously-collected PARTIDs."""
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
            safe_message = _clamp_message(message)
            task.progress = max(0, min(100, progress))
            task.message = safe_message
            task.status = QuotationTaskStatus.running.value
            db.commit()
            loop.run_until_complete(
                thread_tm.update_task_progress(task_id, task.progress, safe_message)
            )

        if token.is_cancelled():
            raise QuotationPipelineCancelledError("任务在启动前被取消")

        existing_payload = dict(task.result_payload or {})
        approved_partids = existing_payload.get("approved_partids")
        if isinstance(approved_partids, list) and approved_partids:
            selected_partids = [str(partid) for partid in approved_partids if str(partid).strip()]
            source = "approved_partids"
        else:
            fallback = existing_payload.get("pdm_partids") or []
            selected_partids = [str(partid) for partid in fallback if str(partid).strip()]
            source = "pdm_partids(fallback)"

        logger.info(
            "Phase2 准备执行 U8 查询: task_id=%s, source=%s, selected_count=%s, sample=%s",
            task_id,
            source,
            len(selected_partids),
            selected_partids[:8],
        )

        if not selected_partids:
            logger.warning(
                "Phase2 缺少可用 PARTID: task_id=%s, payload_keys=%s",
                task_id,
                list(existing_payload.keys()),
            )
            raise QuotationPipelineError("任务缺少已批准的 PARTID 列表，无法继续 U8 查询")

        update_progress(60, f"开始 U8 BOM Inventory 查询（{len(selected_partids)} 项）")

        phase2_result = run_phase2_u8_bom_inventory(
            pdm_partids=selected_partids,
            progress_callback=update_progress,
            cancel_checker=token.is_cancelled,
        )

        _safe_cleanup_task_files(db, task, task_id)

        u8_total = None
        u8_items = None
        if isinstance(phase2_result.u8_result, dict):
            u8_total = phase2_result.u8_result.get("total")
            u8_items = phase2_result.u8_result.get("items")
        logger.info(
            "Phase2 U8 查询结果: task_id=%s, total=%s, items_len=%s",
            task_id,
            u8_total,
            len(u8_items) if isinstance(u8_items, list) else None,
        )

        final_payload: Dict[str, Any] = {
            "keywords_payload": existing_payload.get("keywords_payload"),
            "approved_partids": selected_partids,
            "u8_result": phase2_result.u8_result,
        }

        task.status = QuotationTaskStatus.completed.value
        task.progress = 100
        task.message = "任务完成（U8 BOM Inventory 已返回）"
        task.result_payload = final_payload
        task.error = None
        task.completed_at = datetime.utcnow()
        db.commit()

        loop.run_until_complete(thread_tm.complete_task(task_id, final_payload, task.message))
        return {"status": "success", "task_id": task_id}

    except QuotationPipelineCancelledError as exc:
        task = db.query(QuotationTask).filter(QuotationTask.task_id == task_id).first()
        if task:
            cleanup_result = _safe_cleanup_task_files(db, task, task_id)
            existing_payload = dict(task.result_payload or {})
            existing_payload["cleanup"] = cleanup_result
            task.status = QuotationTaskStatus.cancelled.value
            task.message = "任务已取消"
            task.error = str(exc)
            task.completed_at = datetime.utcnow()
            task.result_payload = existing_payload
            db.commit()
        loop.run_until_complete(thread_tm.fail_task(task_id, str(exc), "任务已取消"))
        return {"status": "cancelled", "task_id": task_id}

    except Exception as exc:
        logger.error(f"报价任务 Phase2 执行失败 {task_id}: {exc}", exc_info=True)
        task = db.query(QuotationTask).filter(QuotationTask.task_id == task_id).first()
        if task:
            # Preserve PDM results for debugging; do not clear result_payload.
            existing_payload = dict(task.result_payload or {})
            task.status = QuotationTaskStatus.failed.value
            task.message = "Phase2 执行失败"
            task.error = str(exc)
            task.completed_at = datetime.utcnow()
            task.result_payload = existing_payload
            db.commit()
        loop.run_until_complete(thread_tm.fail_task(task_id, str(exc), "Phase2 执行失败"))
        return {"status": "error", "task_id": task_id, "error": str(exc)}

    finally:
        try:
            db.close()
        except Exception:
            pass
        _close_thread_tm(loop, thread_tm)


def _dispatch_phase2(task_id: str, owner_id: str) -> None:
    """Submit the Phase 2 worker. Must be called after the DB status flip.

    The executor retains Phase 1's Future under the same task_id for history,
    so we evict it first to allow resubmitting with the same business id.
    """
    try:
        executor_manager.forget_task(task_id)
        future = executor_manager.submit_task(
            task_id,
            process_quotation_task_phase2_background,
            task_id,
        )
        executor_manager.set_task_owner(task_id, owner_id)
        future.add_done_callback(lambda _, oid=owner_id: _dispatch_for_owner(oid))
    except Exception as exc:
        logger.error(f"Phase2 提交执行器失败 {task_id}: {exc}", exc_info=True)
        _mark_task_failed_in_db(task_id, f"执行器提交失败: {exc}")
        _run_async_task_manager_call(
            task_manager.fail_task(task_id, str(exc), "Phase2 提交执行器失败")
        )


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

    if task.status == QuotationTaskStatus.awaiting_approval.value:
        cleanup_result = _safe_cleanup_task_files(db, task, task.task_id)
        existing_payload = dict(task.result_payload or {})
        existing_payload["cleanup"] = cleanup_result
        task.status = QuotationTaskStatus.cancelled.value
        task.message = "任务已取消（审核阶段）"
        task.error = "用户取消"
        task.completed_at = datetime.utcnow()
        task.result_payload = existing_payload
        db.commit()
        await task_manager.fail_task(task.task_id, "用户取消", "任务已取消")
        _dispatch_for_owner(task.owner_id)
        return CancelTaskResponse(success=True, message="审核阶段任务已取消", task_id=task_id)

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


@router.post(
    "/tasks/{task_id}/approve",
    response_model=ApproveTaskResponse,
    summary="同意 PDM 审核并触发 Phase2 (U8 BOM Inventory)",
)
async def approve_quotation_task(
    task_id: str,
    request: ApproveTaskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApproveTaskResponse:
    task = _get_task_or_404(db, task_id)
    _check_task_permission(task, current_user)

    if task.status != QuotationTaskStatus.awaiting_approval.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"任务当前状态为 {task.status}，无法执行审核同意",
        )

    payload = dict(task.result_payload or {})
    available_partids = payload.get("pdm_partids") if isinstance(payload, dict) else None
    if not isinstance(available_partids, list) or not available_partids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="任务缺少 PDM PARTID，无法继续 U8 查询",
        )

    available_set = {str(item).strip() for item in available_partids if str(item).strip()}
    seen: set[str] = set()
    approved_partids: List[str] = []
    unknown_partids: List[str] = []
    for raw in request.approved_partids:
        value = str(raw).strip()
        if not value or value in seen:
            continue
        if value not in available_set:
            unknown_partids.append(value)
            continue
        seen.add(value)
        approved_partids.append(value)

    if unknown_partids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"审核列表包含未知 PARTID: {', '.join(unknown_partids)}",
        )
    if not approved_partids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="审核列表为空，至少需要保留 1 个 PARTID",
        )

    payload["approved_partids"] = approved_partids
    task.result_payload = payload
    task.status = QuotationTaskStatus.running.value
    task.message = f"已同意 {len(approved_partids)}/{len(available_partids)} 项，开始 U8 查询"
    task.progress = max(task.progress, 55)
    task.error = None
    db.commit()

    await task_manager.update_task_progress(task.task_id, task.progress, task.message)

    _dispatch_phase2(task.task_id, task.owner_id)

    return ApproveTaskResponse(
        success=True,
        message="已触发 U8 BOM Inventory 查询",
        task_id=task_id,
        status=task.status,
        approved_count=len(approved_partids),
    )


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

