"""Quotation generation API: queueing, async execution, persistence."""

from __future__ import annotations

from datetime import datetime
import ipaddress
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm import defer

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


def _build_trusted_proxy_networks() -> list[Any]:
    networks: list[Any] = []
    for raw in settings.TRUSTED_PROXIES:
        value = str(raw).strip()
        if not value:
            continue
        try:
            if "/" in value:
                networks.append(ipaddress.ip_network(value, strict=False))
            else:
                ip = ipaddress.ip_address(value)
                prefix = 32 if ip.version == 4 else 128
                networks.append(ipaddress.ip_network(f"{ip}/{prefix}", strict=False))
        except ValueError:
            logger.warning("Ignored invalid trusted proxy config: %s", value)
    return networks


_TRUSTED_PROXY_NETWORKS = _build_trusted_proxy_networks()


def _is_trusted_proxy(client_ip: str) -> bool:
    if not _TRUSTED_PROXY_NETWORKS:
        return False
    try:
        ip_obj = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    return any(ip_obj in network for network in _TRUSTED_PROXY_NETWORKS)


def _extract_request_client_ip(request: Request) -> str:
    direct_ip = (request.client.host if request.client else "") or "unknown"
    if not settings.TRUST_PROXY_HEADERS:
        return direct_ip
    if not _is_trusted_proxy(direct_ip):
        return direct_ip

    x_forwarded_for = request.headers.get("x-forwarded-for", "")
    if not x_forwarded_for:
        return direct_ip

    first_hop = x_forwarded_for.split(",", 1)[0].strip()
    try:
        ipaddress.ip_address(first_hop)
    except ValueError:
        logger.warning("Invalid X-Forwarded-For value: %s", x_forwarded_for)
        return direct_ip
    return first_hop


def _build_content_disposition(filename: str) -> str:
    cleaned = str(filename or "download.bin").replace("\r", "").replace("\n", "").replace('"', "")
    ascii_fallback = cleaned.encode("ascii", errors="ignore").decode("ascii").strip() or "download.bin"
    utf8_encoded = quote(cleaned)
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{utf8_encoded}"


def _compact_query_result(value: Any) -> Any:
    if not isinstance(value, dict):
        return value

    compact = {key: item for key, item in value.items() if key != "items"}
    items = value.get("items")
    if isinstance(items, list):
        compact["items_count"] = len(items)
    return compact


def _compact_u8_result_by_type(value: Any) -> Any:
    if not isinstance(value, dict):
        return value

    compact = {key: item for key, item in value.items() if key != "items"}
    groups = value.get("items")
    if isinstance(groups, list):
        compact["items_count"] = len(groups)
        compact["items"] = [_compact_query_result(group) for group in groups]
    return compact


def _compact_result_payload(payload: Any, *, include_pdm_items: bool) -> Any:
    if not isinstance(payload, dict):
        return payload

    compact = dict(payload)
    compact["__result_compact"] = True
    compact["pdm_result"] = (
        payload.get("pdm_result")
        if include_pdm_items
        else _compact_query_result(payload.get("pdm_result"))
    )
    compact["u8_result"] = _compact_query_result(payload.get("u8_result"))
    compact["u8_result_by_type"] = _compact_u8_result_by_type(payload.get("u8_result_by_type"))
    return compact


def _serialize_task(
    task: QuotationTask,
    *,
    full_result: bool = False,
    load_result_payload: bool = True,
) -> QuotationTaskItemResponse:
    if load_result_payload:
        result_payload = task.result_payload
    else:
        result_payload = {"__result_compact": True, "__result_omitted": True}

    if not full_result and load_result_payload:
        result_payload = _compact_result_payload(
            result_payload,
            include_pdm_items=task.status == "awaiting_approval",
        )

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
        result=result_payload,
        error=task.error,
    )


def _get_task_or_404(db: Session, task_id: str, *, defer_result: bool = False) -> QuotationTask:
    query = db.query(QuotationTask)
    if defer_result:
        query = query.options(defer(QuotationTask.result_payload))
    task = query.filter(QuotationTask.task_id == task_id).first()
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
    request: Request,
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
            owner_ip=_extract_request_client_ip(request),
            role_snapshot=current_user.role.value,
        )
    )
    return QuotationTaskSubmitResponse(**result.__dict__)


@router.get("/tasks", response_model=QuotationTaskListResponse, summary="查询报价任务列表")
async def list_quotation_tasks(
    status_filter: Optional[str] = Query(None, alias="status", description="按状态过滤"),
    owner_username: Optional[str] = Query(None, description="管理员可按用户名过滤"),
    limit: int = Query(100, ge=1, le=500),
    full_result: bool = Query(False, description="是否返回完整任务结果；默认仅返回摘要，避免大 U8 结果卡住前端"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QuotationTaskListResponse:
    query = db.query(QuotationTask)
    if not full_result:
        query = query.options(defer(QuotationTask.result_payload))
    if not _is_admin_like(current_user):
        query = query.filter(QuotationTask.owner_id == str(current_user.id))
    elif owner_username:
        query = query.filter(QuotationTask.owner_username == owner_username)
    if status_filter:
        query = query.filter(QuotationTask.status == status_filter)
    tasks = query.order_by(QuotationTask.created_at.desc()).limit(limit).all()
    return QuotationTaskListResponse(
        total=len(tasks),
        items=[
            _serialize_task(
                task,
                full_result=full_result,
                load_result_payload=full_result or task.status == "awaiting_approval",
            )
            for task in tasks
        ],
    )


@router.get("/tasks/{task_id}", response_model=QuotationTaskItemResponse, summary="查询报价任务详情")
async def get_quotation_task(
    task_id: str,
    full_result: bool = Query(False, description="是否返回完整任务结果；默认仅返回摘要，避免大 U8 结果卡住前端"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QuotationTaskItemResponse:
    task = _get_task_or_404(db, task_id, defer_result=not full_result)
    _check_task_permission(task, current_user)
    return _serialize_task(
        task,
        full_result=full_result,
        load_result_payload=full_result or task.status == "awaiting_approval",
    )


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
        headers={"Content-Disposition": _build_content_disposition(task.uploaded_file_name)},
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
        headers={"Content-Disposition": _build_content_disposition(safe_name)},
    )
