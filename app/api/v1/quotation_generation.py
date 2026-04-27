"""Quotation generation API: queueing, async execution, persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.adapters.quotation import (
    MinioFileStorageAdapter,
    QuotationDispatchAdapter,
    SqlAlchemyQuotationTaskRepoAdapter,
)
from app.adapters.tasking import TaskManagerStateAdapter, ThreadPoolTaskExecutionAdapter
from app.core.config import settings
from app.core.dependencies import get_db
from app.core.logging import get_logger
from app.core.security import get_current_user
from app.core.storage import (
    MINIO_BUCKET_NAME,
    STREAM_CHUNK_SIZE,
    download_object_stream,
    get_minio_client,
)
from app.models.orm.platform.user import User, UserRole
from app.models.orm.quotation_task import QuotationTask
from app.usecases.quotation.approve_task import (
    ApproveQuotationTaskCommand,
    ApproveQuotationTaskUseCase,
)
from app.usecases.quotation.cancel_task import CancelQuotationTaskCommand, CancelQuotationTaskUseCase
from app.usecases.quotation.create_task import CreateQuotationTaskCommand, CreateQuotationTaskUseCase

router = APIRouter()
logger = get_logger("quotation_generation")

_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

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
    file_data = await file.read()
    usecase = CreateQuotationTaskUseCase(
        task_state=TaskManagerStateAdapter(),
        task_repo=SqlAlchemyQuotationTaskRepoAdapter(db),
        file_storage=MinioFileStorageAdapter(),
        task_execution=ThreadPoolTaskExecutionAdapter(),
        task_dispatch=QuotationDispatchAdapter(),
    )
    result = await usecase.execute(
        CreateQuotationTaskCommand(
            file_name=file.filename,
            content_type=file.content_type,
            file_bytes=file_data,
            max_file_size=settings.MAX_FILE_SIZE,
            owner_id=str(current_user.id),
            owner_username=current_user.username,
            role_snapshot=current_user.role.value,
        )
    )
    return QuotationTaskSubmitResponse(**result.__dict__)


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
    usecase = CancelQuotationTaskUseCase(
        task_repo=SqlAlchemyQuotationTaskRepoAdapter(db),
        task_state=TaskManagerStateAdapter(),
        task_execution=ThreadPoolTaskExecutionAdapter(),
        task_dispatch=QuotationDispatchAdapter(),
    )
    result = await usecase.execute(CancelQuotationTaskCommand(task_id=task_id))
    return CancelTaskResponse(**result.__dict__)


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
    usecase = ApproveQuotationTaskUseCase(
        task_repo=SqlAlchemyQuotationTaskRepoAdapter(db),
        task_state=TaskManagerStateAdapter(),
        task_dispatch=QuotationDispatchAdapter(),
    )
    result = await usecase.execute(
        ApproveQuotationTaskCommand(task_id=task_id, approved_partids=request.approved_partids)
    )
    return ApproveTaskResponse(**result.__dict__)


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


@router.get(
    "/tasks/{task_id}/u8-by-type-workbook",
    summary="下载 Phase2 U8 按 type 分组的 Excel",
)
async def get_quotation_task_u8_by_type_workbook(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = _get_task_or_404(db, task_id)
    _check_task_permission(task, current_user)
    payload = task.result_payload if isinstance(task.result_payload, dict) else {}
    minio_path = payload.get("u8_result_by_type_xlsx_minio_path")
    filename = payload.get("u8_result_by_type_xlsx_filename") or "u8_by_type.xlsx"
    if not minio_path or not isinstance(minio_path, str):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="U8 分组 Excel 未生成或不可用",
        )
    try:
        client = get_minio_client()
        client.stat_object(MINIO_BUCKET_NAME, minio_path)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Excel 已不可用",
        ) from None

    def stream_xlsx():
        with download_object_stream(minio_path) as response:
            for chunk in response.stream(STREAM_CHUNK_SIZE):
                yield chunk

    safe_name = str(filename).replace('"', "")
    return StreamingResponse(
        stream_xlsx(),
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename=\"{safe_name}\"'},
    )
