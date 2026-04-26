"""Quotation generation API: queueing, async execution, persistence."""

from __future__ import annotations

import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_db
from app.core.executor import executor_manager
from app.core.logging import get_logger
from app.core.security import get_current_user
from app.core.storage import (
    MINIO_BUCKET_NAME,
    STREAM_CHUNK_SIZE,
    download_object_stream,
    get_minio_client,
    upload_stream_to_minio,
)
from app.integrations.Quotation_Generation.quotation_task_workers import (
    dispatch_quotation_phase2,
    dispatch_quotation_queue_for_owner,
    safe_cleanup_quotation_task_files,
)
from app.models.orm.file_resource import FileResource
from app.models.orm.platform.user import User, UserRole
from app.core.task_manager import task_manager
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
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="文件超过大小限制"
        )
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="上传文件到 MinIO 失败"
        )
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
    dispatch_quotation_queue_for_owner(str(current_user.id))
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
    return QuotationTaskListResponse(
        total=len(tasks), items=[_serialize_task(task) for task in tasks]
    )


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
        return CancelTaskResponse(
            success=False, message="任务已结束，无法取消", task_id=task_id
        )
    if task.status == QuotationTaskStatus.queued.value:
        task.status = QuotationTaskStatus.cancelled.value
        task.message = "任务已取消"
        task.error = "用户取消"
        task.completed_at = datetime.utcnow()
        db.commit()
        await task_manager.fail_task(task.task_id, "用户取消", "任务已取消")
        dispatch_quotation_queue_for_owner(task.owner_id)
        return CancelTaskResponse(success=True, message="排队任务已取消", task_id=task_id)
    if task.status == QuotationTaskStatus.awaiting_approval.value:
        cleanup_result = safe_cleanup_quotation_task_files(db, task, task.task_id)
        existing_payload = dict(task.result_payload or {})
        existing_payload["cleanup"] = cleanup_result
        task.status = QuotationTaskStatus.cancelled.value
        task.message = "任务已取消（审核阶段）"
        task.error = "用户取消"
        task.completed_at = datetime.utcnow()
        task.result_payload = existing_payload
        db.commit()
        await task_manager.fail_task(task.task_id, "用户取消", "任务已取消")
        dispatch_quotation_queue_for_owner(task.owner_id)
        return CancelTaskResponse(success=True, message="审核阶段任务已取消", task_id=task_id)
    cancelled = executor_manager.cancel_task(task.task_id)
    if not cancelled:
        task.status = QuotationTaskStatus.cancelled.value
        task.message = "任务已取消（执行器未持有该任务）"
        task.error = "用户取消"
        task.completed_at = datetime.utcnow()
        db.commit()
        await task_manager.fail_task(task.task_id, "用户取消", "任务已取消")
        dispatch_quotation_queue_for_owner(task.owner_id)
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
    dispatch_quotation_phase2(task.task_id, task.owner_id)
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
        raise HTTPException(
            status_code=status.HTTP_410_GONE, detail="文件已清理，当前不可查看"
        ) from None

    def stream_file():
        with download_object_stream(task.uploaded_file_minio_path) as response:
            for chunk in response.stream(STREAM_CHUNK_SIZE):
                yield chunk

    return StreamingResponse(
        stream_file(),
        media_type=task.uploaded_file_content_type,
        headers={"Content-Disposition": f'attachment; filename=\"{task.uploaded_file_name}\"'},
    )
